"""Create the configured project database and apply pending SQL migrations."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import get_settings
from database.migrate import apply_migrations, create_database


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-create", action="store_true", help="apply migrations without creating the database")
    args = parser.parse_args()
    settings = get_settings()
    if not args.no_create:
        create_database(settings)
        print(f"Database ready: {settings.db_database} on {settings.db_server}")
    pending = apply_migrations(settings)
    print("Applied: " + (", ".join(pending) if pending else "no pending migrations"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

