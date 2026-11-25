import json
import pytest
from scripts.core.service import SPECS, load_config, source_query


def test_core_source_config_rejects_untrusted_identifier(tmp_path):
    path = tmp_path / "sources.json"
    path.write_text(json.dumps({"raw_schema": "raw; DROP SCHEMA raw", "core_schema": "core", "tables": {name: name for name in SPECS}}))
    with pytest.raises(ValueError, match="Unsafe SQL identifier"):
        load_config(path)


def test_inventory_mapping_preserves_ids_and_aliases_categories():
    config = {"raw_schema": "raw", "core_schema": "core", "tables": {name: ("sales_train" if name == "sales_daily" else "test_weights" if name == "series_weights" else name) for name in SPECS}}
    query = source_query(config, SPECS["inventory"]).as_string()
    assert 'product_unique_id::bigint AS "product_unique_id"' in query
    assert '"L1_category_name_en" AS "l1_category_name_en"' in query
    assert "btrim" not in query.lower()


def test_sales_storage_includes_availability_and_immutable_warehouse():
    spec = SPECS["sales_daily"]
    assert "availability" in spec.columns
    assert spec.keys == ("unique_id", "date")
    assert spec.immutable == ("warehouse",)
