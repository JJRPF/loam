#!/usr/bin/env python3
"""Re-key legacy Loam users to a Firebase uid (docs/round7-plan.md 3.3, 3.4).

Legacy users were keyed by a raw Google `sub` or by uids the old client made up. On the
first verified Firebase login the API re-keys any legacy user with the same verified email
automatically; this script does the same by hand, with a dry run that prints row counts.
Run `pg_dump -Fc` first on the Pi.

  # every user, masked emails, rows per table (read-only)
  python -m scripts.migrate_user_ids --list

  # what re-keying a verified email would move (read-only)
  python -m scripts.migrate_user_ids --email you@example.org --dry-run

  # re-key: legacy users with that email (plus any --from uid) -> the Firebase uid
  python -m scripts.migrate_user_ids --email you@example.org --to-uid <firebase uid> [--from justin_default_user]

  # plan 3.4: fake-flow users (google_*, token_*, *@example.com, justin_default_user) that own no rows
  python -m scripts.migrate_user_ids --purge-fake [--dry-run]
"""
import argparse
import sys

from app.account_migration import (
    count_rows, fake_users_report, legacy_ids_for_email, purge_empty_fake_users, rekey_users,
)
from app.db import get_connection


def mask_email(email):
    if not email or "@" not in email:
        return email or "-"
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


def print_counts(counts):
    width = max((len(k) for k in counts), default=10)
    for table, n in sorted(counts.items()):
        print(f"  {table:<{width}}  {n}")


def cmd_list(cur):
    cur.execute("SELECT id, email, auth_provider, created_at FROM users ORDER BY created_at")
    rows = cur.fetchall()
    print(f"{len(rows)} users")
    for uid, email, provider, created in rows:
        counts = count_rows(cur, [uid])
        total = sum(counts.values())
        nonzero = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()) if v)
        print(f"- {uid}  {mask_email(email)}  provider={provider or 'legacy'}  created={created:%Y-%m-%d}  rows={total}  {nonzero}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="list users and their row counts")
    ap.add_argument("--email", help="verified email whose legacy users are re-keyed")
    ap.add_argument("--to-uid", help="the Firebase uid to re-key to")
    ap.add_argument("--from", dest="extra", action="append", default=[], help="an extra legacy uid to include")
    ap.add_argument("--purge-fake", action="store_true", help="delete fake-flow users that own no rows")
    ap.add_argument("--dry-run", action="store_true", help="print counts, change nothing")
    args = ap.parse_args()

    with get_connection() as conn:
        with conn.cursor() as cur:
            if args.list:
                cmd_list(cur)
                return
            if args.purge_fake:
                report = fake_users_report(cur)
                print(f"{len(report)} fake-flow users")
                for r in report:
                    print(f"- {r['id']}  rows={r['rows']}")
                purged = purge_empty_fake_users(cur, dry_run=args.dry_run)
                verb = "Would delete" if args.dry_run else "Deleted"
                print(f"{verb} {len(purged)} users with no rows: {', '.join(purged) or 'none'}")
                kept = [r["id"] for r in report if r["rows"]]
                if kept:
                    print(f"Kept (still own rows; re-key them first): {', '.join(kept)}")
                if not args.dry_run:
                    conn.commit()
                return
            if not args.email:
                ap.error("--email is required (or use --list / --purge-fake)")
            new_uid = args.to_uid or "<firebase uid>"
            old_ids = legacy_ids_for_email(cur, args.email, new_uid) + [u for u in args.extra if u != new_uid]
            old_ids = list(dict.fromkeys(old_ids))
            print(f"Legacy users for {mask_email(args.email)}: {', '.join(old_ids) or 'none'}")
            if not args.dry_run and not args.to_uid:
                ap.error("--to-uid is required unless --dry-run")
            counts = rekey_users(cur, old_ids, new_uid, args.email, dry_run=args.dry_run)
            print("Dry run, rows that would move:" if args.dry_run else f"Re-keyed to {new_uid}:")
            print_counts(counts)
            if args.dry_run:
                conn.rollback()
            else:
                conn.commit()


if __name__ == "__main__":
    sys.exit(main())
