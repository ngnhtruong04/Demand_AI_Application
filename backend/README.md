# DemandAI — Backend (FastAPI + AWS RDS PostgreSQL)

Đây là thành phần Backend của dự án **DemandAIApplication**, phục vụ dự báo nhu cầu bán lẻ và quản trị pipeline nạp dữ liệu raw (Raw Data Ingestion) độc lập.

Bạn có thể chạy các lệnh trực tiếp từ thư mục `backend/` hoặc thông qua root `Makefile` ở cấp dự án `DemandAIApplication/`.

---

## 1. Kiến trúc tổng quan

```text
Rohlik CSVs (data/raw/)
        │
        ▼
CLI Profiling & Ingestion (local) ───[ TLS verify-full, port 5432 ]───► AWS RDS PostgreSQL
                                                                                ▲
                                                                                │
FastAPI runtime (local) ─────────────[ Chỉ đọc raw data qua API user ]──────────┘
```

1. **FastAPI** chạy ở môi trường local, phục vụ các API truy vấn nghiệp vụ.
2. **AWS RDS PostgreSQL** đóng vai trò là cơ sở dữ liệu trung tâm trên AWS.
3. **Security Group** trên AWS chỉ mở port `5432` cho public IP `/32` của máy chạy code. Tuyệt đối không mở `0.0.0.0/0`.
4. **Ingestion pipeline** là CLI chạy riêng biệt, không tạo endpoint FastAPI để upload dữ liệu.

---

## 2. Phân tách quyền người dùng (Database Credentials)

Để đảm bảo nguyên tắc đặc quyền tối thiểu (*least privilege*), hệ thống sử dụng hai nhóm thông tin đăng nhập riêng biệt:

| Vai trò | Biến môi trường | User PostgreSQL | Mục đích & Quyền hạn |
| --- | --- | --- | --- |
| **Master User** | `RDS_MASTER_USERNAME`<br>`RDS_MASTER_PASSWORD` | `tttv_admin` | Quản trị viên: migration (Alembic), tạo schema/bảng, bulk load (`COPY`), tạo index, chạy `ANALYZE`, phân quyền. |
| **API Runtime User** | `RDS_API_USERNAME`<br>`RDS_API_PASSWORD` | `tttv_demandforecast_api` | Ứng dụng FastAPI: Chỉ có quyền `USAGE` trên schema `raw` và `SELECT` trên 4 bảng dữ liệu raw (`calendar`, `inventory`, `sales_train`, `test_weights`). Không được phép ghi/xóa/sửa dữ liệu và không được đọc bảng quản trị `ingestion_log`. |

> **Lưu ý:** Không còn sử dụng các biến mơ hồ `RDS_USERNAME` và `RDS_PASSWORD`.

---

## 3. Cài đặt và cấu hình

### 3.1. Thiết lập môi trường Python

```bash
python3 -m venv .venv
source .venv/bin/activate
make install
```

### 3.2. Cấu hình file `.env`

Tạo file `.env` từ `.env.example`:

```bash
cp .env.example .env
```

Điền thông tin kết nối RDS:

```env
APP_NAME=Rohlik Sales API
APP_ENV=development
API_V1_PREFIX=/api/v1
CORS_ORIGINS=["http://localhost:3000","http://127.0.0.1:3000"]

RDS_ENDPOINT=your-db.xxxxxxxxxxxx.ap-southeast-1.rds.amazonaws.com
RDS_PORT=5432
RDS_DATABASE=rohlik_sales
RDS_SSL_MODE=verify-full
RDS_SSL_ROOT_CERT=certs/global-bundle.pem

# Master credentials
RDS_MASTER_USERNAME=tttv_admin
RDS_MASTER_PASSWORD=your-real-master-password

# Runtime credentials
RDS_API_USERNAME=tttv_demandforecast_api
RDS_API_PASSWORD=your-real-api-password

# Raw data
RAW_DATA_DIR=data/raw
RAW_PROFILE_REPORT=reports/raw_profile.json
```

### 3.3. Tải AWS RDS CA Certificate

Tải bundle CA certificate của AWS RDS để kích hoạt mã hóa TLS `verify-full`:

```bash
make cert
```

Chứng chỉ được lưu tại `certs/global-bundle.pem` (được bảo vệ trong `.gitignore`, không commit lên Git).

### 3.4. Kiểm tra kết nối cơ sở dữ liệu

```bash
make check-db
```

Kết quả mong đợi:
```text
Master database connection: OK
API database connection: OK
TLS connection: enabled
```

---

## 4. Quy trình chạy Raw Data Pipeline

Để khởi tạo schema, profile và nạp dữ liệu hoàn chỉnh, thực hiện theo đúng thứ tự các lệnh:

```bash
# 1. Profile 4 file CSV nguồn (calendar, inventory, test_weights, sales_train)
make profile-raw

# 2. Chạy migration tạo schema raw, bảng và phân quyền
make migrate

# 3. Dry-run thử nghiệm nạp mẫu 1,000 dòng để kiểm tra kiểu dữ liệu và thứ tự cột
make dry-run-raw

# 4. Thực hiện bulk ingestion toàn bộ dữ liệu bằng PostgreSQL COPY FROM STDIN
make load-raw

# 5. Đối soát dữ liệu (row count, checksum, cross-table) và kiểm tra phân quyền API user
make validate-raw

# 6. Chạy bộ unit tests
make test

# 7. Khởi động FastAPI server
make run
```

---

## 5. Cơ chế Idempotency & Tùy chọn `--replace`

Pipeline nạp dữ liệu được thiết kế an toàn và idempotent:

- **Ngăn chặn nạp trùng:** Bảng `raw.ingestion_log` ghi nhận checksum SHA-256 của từng file. Nếu file có cùng checksum đã nạp `success`, các lần chạy tiếp theo của `make load-raw` sẽ tự động **bỏ qua** (`skipped`).
- **Bảo vệ dữ liệu:** Nếu một bảng đã có dữ liệu nhưng checksum file nguồn khác đi, loader sẽ **dừng an toàn** để tránh ghi đè ngoài ý muốn.
- **Tùy chọn ghi đè (`--replace`):** Khi bạn có chủ đích muốn nạp lại toàn bộ dữ liệu mới, chạy:
  ```bash
  .venv/bin/python -m scripts.ingestion.load_raw --all --replace
  ```
  Lệnh này sẽ `TRUNCATE` bảng tương ứng trong transaction nạp dữ liệu và load lại dữ liệu mới nhất.

---

## 6. Đọc kết quả Profile và Validation Reports

Sau khi chạy, các báo cáo dạng JSON được lưu trữ trong thư mục `reports/`:

1. **`reports/raw_profile.json`:**
   - Kích thước file, mã băm SHA-256, tổng số dòng.
   - Thống kê từng cột: kiểu dữ liệu suy diễn (`inferred_pg_type`), số lượng và tỷ lệ null (`null_count`, `null_ratio`), giá trị min/max, độ dài tối đa, các mẫu giá trị an toàn.
   - Báo cáo candidate key và kiểm tra trùng lặp (`duplicate_count`).

2. **`reports/raw_validation.json`:**
   - Trạng thái tổng thể (`overall_status: PASS`).
   - Khớp row count giữa CSV nguồn và PostgreSQL.
   - Khớp SHA-256 với lịch sử `ingestion_log`.
   - Kết quả đối soát liên bảng: kiểm tra sự nhất quán giữa `sales_train` với `inventory` và `calendar`.
   - Kết quả kiểm tra quyền bảo mật của user `tttv_demandforecast_api` (chỉ có quyền `SELECT` 4 bảng dữ liệu, không đọc được `ingestion_log`, không có quyền ghi hay tạo schema).

---

## 7. Khắc phục sự cố thường gặp (Troubleshooting)

- **Lỗi Timeout khi kết nối RDS (`OperationalError: connection timed out`):**
  - Public IP của bạn có thể đã thay đổi (thường gặp khi dùng mạng động/wifi).
  - Lấy IP hiện tại: `curl -4 https://checkip.amazonaws.com`
  - Cập nhật lại Inbound Rule trong AWS RDS Security Group cho port `5432` với CIDR `YOUR_IP/32`.
- **Lỗi Chứng chỉ SSL (`root certificate file ... does not exist`):**
  - Chạy `make cert` để tải lại file `certs/global-bundle.pem`.
- **Lỗi Xác thực mật khẩu (`password authentication failed`):**
  - Kiểm tra mật khẩu trong `.env`. Đảm bảo các ký tự đặc biệt được lưu chính xác (code đã sử dụng `SQLAlchemy URL.create()` để tự động encode ký tự đặc biệt).
  - Đảm bảo `RDS_MASTER_USERNAME` và `RDS_API_USERNAME` không bị hoán đổi.
- **Lỗi Quyền hạn API User (`permission denied for table ...`):**
  - Chạy lại `make migrate` để đảm bảo lệnh `GRANT SELECT` được thực thi đầy đủ bởi master user.

## PostgreSQL core layer

The backend includes a validated `core` schema for inventory, calendar, daily sales, and series weights. See [`backend/docs/core_database.md`](backend/docs/core_database.md) for source mapping, commands, query contracts, rerun behavior, AWS deployment state, and test limitations.

```bash
make core-inspect
make core-validate
make core-migrate
make core-load
make core-verify
```

## Demo inventory snapshot

`static_inventory_by_item.csv` represents the starting inventory for a demo scenario. Its
`status` column is normalized and stored as `scenario_group`; it is not the current action.
The current action (`In Stock`, `Monitor`, `Reorder`, `Critical`, or `Deadstock`) is
calculated later by the Run Forecast flow.

The inventory is the opening stock for the forecast period. The loader requires
`snapshot_date = max(core.sales_daily.date) + 1 day` to prevent a gap between history and
forecast. In the bundled data, sales end on 2024-06-02, so the snapshot date is 2024-06-03.

```bash
make migrate
make dry-run-inventory-snapshot SNAPSHOT_DATE=2024-06-03
make load-inventory-snapshot SNAPSHOT_DATE=2024-06-03
```

The snapshot date is mandatory. Loading the same checksum for the same date is idempotent.
If that date already contains different data, review it and rerun the module explicitly with
`--replace`; replacement deletes and reloads only that snapshot date in one transaction.

## Real forecast jobs and live progress

`Run Forecast` now starts real work using `POST /api/v1/forecast/runs` with
`{"request_id":"<client-generated UUID>"}`. A repeated request ID reuses the same
job. While a job is running, other start requests attach to that active job to
avoid loading multiple ensembles into memory.

- `GET /api/v1/forecast/runs/{job_id}` returns the current job and all four stage statuses.
- `GET /api/v1/forecast/runs/{job_id}/events` streams snapshots via SSE. Connecting
  or reconnecting only observes the job; it never executes a pipeline.
- `GET /api/v1/forecast/forecast_status` is retired and returns HTTP 410.
- Successful jobs include `run_id`. Fetch all result pages with
  `get_forecast_14d?source=database&run_id=<run_id>&limit=500&offset=0`.
  These requests never switch to cached results from another run.

The existing inactive-item policy is retained: items with no sales in the last
10 days are excluded before feature engineering. The stages execute real history
extraction, feature engineering, recursive
14-day inference, then inventory analysis/persistence. SHAP runs separately on demand.
Only a successful PostgreSQL commit allows the final stage to complete.
Failure stops the pipeline, marks the current stage failed, and leaves later
stages pending. The 14-day forecast starts after the latest historical date in
RDS; it does not assume today's date when the dataset is historical.

### Required trained models

Place the trained `lightgbm.joblib`, `xgboost.joblib`, and `catboost.joblib` in
`backend/models/`, matching the existing `feature_contract.json` and
`selected_weights.json`. They are ignored by Git. Saved predictions and SHAP
parquet files are not substitutes for trained model binaries. Without these
files, stage 3 reports a missing-model error; it does not report completion or
load old forecasts. Each run retains immutable model binaries and the exact per-horizon model inputs
in `backend/data/forecast_artifacts/<run_id>/` for on-demand explanations. These
artifacts and item caches are removed when subsequent successful runs prune the
corresponding database run. Keep this directory on persistent storage.

### Execution scope

This implementation uses one background thread and an in-memory job registry
inside **one Uvicorn worker process**. Use the existing single-worker launch
command; do not use multiple workers/replicas with this registry. SSE disconnects
and browser reloads do not stop the job. Restarting/reloading the backend loses
in-flight jobs and job status (the UI reports job-not-found); committed forecasts
remain in PostgreSQL. Up to 30 recent job states are retained. For multi-worker
production deployment, move the registry and execution to a durable queue/worker
service before scaling. Model inference can take longer than loading precomputed results; there is no
synthetic completion timer. SHAP no longer blocks forecast readiness.

Validation without model binaries or RDS writes:

```bash
.venv/bin/python -m pytest tests/test_forecast_jobs.py tests/test_forecast_api.py -q
```

### On-demand item SHAP

- `POST /api/v1/forecast/runs/{run_id}/items/{item_id}/shap` starts/reuses an item
  explanation job; it immediately returns queued/running/completed/failed status.
- `GET` on that URL only reads status/results. Repeated requests for the same
  `(run_id, item_id)` share one task; failed tasks can be retried with POST.
- The worker explains only the selected item's 14 saved input rows, using that
  run's copied models, categorical encodings, and ensemble weights. It never
  uses SHAP from an older run or recalculates the forecast.
- Completed explanations update PostgreSQL and an atomic per-run/item JSON cache.
  The cache survives backend restarts. Active SHAP jobs use a single background
  worker and are lost on restart; the client can request them again.
- The forecast list is ready after inventory analysis and database commit.
  SHAP is reported separately as queued/calculating/ready/failed. Missing SHAP
  values are not replaced with mock drivers.
- Runs created before input snapshots were introduced cannot compute new SHAP
  on demand; create a new forecast for those items.

On-demand regression tests:

```bash
.venv/bin/python -m pytest tests/test_item_shap.py tests/test_forecast_jobs.py tests/test_forecast_api.py -q
```
