#!/usr/bin/env python3
"""Remove the fabricated rows earlier rounds wrote to the database (docs/round7-plan.md section 4).

Run `pg_dump -Fc` first on the Pi. Deletes exactly:
  - the fake "Bow Town Forest kickstart" activity and its activity_edge_visits,
then recalculates heat, which zeroes every edge_heat row no real visit supports (including
the invented Bow heat). Curated `edges` rows with hand-made geometry are reported here and
overwritten by the OSM import (scripts/import_osm_graph.py).

It also reports, without deleting, activities written by the old mock Garmin connector
(ids garmin_act_<uid>_<n>); deleting those needs the user's OK.

    python -m scripts.cleanup_fabricated [--dry-run]
"""
import argparse

from app.db import get_connection, recalculate_all_edge_heat

FAKE_ACTIVITY_IDS = ["bow-town-forest-kickstart-001"]
# osm ids the old Bow ingest wrote with hand-made geometry and lengths
CURATED_EDGE_IDS = [289829667, 289829681, 289829857, 302693899, 339654248, 18854090, 313179483,
                    304316555, 304316556, 304316557, 304316558, 304316559, 304316560]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM activities WHERE id = ANY(%s)", (FAKE_ACTIVITY_IDS,))
            n_act = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM activity_edge_visits WHERE activity_id = ANY(%s)", (FAKE_ACTIVITY_IDS,))
            n_vis = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM edge_heat WHERE weighted_score > 0")
            heat_before = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM edges WHERE osm_id = ANY(%s)", (CURATED_EDGE_IDS,))
            n_curated = cur.fetchone()[0]
            cur.execute(r"SELECT count(*) FROM activities WHERE id ~ '^garmin_act_.+_[1-6]$' AND id !~ '^garmin_act_[0-9]+$'")
            n_mock_garmin = cur.fetchone()[0]
            print(f"fake activities: {n_act}, their edge visits: {n_vis}")
            print(f"edge_heat rows with heat before: {heat_before}")
            print(f"curated Bow edges with hand-made geometry (overwritten by the OSM import): {n_curated}")
            print(f"activities from the old mock Garmin connector (reported only): {n_mock_garmin}")
            if args.dry_run:
                conn.rollback()
                return
            cur.execute("DELETE FROM activities WHERE id = ANY(%s)", (FAKE_ACTIVITY_IDS,))
            print(f"deleted {cur.rowcount} activities (visits cascade)")
        conn.commit()
    stats = recalculate_all_edge_heat()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM edge_heat WHERE weighted_score > 0")
            print(f"heat recalculated: {stats}; edge_heat rows with heat after: {cur.fetchone()[0]}")


if __name__ == "__main__":
    main()
