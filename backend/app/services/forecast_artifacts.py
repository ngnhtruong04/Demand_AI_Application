"""Immutable run inputs/models and on-demand item SHAP cache on local disk."""
from pathlib import Path
import shutil
from uuid import UUID

from app.core.config import BACKEND_ROOT

ARTIFACT_ROOT = BACKEND_ROOT / "data" / "forecast_artifacts"
MODEL_FILES = ("lightgbm.joblib", "xgboost.joblib", "catboost.joblib", "feature_contract.json", "selected_weights.json", "feature_dictionary.json")


def run_directory(run_id: str) -> Path:
    return ARTIFACT_ROOT / str(UUID(str(run_id)))


def snapshot_models(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for name in MODEL_FILES:
        shutil.copy2(source / name, destination / name)


def prune_artifacts(retained_ids: set[str]) -> None:
    if not ARTIFACT_ROOT.exists():
        return
    for entry in ARTIFACT_ROOT.iterdir():
        try:
            run_id = str(UUID(entry.name))
        except ValueError:
            continue
        if entry.is_dir() and not entry.is_symlink() and run_id not in retained_ids:
            shutil.rmtree(entry)


def prune_old_sessions(keep_n: int = 4) -> list[str]:
    """Automatically remove expired session folders in ARTIFACT_ROOT, keeping only the last n (default 2) sessions."""
    if not ARTIFACT_ROOT.exists():
        return []
    session_dirs = []
    for entry in ARTIFACT_ROOT.iterdir():
        try:
            UUID(entry.name)
            if entry.is_dir() and not entry.is_symlink():
                session_dirs.append(entry)
        except ValueError:
            continue
    session_dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
    removed = []
    for old_dir in session_dirs[keep_n:]:
        try:
            shutil.rmtree(old_dir, ignore_errors=True)
            removed.append(old_dir.name)
        except OSError:
            pass
    return removed


EXPORTS_DIR = BACKEND_ROOT / "data" / "exports"


def prune_old_exports(keep_n: int = 5) -> list[str]:
    """Automatically remove oldest export files in EXPORTS_DIR, keeping only the last n (default 4) files (FIFO)."""
    if not EXPORTS_DIR.exists():
        return []
    files = [f for f in EXPORTS_DIR.iterdir() if f.is_file() and not f.is_symlink()]
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    removed = []
    for old_file in files[keep_n:]:
        try:
            old_file.unlink(missing_ok=True)
            removed.append(old_file.name)
        except OSError:
            pass
    return removed

