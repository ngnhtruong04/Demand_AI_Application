"""load_forecast_to_db.py — CLI script to load forecast & TreeSHAP data into RDS core schema with 10-run retention.

Usage:
    python -m scripts.load_forecast_to_db [--verify-only] [--prune-only] [--max-runs 10] [--model-version MODEL_VERSION]
"""
from __future__ import annotations

import argparse
import json
import time
from sqlalchemy import text

from app.db.session import SessionLocal
from app.services.forecast_persistence import (
    get_forecast_runs_from_db,
    get_latest_forecast_from_db,
    prune_old_forecast_runs,
    save_forecast_run,
)


def verify_forecast_data() -> dict:
    """Verify data consistency, run count and TreeSHAP retention in RDS."""
    db = SessionLocal()
    try:
        run = get_latest_forecast_from_db(db, unique_id="all", limit=5, offset=0, top_k=5)
        if not run:
            print("[FAIL] No active forecast run found in RDS.")
            return {"status": "fail", "message": "No active forecast run found."}

        total_runs_count = db.execute(text("SELECT COUNT(*) FROM core.forecast_runs")).scalar() or 0
        print(f"[PASS] Found latest active forecast run: {run.get('run_id')}")
        print(f"       Total forecast runs currently stored in RDS: {total_runs_count} (Retention policy: max 10)")
        print(f"       Total items in active run: {run.get('total_items')}")

        # Check item summary count
        run_id = run.get('run_id')
        item_count = db.execute(
            text("SELECT COUNT(*) FROM core.forecast_item_summary WHERE run_id = :run_id"),
            {"run_id": run_id}
        ).scalar()

        # Check daily points count
        pts_count = db.execute(
            text("SELECT COUNT(*) FROM core.forecast_daily_points WHERE run_id = :run_id"),
            {"run_id": run_id}
        ).scalar()

        # Check raw all_features_shap count in item summary
        shap_count = db.execute(
            text("""
                SELECT jsonb_array_length(all_features_shap) 
                FROM core.forecast_item_summary 
                WHERE run_id = :run_id AND jsonb_array_length(all_features_shap) > 0
                LIMIT 1
            """),
            {"run_id": run_id}
        ).scalar()

        print(f"       Verified {item_count} items in core.forecast_item_summary")
        print(f"       Verified {pts_count} daily points in core.forecast_daily_points")
        print(f"       Sample item all_features_shap contains {shap_count} features stored losslessly in JSONB")

        # Test single item query with Top-5 + Other
        single = get_latest_forecast_from_db(db, unique_id="10", top_k=5)
        if single and single.get("items"):
            item10 = single["items"][0]
            top_features = item10.get("all_features_shap", [])
            print(f"       Top-5 + Other features for Item 10: {len(top_features)} rows returned")
            for idx, feat in enumerate(top_features):
                print(f"         {idx+1}. {feat.get('label')}: shap={feat.get('shap')} (group={feat.get('group')})")

        return {
            "status": "success",
            "run_id": run_id,
            "total_runs_in_db": total_runs_count,
            "total_items": item_count,
            "total_daily_points": pts_count,
            "sample_shap_feature_count": shap_count,
        }
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed and verify forecast results on PostgreSQL RDS")
    parser.add_argument("--verify-only", action="store_true", help="Only verify existing forecast data")
    parser.add_argument("--prune-only", action="store_true", help="Only prune runs beyond max-runs retention")
    parser.add_argument("--max-runs", type=int, default=10, help="Maximum number of historical runs to retain (default: 10)")
    parser.add_argument("--model-version", default="recursive-ensemble-v1.0", help="Model version string")
    args = parser.parse_args()

    if args.prune_only:
        db = SessionLocal()
        try:
            pruned = prune_old_forecast_runs(db, max_runs_to_keep=args.max_runs)
            db.commit()
            print(f"Pruned {pruned} runs. Current runs retained: <= {args.max_runs}")
        finally:
            db.close()
        res = verify_forecast_data()
        print(json.dumps(res, indent=2))
        return

    if args.verify_only:
        res = verify_forecast_data()
        print(json.dumps(res, indent=2))
        return

    started = time.monotonic()
    print(f"Loading forecast and TreeSHAP results into RDS (model_version={args.model_version}, max_runs={args.max_runs})...")
    db = SessionLocal()
    try:
        run = save_forecast_run(db, model_version=args.model_version, is_latest=True, max_runs_to_keep=args.max_runs)
        elapsed = time.monotonic() - started
        print(f"Successfully committed forecast run {run.run_id} in {elapsed:.2f}s (retained up to {args.max_runs} runs)")
    finally:
        db.close()

    print("\n--- Verification ---")
    res = verify_forecast_data()
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
