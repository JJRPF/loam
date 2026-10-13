"""Re-keys legacy user rows to a Firebase uid (plan 3.3).

Before Round 7, users were keyed by a raw Google `sub` or by uids the client made up
(`google_<email>`, `token_*`, `justin_default_user`). Firebase uids differ, so on the first
verified login the rows of any legacy user with the same verified email move to the new uid.
`scripts/migrate_user_ids.py` runs the same code by hand, with `--dry-run`.
"""
import logging
from typing import Dict, Iterable, List, Optional

from psycopg2 import errors as pg_errors

from app.db import get_connection

logger = logging.getLogger("loam.account_migration")

# Users created by the pre-Round-7 fake sign-in flows (plan 3.4).
FAKE_USER_SQL = (
    "(id LIKE 'google\\_%%' OR id LIKE 'token\\_%%' OR id = 'justin_default_user' "
    "OR coalesce(email, '') ILIKE '%%@example.com')"
)


def user_id_tables(cur) -> List[str]:
    """Every base table (except users) with a `user_id` column."""
    cur.execute(
        """
        SELECT c.table_name
        FROM information_schema.columns c
        JOIN information_schema.tables t
          ON t.table_schema = c.table_schema AND t.table_name = c.table_name
        WHERE c.table_schema = 'public' AND c.column_name = 'user_id'
          AND t.table_type = 'BASE TABLE' AND c.table_name <> 'users'
        ORDER BY c.table_name
        """
    )
    return [r[0] for r in cur.fetchall()]


def count_rows(cur, user_ids: Iterable[str]) -> Dict[str, int]:
    ids = list(user_ids)
    counts: Dict[str, int] = {}
    for table in user_id_tables(cur):
        cur.execute(f'SELECT count(*) FROM "{table}" WHERE user_id = ANY(%s)', (ids,))
        counts[table] = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM edge_heat WHERE contributor_ids && %s::text[]", (ids,))
    counts["edge_heat.contributor_ids"] = cur.fetchone()[0]
    return counts


def legacy_ids_for_email(cur, email: str, new_uid: str) -> List[str]:
    """Users with this email that never signed in through Firebase."""
    cur.execute(
        """
        SELECT id FROM users
        WHERE lower(email) = lower(%s) AND id <> %s AND auth_provider IS NULL
        ORDER BY created_at
        """,
        (email.strip(), new_uid),
    )
    return [r[0] for r in cur.fetchall()]


def rekey_users(cur, old_ids: List[str], new_uid: str, email: Optional[str], dry_run: bool) -> Dict[str, int]:
    """Moves every row of `old_ids` to `new_uid` and deletes the old users rows.

    A row that would collide with a unique constraint already held by `new_uid`
    (consent, a vote on the same flag, the same connector) is a duplicate and is dropped.
    Runs inside the caller's transaction.
    """
    counts = count_rows(cur, old_ids)
    counts["users_removed"] = len(old_ids)
    if dry_run or not old_ids:
        return counts

    cur.execute(
        """
        INSERT INTO users (id, email, display_name, auth_provider)
        SELECT %s, %s, display_name, 'firebase' FROM users WHERE id = ANY(%s)
        ORDER BY created_at LIMIT 1
        ON CONFLICT (id) DO NOTHING
        """,
        (new_uid, email, old_ids),
    )
    cur.execute(
        "INSERT INTO users (id, email, auth_provider) VALUES (%s, %s, 'firebase') ON CONFLICT (id) DO NOTHING",
        (new_uid, email),
    )

    dropped = 0
    for table in user_id_tables(cur):
        cur.execute("SAVEPOINT rekey_table")
        try:
            cur.execute(f'UPDATE "{table}" SET user_id = %s WHERE user_id = ANY(%s)', (new_uid, old_ids))
            cur.execute("RELEASE SAVEPOINT rekey_table")
        except pg_errors.UniqueViolation:
            cur.execute("ROLLBACK TO SAVEPOINT rekey_table")
            cur.execute(f'SELECT ctid FROM "{table}" WHERE user_id = ANY(%s)', (old_ids,))
            for (ctid,) in cur.fetchall():
                cur.execute("SAVEPOINT rekey_row")
                try:
                    cur.execute(f'UPDATE "{table}" SET user_id = %s WHERE ctid = %s', (new_uid, ctid))
                    cur.execute("RELEASE SAVEPOINT rekey_row")
                except pg_errors.UniqueViolation:
                    cur.execute("ROLLBACK TO SAVEPOINT rekey_row")
                    cur.execute(f'DELETE FROM "{table}" WHERE ctid = %s', (ctid,))
                    dropped += 1

    cur.execute(
        """
        UPDATE edge_heat
        SET contributor_ids = ARRAY(
            SELECT DISTINCT CASE WHEN x = ANY(%s) THEN %s ELSE x END
            FROM unnest(contributor_ids) AS x
        )
        WHERE contributor_ids && %s::text[]
        """,
        (old_ids, new_uid, old_ids),
    )
    cur.execute("DELETE FROM users WHERE id = ANY(%s)", (old_ids,))
    counts["duplicates_dropped"] = dropped
    return counts


def mark_firebase_user(uid: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET auth_provider = 'firebase' WHERE id = %s", (uid,))
        conn.commit()


def claim_legacy_accounts(new_uid: str, email: str) -> Dict[str, int]:
    """Called on a verified login: marks the user as a Firebase user and re-keys any legacy
    account with the same verified email, in one transaction."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET auth_provider = 'firebase' WHERE id = %s", (new_uid,))
            old_ids = legacy_ids_for_email(cur, email, new_uid)
            if not old_ids:
                conn.commit()
                return {}
            counts = rekey_users(cur, old_ids, new_uid, email, dry_run=False)
        conn.commit()
    logger.warning(
        "Re-keyed %d legacy user(s) to Firebase uid %s: %s", len(old_ids), new_uid,
        {k: v for k, v in counts.items() if v},
    )
    return counts


def fake_users_report(cur) -> List[Dict[str, object]]:
    """Fake-flow users (plan 3.4) with their total row count across user tables."""
    cur.execute(f"SELECT id FROM users WHERE {FAKE_USER_SQL} ORDER BY id")
    report = []
    for (uid,) in cur.fetchall():
        counts = count_rows(cur, [uid])
        report.append({"id": uid, "rows": sum(counts.values()), "counts": counts})
    return report


def purge_empty_fake_users(cur, dry_run: bool) -> List[str]:
    """Deletes fake-flow users that own no rows (re-keyed already, or never used)."""
    empty = [r["id"] for r in fake_users_report(cur) if r["rows"] == 0]
    if empty and not dry_run:
        cur.execute("DELETE FROM users WHERE id = ANY(%s) AND auth_provider IS NULL", (empty,))
    return empty

