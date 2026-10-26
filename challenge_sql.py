"""Azure SQL persistence. Schema administration is deliberately a separate step."""
from contextlib import contextmanager
import os
import re
from uuid import UUID

from challenge_store import ChallengeStore, DatabaseUnavailable, configured_version


def connection_string():
    server = os.environ.get("CHALLENGE_SQL_SERVER", "")
    database = os.environ.get("CHALLENGE_SQL_DATABASE", "")
    client_id = os.environ.get("CHALLENGE_SQL_CLIENT_ID", "")
    if not re.fullmatch(r"[a-z0-9-]+\.database\.windows\.net", server):
        raise ValueError("CHALLENGE_SQL_SERVER must be an Azure SQL hostname")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", database):
        raise ValueError("CHALLENGE_SQL_DATABASE must be a database name")
    client_id = str(UUID(client_id))
    return (f"Server=tcp:{server},1433;Database={database};"
            f"Authentication=ActiveDirectoryMsi;UID={client_id};"
            "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=15;")


class SQLConnection:
    """Small DB-API adapter; values stay bound parameters, never SQL text."""
    def __init__(self, connection):
        self.cursor = connection.cursor()

    def execute(self, statement, parameters=()):
        self.cursor.execute(statement, parameters)
        return self

    def fetchone(self):
        row = self.cursor.fetchone()
        if row is None:
            return None
        return dict(zip((column[0] for column in self.cursor.description), row))


class AzureChallengeStore(ChallengeStore):
    azure_sql = True

    def __init__(self):
        # Do not contact Azure or create tables at application import/startup.
        self.test_version = configured_version()
        self.connection_string = connection_string()
        import mssql_python
        self.driver = mssql_python
        # Close idle connections immediately so an unused serverless DB can pause.
        self.driver.pooling(enabled=False)

    @contextmanager
    def connection(self):
        connection = None
        try:
            connection = self.driver.connect(self.connection_string, autocommit=False, timeout=15)
            connection.timeout = 15
            database = SQLConnection(connection)
            database.execute("SET XACT_ABORT ON; SET LOCK_TIMEOUT 10000;")
            version = database.execute("SELECT version FROM dbo.challenge_schema WHERE singleton = 1").fetchone()
            if version is None or version["version"] != 1:
                raise DatabaseUnavailable("Unsupported challenge schema")
            yield database
            connection.commit()
        except BaseException as error:
            if connection is not None:
                try:
                    connection.rollback()
                except self.driver.Error:
                    pass
            if isinstance(error, self.driver.Error):
                raise DatabaseUnavailable("Azure SQL operation failed") from None
            raise
        finally:
            if connection is not None:
                try:
                    connection.close()
                except self.driver.Error:
                    pass

    def set_student(self, email, enabled=True):
        raise ValueError("Manage the Azure roster through the administrator SQL script, not the application identity.")


if __name__ == "__main__":
    # Explicit, read-only diagnostic. Never invoked by the HTTP health check.
    try:
        with AzureChallengeStore().connection() as database:
            identity = database.execute("SELECT DB_NAME() AS database_name, USER_NAME() AS database_user").fetchone()
        print(f"Connected to {identity['database_name']} as {identity['database_user']}; schema version 1.")
    except (DatabaseUnavailable, ValueError, ImportError):
        raise SystemExit("Database check failed. Check configuration, identity, firewall, schema and grants.") from None
