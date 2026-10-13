#!/usr/bin/env python3
"""Apply pending database migrations (db/migrations/*.sql) to DATABASE_URL.

On the Pi, run `pg_dump -Fc` first (docs/round7-plan.md 3.4).

    python -m scripts.migrate [--dry-run]
"""
import argparse

from app.migrations import apply_migrations


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="list pending migrations without applying them")
    args = ap.parse_args()
    names = apply_migrations(dry_run=args.dry_run)
    verb = "Pending" if args.dry_run else "Applied"
    print(f"{verb}: {', '.join(names) if names else 'none'}")


if __name__ == "__main__":
    main()
