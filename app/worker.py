import sys
import time
import logging
import argparse
import datetime
from typing import Optional, Dict, Any
from app.db import recalculate_all_edge_heat, check_db_health

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("loam.nightly_worker")

def run_nightly_job(ref_date: Optional[datetime.datetime] = None) -> Dict[str, Any]:
    """
    Executes the nightly Loam Heat v1 job:
    1. Recalculates edge_heat for all traversed edges using exponential decay (6-month half-life).
    2. Enforces the >= 3 unique riders privacy threshold for public heat.
    3. Zeros out stale edges outside the 12-month window.
    4. Refreshes the regional coverage grid (coverage-aware zero-heat penalty).
    """
    logger.info("Starting nightly heat recalculation job...")
    if not check_db_health():
        logger.error("Database health check failed; aborting worker job.")
        return {"status": "error", "error": "Database unavailable"}

    t0 = time.time()
    stats = recalculate_all_edge_heat(ref_date=ref_date)
    duration = time.time() - t0

    logger.info(
        f"Nightly heat recalculation complete in {duration:.2f}s: "
        f"{stats.get('edges_updated', 0)} edges updated "
        f"({stats.get('public_edges_count', 0)} public, {stats.get('private_edges_count', 0)} private), "
        f"{stats.get('coverage_cells_updated', 0)} regional coverage cells refreshed."
    )

    try:
        from app.reports import retry_pending
        stats["reports"] = retry_pending()
    except Exception as e:  # reports must never fail the heat job
        logger.warning(f"Retrying pending bad-route reports failed: {type(e).__name__}")

    stats["status"] = "success"
    return stats

def main():
    parser = argparse.ArgumentParser(description="Loam Nightly Heat Recalculation Worker")
    parser.add_argument("--date", help="Reference date (YYYY-MM-DD) for simulation or testing", default=None)
    args = parser.parse_args()

    ref_date = None
    if args.date:
        ref_date = datetime.datetime.fromisoformat(args.date).replace(tzinfo=datetime.timezone.utc)

    result = run_nightly_job(ref_date=ref_date)
    logger.info(f"Worker result: {result}")
    sys.exit(0 if result.get("status") == "success" else 1)

if __name__ == "__main__":
    main()
