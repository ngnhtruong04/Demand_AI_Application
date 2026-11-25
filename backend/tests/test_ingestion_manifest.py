import json
import pytest

from scripts.ingestion.common import (
    ManifestValidationError,
    get_dataset_by_name,
    load_manifest,
)


def test_manifest_contains_exact_four_datasets() -> None:
    datasets = load_manifest()
    dataset_names = [d["name"] for d in datasets]
    assert dataset_names == ["calendar", "inventory", "test_weights", "sales_train"]

    for d in datasets:
        assert d["schema"] == "raw"
        assert d["table"] in {"calendar", "inventory", "test_weights", "sales_train"}
        assert d["file"].endswith(".csv")


def test_manifest_rejects_sales_test_explicitly(tmp_path) -> None:
    # Attempting to query sales_test by name should raise ManifestValidationError
    with pytest.raises(ManifestValidationError):
        get_dataset_by_name("sales_test")

    # Creating a manifest with sales_test must be rejected by load_manifest
    bad_manifest = tmp_path / "bad_manifest.json"
    bad_manifest.write_text(
        json.dumps({
            "datasets": [
                {
                    "name": "sales_test",
                    "file": "sales_test.csv",
                    "schema": "raw",
                    "table": "sales_test"
                }
            ]
        })
    )
    with pytest.raises(ManifestValidationError):
        load_manifest(bad_manifest)


def test_manifest_rejects_unauthorized_tables_or_schemas(tmp_path) -> None:
    bad_manifest = tmp_path / "bad_manifest.json"
    bad_manifest.write_text(
        json.dumps({
            "datasets": [
                {
                    "name": "users",
                    "file": "users.csv",
                    "schema": "public",
                    "table": "users"
                }
            ]
        })
    )
    with pytest.raises(ManifestValidationError):
        load_manifest(bad_manifest)
