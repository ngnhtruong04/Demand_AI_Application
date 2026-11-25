import hashlib
import tempfile
from pathlib import Path
from psycopg import sql

from scripts.ingestion.common import (
    compute_file_sha256,
    count_csv_data_rows,
    load_manifest,
)


def test_compute_file_sha256() -> None:
    content = b"header1,header2\nval1,val2\nval3,val4\n"
    expected_hash = hashlib.sha256(content).hexdigest()

    with tempfile.NamedTemporaryFile(delete=False) as tf:
        tf.write(content)
        temp_path = tf.name

    try:
        calc_hash = compute_file_sha256(temp_path)
        assert calc_hash == expected_hash
    finally:
        Path(temp_path).unlink(missing_ok=True)


def test_count_csv_data_rows() -> None:
    content = b"col1,col2\n1,2\n3,4\n5,6\n"
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        tf.write(content)
        temp_path = tf.name

    try:
        # 3 data rows (excluding header)
        count = count_csv_data_rows(temp_path)
        assert count == 3
    finally:
        Path(temp_path).unlink(missing_ok=True)


def test_count_csv_data_rows_without_trailing_newline() -> None:
    content = b"col1,col2\n1,2\n3,4"
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        tf.write(content)
        temp_path = tf.name

    try:
        # 2 data rows
        count = count_csv_data_rows(temp_path)
        assert count == 2
    finally:
        Path(temp_path).unlink(missing_ok=True)


def test_safe_sql_identifier_construction() -> None:
    manifest = load_manifest()
    for ds in manifest:
        query = sql.SQL("SELECT count(*) FROM {}.{}").format(
            sql.Identifier(ds["schema"]),
            sql.Identifier(ds["table"]),
        )
        as_string = query.as_string()
        assert f'"{ds["schema"]}"."{ds["table"]}"' in as_string
