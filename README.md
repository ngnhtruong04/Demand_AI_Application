# DemandAI Application

Dự án ứng dụng fullstack **DemandAI** phục vụ dự báo nhu cầu bán lẻ và quản trị pipeline nạp dữ liệu raw (Raw Data Ingestion) lên AWS RDS PostgreSQL.

Dự án gồm 2 thành phần độc lập:
- **`backend/`**: REST API xây dựng bằng FastAPI, SQLAlchemy 2, Alembic, psycopg 3 và pipeline ETL CSV dạng stream.
- **`frontend/`**: Giao diện người dùng hiện đại xây dựng bằng Next.js (App Router), TypeScript và Tailwind CSS.

> 📘 **Tài Liệu Dành Cho Kỹ Sư Phát Triển (Intern • Fresher • Junior)**:
> Xem [Cẩm Nang Phát Triển Dự Án Chi Tiết (Developer Onboarding & Architecture Guide)](docs/developer_guide.md) để nắm toàn bộ sơ đồ kiến trúc, cơ chế ML Recursive Ensemble, TreeSHAP explainability, hệ thống ReAct Agent, SSE streaming, và cẩm nang công thức thực hành (Cookbook).
>
> 🛒 **Tài Liệu Dành Cho Người Dùng Cuối & Quản Lý Vận Hành (End-User Guide)**:
> Xem [Hướng Dẫn Vận Hành Nền Tảng Cho Quản Trị Kho & Chuỗi Cung Ứng](docs/user_guide.md) để nắm quy trình dự báo 14 ngày, đọc hiểu 5 trạng thái rủi ro tồn kho, phân tích động lực TreeSHAP, và khai thác 10 lệnh tắt của Trợ lý ảo AI.

---

## 1. Yêu cầu môi trường (Prerequisites)

- **Python**: `>= 3.11` (đã kiểm thử và xác nhận trên Python `3.12.3`).
- **Node.js**: `>= 22.6.0` (Khuyến nghị sử dụng Node.js `22 LTS`, đã kiểm thử và xác nhận trên Node.js `v22.23.2 LTS`).
Bộ test frontend dùng tính năng TypeScript stripping của Node.js, vì vậy yêu cầu Node cao hơn mức tối thiểu của Next.js.

- **npm**: `>= 10` (đã kiểm thử trên npm `10.9.8`).
- **Make**: Tiện ích `make` có sẵn trên hệ thống Linux/macOS.

---

## 2. Cấu trúc thư mục

```text
DemandAIApplication/
├── frontend/                     # Next.js 16 + React 19 + Tailwind CSS 4
│   ├── src/
│   │   ├── app/                 # App Router (page.tsx, layout.tsx, globals.css)
│   │   └── lib/                 # API helpers (api.ts)
│   ├── public/
│   ├── .env.example
│   ├── package.json
│   ├── package-lock.json
│   └── tsconfig.json, eslint.config.mjs, postcss.config.mjs
├── backend/                      # FastAPI + SQLAlchemy + Ingestion Pipeline
│   ├── app/                     # FastAPI core, db, models, routes
│   ├── alembic/                 # Database migrations
│   ├── scripts/                 # Ingestion pipeline & DB check scripts
│   ├── tests/                   # Pytest unit & path resilience tests
│   ├── config/                  # Manifest allowlist (raw_datasets.json)
│   ├── certs/                   # AWS RDS CA certificate bundle
│   ├── data/                    # Raw CSV datasets
│   ├── reports/                 # Profiling & validation reports
│   ├── docs/                    # Backend architecture documentation
│   ├── .env.example
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── Makefile
│   └── README.md
├── docs/plans/                   # Kế hoạch và báo cáo refactor
│   ├── fullstack_refactor_plan.md
│   └── fullstack_refactor_report.md
├── .gitignore                    # Bảo vệ secret, .venv, node_modules, certs
├── Makefile                      # Root commands điều phối cả hai ứng dụng
└── README.md
```

---

## 3. Cấu hình (Configuration)

### 3.1. Cấu hình Backend

Tạo file `backend/.env` từ `backend/.env.example`:

```bash
cp backend/.env.example backend/.env
```

Điền các thông tin kết nối RDS:

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

RDS_MASTER_USERNAME=tttv_admin
RDS_MASTER_PASSWORD=your-real-master-password

RDS_API_USERNAME=tttv_demandforecast_api
RDS_API_PASSWORD=your-real-api-password

RAW_DATA_DIR=data/raw
RAW_PROFILE_REPORT=reports/raw_profile.json
```

> **Quy tắc đường dẫn:** Mọi đường dẫn tương đối trong cấu hình backend (`certs/`, `data/`, `reports/`, `config/`) được neo tự động vào thư mục `backend/` thông qua `pathlib`, đảm bảo chạy đúng từ bất kỳ thư mục làm việc nào.

### 3.2. Cấu hình Frontend

Tạo file `frontend/.env.local` từ `frontend/.env.example`:

```bash
cp frontend/.env.example frontend/.env.local
```

Nội dung:

```env
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

---

## 4. Cài đặt ban đầu (Fresh Setup)

Từ thư mục gốc `DemandAIApplication/`:

```bash
# 1. Cài đặt môi trường ảo và dependencies Backend
make install-backend

# 2. Cài đặt dependencies Frontend
make install-frontend
```

---

## 5. Chạy ứng dụng (Development Mode)

Chạy trên 2 terminal riêng biệt:

### Terminal 1: Backend (FastAPI)

```bash
make dev-backend
```
*Backend khởi động tại: `http://127.0.0.1:8000`*

### Terminal 2: Frontend (Next.js)

```bash
make dev-frontend
```
*Frontend khởi động tại: `http://localhost:3000`*

---

## 6. Danh sách URL

| Dịch vụ | URL | Mô tả |
| --- | --- | --- |
| **Frontend UI** | [http://localhost:3000](http://localhost:3000) | Giao diện DemandAI hiển thị trạng thái kết nối liveness và thao tác thử lại |
| **Backend Root** | [http://127.0.0.1:8000/](http://127.0.0.1:8000/) | Thông tin metadata ứng dụng FastAPI |
| **Backend Health** | [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health) | Endpoint kiểm tra liveness (trả về `{"status":"healthy"}`) |
| **Swagger API Docs** | [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) | Tài liệu OpenAPI tương tác trực tiếp |

---

## 7. Các lệnh kiểm tra & CI

Chạy từ thư mục gốc `DemandAIApplication/`:

```bash
# Chạy toàn bộ unit test backend (bao gồm test hồi quy đường dẫn)
make test-backend

# Chạy kiểm thử API helper frontend (timeout, parse, connection error)
make test-frontend

# Kiểm tra cú pháp và quy chuẩn mã nguồn frontend
make lint-frontend

# Kiểm tra kiểu dữ liệu TypeScript của frontend
make typecheck-frontend

# Build bản đóng gói production của frontend
make build-frontend

# Kiểm tra kết nối DB có mã hóa TLS (yêu cầu RDS credentials)
make check-db

# Thử nghiệm nạp dữ liệu mẫu 1000 dòng an toàn (dry-run: stream COPY trong transaction và luôn rollback, không lưu thay đổi vào DB)
make dry-run-raw
```

## PostgreSQL core layer

The backend includes a validated `core` schema for inventory, calendar, daily sales, and series weights. See [`backend/docs/core_database.md`](backend/docs/core_database.md) for mapping, commands, rerun behavior and test limitations.

```bash
make core-inspect
make core-validate
make core-migrate
make core-load
make core-verify
```
