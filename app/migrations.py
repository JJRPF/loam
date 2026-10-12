"""Applies `db/migrations/*.sql` in name order, once each, recording them in `schema_migrations`.

`db/init_schema.sql` creates a fresh database; every later schema change is a numbered,
idempotent migration file. Run `python -m scripts.migrate` (after a pg_dump on prod).
"""
import os
from typing import List

from app.db import get_connection

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db", "migrations")


def pending_migrations(applied: set) -> List[str]:
    names = sorted(f for f in os.listdir(MIGRATIONS_DIR) if f.endswith(".sql"))
    return [n for n in names if n not in applied]


def apply_migrations(dry_run: bool = False) -> List[str]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ DEFAULT NOW())"
            )
            cur.execute("SELECT name FROM schema_migrations")
            todo = pending_migrations({r[0] for r in cur.fetchall()})
            if dry_run:
                conn.rollback()
                return todo
            for name in todo:
                with open(os.path.join(MIGRATIONS_DIR, name)) as f:
                    cur.execute(f.read())
                cur.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (name,))
        conn.commit()
    return todo
