import argparse
import os
from pathlib import Path

from challenge_store import create_store, DatabaseUnavailable


def main():
    parser = argparse.ArgumentParser(description="Maintain the private Challenge Mode student allowlist.")
    parser.add_argument("email")
    parser.add_argument("--disable", action="store_true")
    parser.add_argument("--database", help="Explicit local SQLite path; otherwise use the configured backend")
    arguments = parser.parse_args()
    try:
        email = create_store(arguments.database).set_student(arguments.email, not arguments.disable)
    except ValueError as error:
        parser.error(str(error))
    except DatabaseUnavailable:
        parser.exit(1, "Database unavailable. Check connectivity, schema, and roster permissions.\n")
    print(f"{'Disabled' if arguments.disable else 'Authorized'}: {email}")


if __name__ == "__main__":
    main()
