"""Offline driver-contract tests; these do not claim an Azure integration test."""
import os
import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from challenge_sql import AzureChallengeStore, SQLConnection, connection_string
from challenge_store import DatabaseUnavailable, create_store

CONFIG = {
    "CHALLENGE_SQL_SERVER": "example.database.windows.net",
    "CHALLENGE_SQL_DATABASE": "challenge-test",
    "CHALLENGE_SQL_CLIENT_ID": "11111111-1111-4111-8111-111111111111",
    "CHALLENGE_TEST_VERSION": "sorting-15-v2",
}


class DriverError(Exception):
    pass


class AzureStoreTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, CONFIG)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.driver = MagicMock()
        self.driver.Error = DriverError
        self.modules = patch.dict("sys.modules", {"mssql_python": self.driver})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.connection = self.driver.connect.return_value
        self.cursor = self.connection.cursor.return_value
        self.cursor.description = [("version",)]
        self.cursor.fetchone.return_value = (1,)
        self.store = AzureChallengeStore()

    def test_configuration_rejects_connection_string_injection(self):
        expected = connection_string()
        self.assertIn("Authentication=ActiveDirectoryMsi", expected)
        self.assertIn("Encrypt=yes;TrustServerCertificate=no", expected)
        self.assertNotIn("PWD", expected)
        for name, value in (("CHALLENGE_SQL_SERVER", "example.database.windows.net;Encrypt=no"),
                            ("CHALLENGE_SQL_DATABASE", "test;UID=admin"),
                            ("CHALLENGE_SQL_CLIENT_ID", "bad;PWD=secret")):
            with patch.dict(os.environ, {name: value}), self.assertRaises(ValueError):
                connection_string()

    def test_constructor_never_connects_and_backend_selection_is_explicit(self):
        self.driver.connect.assert_not_called()
        self.driver.pooling.assert_called_with(enabled=False)
        with patch.dict(os.environ, {"CHALLENGE_DB_BACKEND": "azure_sql"}):
            self.assertIsInstance(create_store(), AzureChallengeStore)
        with patch.dict(os.environ, {"CHALLENGE_DB_BACKEND": "typo"}), self.assertRaises(ValueError):
            create_store()

    def test_identifier_surrounding_whitespace_is_normalized(self):
        expected = connection_string()
        values = {name: " \t" + value + "\r\n" for name, value in CONFIG.items() if name.startswith("CHALLENGE_SQL_")}
        with patch.dict(os.environ, values), self.assertLogs("challenge_sql", level="WARNING") as logs:
            self.assertEqual(expected, connection_string())
        for value in CONFIG.values():
            self.assertNotIn(value, " ".join(logs.output))

    def test_missing_empty_and_misspelled_settings_fail_without_fallback(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ValueError, "CHALLENGE_SQL_SERVER is missing"):
            connection_string()
        with patch.dict(os.environ, {"CHALLENGE_SQL_DATABASE": " \r\n"}), self.assertRaisesRegex(ValueError, "CHALLENGE_SQL_DATABASE is empty"):
            connection_string()
        config = dict(CONFIG)
        config["CHALLENGE_SQL_DATABASE "] = config.pop("CHALLENGE_SQL_DATABASE")
        with patch.dict(os.environ, config, clear=True), self.assertRaisesRegex(ValueError, "CHALLENGE_SQL_DATABASE is missing"):
            connection_string()

    def test_invalid_values_are_rejected_with_private_shape_diagnostics(self):
        cases = [
            ("CHALLENGE_SQL_DATABASE", "private\nname", "contains_whitespace=True"),
            ("CHALLENGE_SQL_DATABASE", "private\u200bname", "contains_non_ascii=True"),
            ("CHALLENGE_SQL_DATABASE", "x" * 129, "length=129"),
            ("CHALLENGE_SQL_DATABASE", " private;UID=admin \n", "Value withheld"),
            ("CHALLENGE_SQL_CLIENT_ID", "private-invalid-uuid", "client UUID"),
        ]
        for name, value, diagnostic in cases:
            with self.subTest(name=name, value=value), patch.dict(os.environ, {name: value}):
                with self.assertRaises(ValueError) as caught:
                    connection_string()
                self.assertIn(diagnostic, str(caught.exception))
                self.assertNotIn(value.strip(), str(caught.exception))

    def test_commit_close_and_bound_parameters(self):
        payload = "'); DROP TABLE students; --"
        with self.store.connection() as database:
            database.execute("SELECT email FROM students WHERE email = ?", (payload,))
        self.cursor.execute.assert_called_with("SELECT email FROM students WHERE email = ?", (payload,))
        self.connection.commit.assert_called_once()
        self.connection.close.assert_called_once()
        self.connection.rollback.assert_not_called()
        self.assertEqual(15, self.connection.timeout)
        self.assertEqual(60, self.driver.connect.call_args.kwargs["timeout"])
        self.assertFalse(self.driver.connect.call_args.kwargs["autocommit"])

    def test_business_rejection_rolls_back_without_masking_http_error(self):
        with self.assertRaises(HTTPException) as caught:
            with self.store.connection():
                raise HTTPException(409, "Stale revision")
        self.assertEqual(409, caught.exception.status_code)
        self.connection.rollback.assert_called_once()
        self.connection.commit.assert_not_called()
        self.connection.close.assert_called_once()

    def test_connect_and_commit_failures_are_sanitized_and_not_retried(self):
        for stage in ("connect", "commit"):
            with self.subTest(stage=stage):
                self.driver.reset_mock()
                self.driver.connect.side_effect = None
                self.connection.commit.side_effect = None
                target = self.driver.connect if stage == "connect" else self.connection.commit
                target.side_effect = DriverError("sensitive server diagnostic")
                with self.assertRaises(DatabaseUnavailable) as caught:
                    with self.store.connection():
                        pass
                self.assertNotIn("sensitive", str(caught.exception))
                self.driver.connect.assert_called_once()
                if stage == "commit":
                    self.connection.rollback.assert_called_once()
                    self.connection.close.assert_called_once()

    def test_schema_mismatch_rolls_back_and_closes(self):
        self.cursor.fetchone.return_value = (99,)
        with self.assertRaises(DatabaseUnavailable):
            with self.store.connection():
                self.fail("Must not run application queries with an unknown schema")
        self.connection.rollback.assert_called_once()
        self.connection.close.assert_called_once()

    def test_row_mapping_and_missing_row(self):
        database = SQLConnection(self.connection)
        self.cursor.description = [("id",), ("email",)]
        self.cursor.fetchone.return_value = ("attempt", "tester@ucsd.edu")
        self.assertEqual({"id": "attempt", "email": "tester@ucsd.edu"}, database.fetchone())
        self.cursor.fetchone.return_value = None
        self.assertIsNone(database.fetchone())

    def test_runtime_identity_cannot_manage_roster(self):
        with self.assertRaises(ValueError):
            self.store.set_student("tester@ucsd.edu")
        self.driver.connect.assert_not_called()

    def test_access_locks_attempt_range_without_roster_write_permissions(self):
        # Shape the driver rows for schema, roster and existing-attempt lookup.
        descriptions = [[("version",)], [("email",)], [("id",)]]
        rows = [(1,), ("tester@ucsd.edu",), ("existing-attempt",)]
        def fetchone():
            self.cursor.description = descriptions.pop(0)
            return rows.pop(0)
        self.cursor.fetchone.side_effect = fetchone
        self.store.access("tester@ucsd.edu")
        statements = [call.args[0] for call in self.cursor.execute.call_args_list]
        self.assertIn("SELECT email FROM students WHERE email = ? AND enabled = 1", statements)
        attempt_query = next(sql for sql in statements if sql.startswith("SELECT TOP"))
        self.assertIn("WITH (UPDLOCK, HOLDLOCK)", attempt_query)
        self.assertNotIn("LIMIT", attempt_query)
        self.assertFalse(any(sql.startswith("INSERT INTO attempts") for sql in statements))


class RealDriverParserTests(unittest.TestCase):
    def test_generated_string_passes_strict_driver_validation(self):
        # Run with the pinned Linux driver in the container; no network needed.
        from mssql_python.connection_string_parser import _ConnectionStringParser
        from mssql_python.exceptions import ConnectionStringParseError
        parser = _ConnectionStringParser(validate_keywords=True)
        with patch.dict(os.environ, CONFIG):
            value = connection_string()
        parser._parse(value)
        # Prove that this real parser catches the previously deployed bug.
        with self.assertRaises(ConnectionStringParseError):
            parser._parse(value + "Connection Timeout=15;")


if __name__ == "__main__":
    unittest.main()
