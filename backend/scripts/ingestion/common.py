import hashlib
import json
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql

from app.core.config import settings

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
FORBIDDEN_NAMES = {"sales_test", "sales_test.csv", "raw.sales_test"}
DEFAULT_MANIFEST_PATH = BACKEND_ROOT / "config" / "raw_datasets.json"


class ManifestValidationError(ValueError):
    """Raised when manifest validation fails or illegal dataset is requested."""
    pass


def load_manifest(manifest_path: str | Path = DEFAULT_MANIFEST_PATH) -> list[dict[str, Any]]:
    """
    Load dataset manifest and enforce strict allowlist.
    Rejects any forbidden files/tables like sales_test.
    """
    path = Path(manifest_path)
    if not path.is_file():
        if not path.is_absolute() and (BACKEND_ROOT / path).is_file():
            path = BACKEND_ROOT / path
        else:
            raise FileNotFoundError(f"Manifest file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    datasets = data.get("datasets", [])
    if not datasets:
        raise ManifestValidationError("Manifest does not contain any datasets")

    allowed_names = {"calendar", "inventory", "test_weights", "sales_train"}
    seen_names = set()

    for item in datasets:
        name = item.get("name")
        file_name = item.get("file")
        schema = item.get("schema")
        table = item.get("table")

        if not all([name, file_name, schema, table]):
            raise ManifestValidationError(f"Invalid dataset entry: {item}")

        if name in FORBIDDEN_NAMES or file_name in FORBIDDEN_NAMES or f"{schema}.{table}" in FORBIDDEN_NAMES:
            raise ManifestValidationError(f"Forbidden dataset requested: {item}")

        if name not in allowed_names:
            raise ManifestValidationError(f"Dataset name '{name}' not in allowed datasets: {allowed_names}")

        if schema != "raw":
            raise ManifestValidationError(f"Only 'raw' schema is permitted, got: '{schema}'")

        if table not in allowed_names:
            raise ManifestValidationError(f"Table name '{table}' not in allowed tables: {allowed_names}")

        if name in seen_names:
            raise ManifestValidationError(f"Duplicate dataset name in manifest: {name}")

        seen_names.add(name)

    return datasets


def get_dataset_by_name(name: str, manifest_path: str | Path = DEFAULT_MANIFEST_PATH) -> dict[str, Any]:
    """Resolve a single dataset by name from the manifest allowlist."""
    if name in FORBIDDEN_NAMES:
        raise ManifestValidationError(f"Forbidden dataset requested: {name}")

    manifest = load_manifest(manifest_path)
    for ds in manifest:
        if ds["name"] == name:
            return ds
    raise ManifestValidationError(f"Unknown dataset '{name}'. Available: {[d['name'] for d in manifest]}")


def compute_file_sha256(file_path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    """Compute SHA-256 checksum using streaming chunks to avoid loading whole files into memory."""
    sha256 = hashlib.sha256()
    path = Path(file_path)
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            sha256.update(chunk)
    return sha256.hexdigest()


def count_csv_data_rows(file_path: str | Path, buffer_size: int = 1024 * 1024) -> int:
    """
    Count data rows (excluding header) efficiently using chunked binary reading.
    Assumes standard newline termination.
    """
    path = Path(file_path)
    total_newlines = 0
    with path.open("rb") as f:
        while chunk := f.read(buffer_size):
            total_newlines += chunk.count(b"\n")

    # If the file does not end with a newline, check if there are bytes after the last newline
    with path.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        if size > 0:
            f.seek(max(0, size - 1))
            last_byte = f.read(1)
            if last_byte != b"\n":
                total_newlines += 1

    # Subtract 1 for the header row
    return max(0, total_newlines - 1)


def get_master_connection() -> psycopg.Connection:
    """
    Establish a psycopg 3 connection using master credentials.
    Enforces TLS verify-full with custom CA bundle.
    """
    return psycopg.connect(
        host=settings.rds_endpoint,
        port=settings.rds_port,
        dbname=settings.rds_database,
        user=settings.rds_master_username,
        password=settings.rds_master_password.get_secret_value(),
        sslmode=settings.rds_ssl_mode,
        sslrootcert=settings.rds_ssl_root_cert,
        connect_timeout=10,
        application_name="rohlik-ingestion-master",
        autocommit=False,
    )


def get_api_connection() -> psycopg.Connection:
    """
    Establish a psycopg 3 connection using API credentials.
    Enforces TLS verify-full with custom CA bundle.
    """
    return psycopg.connect(
        host=settings.rds_endpoint,
        port=settings.rds_port,
        dbname=settings.rds_database,
        user=settings.rds_api_username,
        password=settings.rds_api_password.get_secret_value(),
        sslmode=settings.rds_ssl_mode,
        sslrootcert=settings.rds_ssl_root_cert,
        connect_timeout=10,
        application_name="rohlik-ingestion-api",
        autocommit=False,
    )
