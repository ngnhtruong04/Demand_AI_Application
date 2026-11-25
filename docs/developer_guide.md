# 📘 DemandAI - Developer Onboarding & Architecture Guide
> **Tài Liệu Hướng Dẫn Phát Triển Dành Cho Kỹ Sư: Intern • Fresher • Junior**  
> *Được biên soạn theo quy chuẩn kiến trúc `code-documenter` chuyên sâu: trực quan, chi tiết từng bước, kèm ví dụ thực tế và cẩm nang xử lý sự cố.*

---

## 📑 Mục Lục
1. [Giới Thiệu & Kiến Trúc Tổng Quan (System Architecture & Mental Model)](#1-giới-thiệu--kiến-trúc-tổng-quan-system-architecture--mental-model)
2. [Hướng Dẫn Cài Đặt & Khởi Chạy Local (Quickstart: 0 to Running in 5 mins)](#2-hướng-dẫn-cài-đặt--khởi-chạy-local-quickstart-0-to-running-in-5-mins)
3. [Bản Đồ Cấu Trúc Mã Nguồn (Repository Structure & Code Tour)](#3-bản-đồ-cấu-trúc-mã-nguồn-repository-structure--code-tour)
4. [Deep-Dive: Pipeline Dự Báo & TreeSHAP (ML Forecasting & Explainability)](#4-deep-dive-pipeline-dự-báo--treeshap-ml-forecasting--explainability)
   - [4.1. Cơ Chế Dự Báo Đệ Quy 14 Ngày](#41-cơ-chế-dự-báo-đệ-quy-14-day-recursive-ensemble)
   - [4.2. Tối Ưu Tốc Độ Với Parquet Cache](#42-tối-ưu-tốc-độ-với-parquet-cache)
   - [4.3. Giải Thích Quyết Định Bằng TreeSHAP Chạy Ngầm](#43-giải-thích-quyết-định-bằng-treeshap-chạy-ngầm)
   - [4.4. Tính Tất Định Tuyệt Đối & Khử Nhiễu Đa Luồng](#44-tính-tất-định-tuyệt-đối--khử-nhiễu-đa-luồng-strict-determinism)
   - [4.5. Cơ Chế Lọc SKU Ngưng Hoạt Động](#45-cơ-chế-lọc-sku-ngưng-hoạt-động-inactive-items-filtering)
5. [Deep-Dive: SKU Assistant & Hệ Thống Agent AI (LLM Agent & Tools)](#5-deep-dive-sku-assistant--hệ-thống-agent-ai-llm-agent--tools)
   - [5.1. Kiến Trúc ReAct Agent & Streaming SSE](#51-kiến-trúc-react-agent--streaming-sse)
   - [5.2. Danh Sách 9 Công Cụ Nghiệp Vụ Cốt Lõi](#52-danh-sách-công-cụ-nghiệp-vụ-agent-tools)
   - [5.3. Hệ Thống Slash Commands](#53-hệ-thống-slash-commands)
   - [5.4. Deep-Dive: What-If Demand Simulation Engine](#54-deep-dive-what-if-demand-simulation-engine)
6. [Deep-Dive: Cơ Sở Dữ Liệu & Lưu Trữ Phiên (Database & Persistence)](#6-deep-dive-cơ-sở-dữ-liệu--lưu-trữ-phiên-database--persistence)
7. [Deep-Dive: Giao Diện Người Dùng (Frontend Architecture & Canvas)](#7-deep-dive-giao-diện-người-dùng-frontend-architecture--canvas)
8. [Cookbook: Cẩm Nang Thực Hành Cho Developer (Step-by-Step Practical Recipes)](#8-cookbook-cẩm-nang-thực-hành-cho-developer-step-by-step-practical-recipes)
   - [Recipe 1: Thêm một Agent Tool mới](#recipe-1-thêm-một-agent-tool-mới)
   - [Recipe 2: Thêm một Slash Command mới trên Chat Composer](#recipe-2-thêm-một-slash-command-mới-trên-chat-composer)
   - [Recipe 3: Thêm một API Endpoint mới trong FastAPI](#recipe-3-thêm-một-api-endpoint-mới-trong-fastapi)
   - [Recipe 4: Tạo và chạy Database Migration với Alembic](#recipe-4-tạo-và-chạy-database-migration-với-alembic)
9. [Kiểm Thử & Tiêu Chuẩn Chất Lượng Mã Nguồn (Testing & Quality Assurance)](#9-kiểm-thử--tiêu-chuẩn-chất-lượng-mã-nguồn-testing--quality-assurance)
10. [Lỗi Thường Gặp & Cẩm Nang Khắc Phục (Troubleshooting & FAQs)](#10-lỗi-thường-gặp--cẩm-nang-khắc-phục-troubleshooting--faqs)

---

## 1. Giới Thiệu & Kiến Trúc Tổng Quan (System Architecture & Mental Model)

### 1.1. DemandAI là gì?
**DemandAI** là nền tảng phân tích và dự báo nhu cầu bán lẻ đa kênh (Retail Demand Forecasting) thông minh. Hệ thống kết hợp 4 trụ cột công nghệ:
1. **Pipeline Dự báo 14 ngày (14-day Recursive Ensemble)**: Sử dụng tổ hợp các mô hình Machine Learning mạnh mẽ nhất cho dữ liệu bảng (**CatBoost**, **LightGBM**, **XGBoost**) để dự báo nhu cầu tương lai cho hàng ngàn mặt hàng (SKU).
2. **Khả năng Giải thích Quyết định (Explainable AI - TreeSHAP)**: Bóc tách chính xác các yếu tố chi phối nhu cầu của từng SKU theo 4 nhóm động lực: *Lịch sử doanh số (Sales Lags)*, *Biến động giá (Pricing)*, *Chương trình khuyến mãi (Promotions)*, và *Tính mùa vụ (Seasonality)*.
3. **Trợ lý AI Đàm thoại Nghiệp vụ (Conversational SKU Agent)**: Agent thông minh sử dụng kiến trúc ReAct kết hợp LangChain và Server-Sent Events (SSE) để truy vấn thông tin tồn kho, cảnh báo hết hàng, so sánh đồng nghiệp (peer comparison), sinh báo cáo PDF và xuất file CSV kế hoạch đặt hàng.
4. **Data Ingestion & Quản trị dữ liệu lớn**: Quản lý dữ liệu lịch sử bán hàng, kho bãi trên PostgreSQL RDS cùng cơ chế bộ nhớ đệm tốc độ cao bằng Parquet.

### 1.2. Sơ Đồ Kiến Trúc Hệ Thống (Architecture Diagram)

```mermaid
flowchart TB
    subgraph Frontend["Frontend Layer (Next.js 16 + React 19)"]
        UI["DemandAI Shell & Canvas UI"]
        Chat["Chat Panel & Composer (/commands)"]
        Charts["Line Charts & TreeSHAP Waterfall"]
    end

    subgraph Gateway["API Gateway / Backend (FastAPI)"]
        API["FastAPI App (uvicorn :8000)"]
        SSE["SSE Event Stream (/api/v1/chat/stream)"]
        ForeAPI["Forecast Endpoints (/api/v1/forecast/...)"]
    end

    subgraph AgentSystem["SKU Agent Intelligence"]
        Agent["LangChain ReAct Agent (OpenAI GPT-6-Luna)"]
        Tools["Agent Tools (Inventory, SHAP, PDF, CSV, Warehouse)"]
        Fall["Local Fallback Engine (Offline)"]
    end

    subgraph MLEngine["Machine Learning & Feature Engine"]
        FE["Feature Engineering (Lags, Rollings, Prices)"]
        Ensemble["Recursive Ensemble (CatBoost, LightGBM, XGBoost)"]
        SHAP["TreeSHAP Explainer (Background Worker)"]
    end

    subgraph Storage["Storage & Persistence Layer"]
        RDS[("AWS RDS PostgreSQL (core & raw schemas)")]
        ParquetCache[("Parquet Local Cache (data/cache/)")]
        Artifacts[("Generated PDF & CSV Exports (data/exports/)")]
    end

    UI -->|"HTTP REST Requests"| ForeAPI
    Chat -->|"SSE Streaming"| SSE
    Charts -->|"Fetch Data / SHAP"| ForeAPI

    SSE --> Agent
    Agent --> Tools
    Tools -->|"Fallback if offline"| Fall
    Tools -->|"Query Live Data"| RDS
    Tools -->|"Generate PDF/CSV"| Artifacts

    ForeAPI --> Ensemble
    ForeAPI --> SHAP
    Ensemble --> FE
    FE --> RDS
    FE <--> ParquetCache
    SHAP --> Ensemble
    ForeAPI --> RDS
```

### 1.3. Luồng Dữ Liệu Chuẩn (End-to-End Request Lifecycle)
1. **Khởi động**: Khi người dùng vào Dashboard, Frontend gọi `GET /api/v1/forecast/runs` để kiểm tra có phiên dự báo nào đang hoạt động hoặc đã lưu hay không.
2. **Chạy Dự Báo**: Khi người dùng kích hoạt phiên dự báo, Backend gọi `POST /api/v1/forecast/runs`. Một background task được sinh ra để chạy mô hình ensemble đệ quy 14 ngày cho các SKU. Kết quả được lưu tạm trong bộ nhớ và cache Parquet.
3. **Truy vấn với SKU Assistant**: Người dùng nhập câu hỏi hoặc gõ `/warehouse`, `/reorder`. Frontend mở luồng kết nối SSE tới `POST /api/v1/chat/stream`. Agent phân tích ý định (intent), gọi các công cụ nghiệp vụ tương ứng trong `tools.py`, stream suy nghĩ (*thought*) và kết quả từng từ về giao diện người dùng.
4. **Lưu trữ phiên (Persistence)**: Người dùng có thể nhấn nút "Save Forecast" để ghi vĩnh viễn toàn bộ kết quả dự báo 14 ngày vào bảng `core.forecast_runs` và `core.forecast_records` trên PostgreSQL RDS.

---

## 2. Hướng Dẫn Cài Đặt & Khởi Chạy Local (Quickstart: 0 to Running in 5 mins)

### 2.1. Yêu Cầu Môi Trường (Prerequisites)
- **Hệ điều hành**: Linux (Ubuntu 20.04+ khuyến nghị) hoặc macOS.
- **Python**: `>= 3.11` (Khuyến nghị `Python 3.12.3`).
- **Node.js**: `>= 22.6.0` (Khuyến nghị `Node.js 22 LTS`).
- **npm**: `>= 10` (Khuyến nghị `npm 10.9.8+`).
- **Make**: Tiện ích `make` có sẵn trong hệ điều hành (`sudo apt install build-essential`).

> [!IMPORTANT]
> **Lưu ý về Node.js 22+**: Bộ test frontend sử dụng tính năng native TypeScript stripping (`node --experimental-strip-types`), do đó bắt buộc bạn phải cài đặt Node.js version 22 trở lên.

### 2.2. Thiết Lập Backend

```bash
# 1. Di chuyển vào thư mục backend
cd backend

# 2. Tạo virtual environment bằng Python 3.12
python3 -m venv .venv

# 3. Kích hoạt môi trường ảo
source .venv/bin/activate

# 4. Cài đặt các thư viện phụ thuộc
pip install --upgrade pip
pip install -e .

# 5. Cấu hình biến môi trường
cp .env.example .env
```

Cấu hình file `backend/.env` với các giá trị tiêu chuẩn:
```ini
PROJECT_NAME="DemandAI Retail Forecasting"
API_V1_PREFIX="/api/v1"

# Database Configuration (PostgreSQL / AWS RDS)
DATABASE_URL="postgresql+asyncpg://postgres:YourPassword@your-db-host:5432/demand_ai"
DATABASE_URL_SYNC="postgresql+psycopg2://postgres:YourPassword@your-db-host:5432/demand_ai"

# CORS Configuration
CORS_ORIGINS=["http://localhost:3000","http://127.0.0.1:3000"]

# OpenAI API Key (Dành cho Conversational SKU Agent)
# Nếu để trống, hệ thống sẽ tự động chuyển sang chế độ Rule-based Fallback mượt mà
OPENAI_API_KEY="sk-..."
OPENAI_MODEL="gpt-6-luna"
```

### 2.3. Thiết Lập Frontend

```bash
# 1. Di chuyển vào thư mục frontend
cd ../frontend

# 2. Cài đặt các gói phụ thuộc qua npm
npm install

# 3. Cấu hình biến môi trường
cp .env.example .env.local
```

File `frontend/.env.local`:
```ini
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### 2.4. Khởi Chạy Toàn Bộ Hệ Thống Bằng Makefile

Tại thư mục gốc của dự án (`DemandAIApplication/`), bạn chỉ cần chạy 1 lệnh duy nhất:

```bash
make dev
```

Lệnh trên sẽ khởi chạy song song:
- **Backend API**: `http://localhost:8000` (FastAPI Server với live reload)
- **Frontend App**: `http://localhost:3000` (Next.js Turbopack)

Nếu muốn chạy riêng biệt từng dịch vụ:
```bash
# Chỉ chạy Backend:
make dev-backend

# Chỉ chạy Frontend:
make dev-frontend
```

### 2.5. Kiểm Tra Hệ Thống Hoạt Động & Tài Liệu API (Verification Checkpoints)
- **Swagger UI (FastAPI Native)**: [http://localhost:8000/docs](http://localhost:8000/docs) — Giao diện kiểm thử trực tiếp 27 API endpoints với đầy đủ schema và tham số mẫu.
- **Swagger UI (Frontend Nhúng)**: [http://localhost:3000/docs](http://localhost:3000/docs) — Trang API Management tích hợp sẵn bộ lọc theo từng nhóm nghiệp vụ (`forecast`, `chat`, `wiki`, `pipeline`, `feature-engineering`, `health`, `system`).
- **ReDoc UI**: [http://localhost:8000/redoc](http://localhost:8000/redoc) — Giao diện tài liệu kỹ thuật ba cột tối ưu cho việc đọc đặc tả OpenAPI.
- **Raw OpenAPI 3.1 JSON**: [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json) — File JSON chuẩn hóa phục vụ import vào Postman, Insomnia hoặc sinh client SDK.
- **Liveness probe**: `curl http://localhost:8000/health` -> `{"status":"healthy"}`
- **Database connection probe**: `curl http://localhost:8000/api/v1/health/database` -> `{"status":"healthy","database":"connected","tls":true}`
- **Giao diện người dùng (Next.js Dashboard)**: [http://localhost:3000](http://localhost:3000)

---

## 3. Bản Đồ Cấu Trúc Mã Nguồn (Repository Structure & Code Tour)

```text
DemandAIApplication/
├── backend/                      # Python FastAPI + Data Science + ML Pipeline
│   ├── alembic/                 # Quản trị Database Schema Migrations
│   │   ├── versions/            # Các file migration từng phiên bản
│   │   └── env.py               # Cấu hình kết nối Alembic với SQLAlchemy
│   ├── app/                     # Mã nguồn chính của Backend
│   │   ├── agent/               # Hệ thống Conversational SKU Agent
│   │   │   ├── sku_agent.py     # LangChain Agent ReAct Executor & SSE streamer
│   │   │   ├── tools.py         # Tập hợp công cụ (Inventory, SHAP, PDF, CSV, Warehouse)
│   │   │   ├── presets.py       # Các mẫu câu hỏi và kịch bản gợi ý
│   │   │   ├── skills.py        # Logic phân giải kỹ năng & slash commands
│   │   │   ├── language.py      # Phát hiện & chuẩn hóa ngôn ngữ (VI/EN)
│   │   │   └── fallback.py      # Bộ máy quy tắc trả lời khi không có OpenAI key
│   │   ├── api/                 # API Routes theo chuẩn RESTful
│   │   │   ├── router.py        # Gom cụm các router con vào API v1
│   │   │   └── routes/          # Các endpoint chi tiết
│   │   │       ├── forecast.py  # Chạy dự báo, xem kết quả, SHAP drivers, persistence
│   │   │       ├── chat.py      # SSE stream chat & quản lý mô hình
│   │   │       ├── health.py    # Kiểm tra trạng thái DB và hệ thống
│   │   │       ├── pipeline.py  # Ingestion pipeline streaming
│   │   │       └── feature_engineering.py # Trích xuất lag features
│   │   ├── core/                # Thiết lập cốt lõi
│   │   │   └── config.py        # Pydantic Settings đọc từ biến môi trường
│   │   ├── db/                  # Kết nối Database
│   │   │   ├── session.py       # Engine Async (asyncpg) & Sync (psycopg2)
│   │   │   └── base.py          # SQLAlchemy DeclarativeBase
│   │   ├── models/              # Định nghĩa bảng ORM
│   │   │   ├── core/            # Schema 'core' (dim_items, forecast_runs, ...)
│   │   │   └── raw/             # Schema 'raw' (sales_train, inventory, calendar)
│   │   ├── pipeline/            # ML Pipeline & Trích xuất đặc trưng
│   │   │   ├── recursive_ensemble.py # Dự báo đệ quy CatBoost + LightGBM + XGBoost
│   │   │   ├── feature_engineering.py# Lags, Rollings, Price elasticity
│   │   │   └── load_pipeline.py # Nạp dữ liệu vào database
│   │   ├── services/            # Nghiệp vụ chuyên sâu
│   │   │   ├── forecast_jobs.py # Quản lý hàng đợi job chạy dự báo nền
│   │   │   ├── item_shap.py     # Tính toán TreeSHAP theo từng SKU
│   │   │   ├── forecast_persistence.py # Lưu/Đọc forecast runs từ RDS
│   │   │   ├── forecast_artifacts.py   # Quản lý file cache & dọn dẹp phiên cũ
│   │   │   └── pdf_report_generator.py # Sinh báo cáo PDF chuyên nghiệp (ReportLab)
│   │   └── main.py              # Entrypoint khởi tạo FastAPI App & Lifespan
│   ├── data/                    # Thư mục lưu dữ liệu, model weights và cache
│   │   ├── cache/               # Parquet files cache tốc độ cao
│   │   ├── models/              # Weights model đã huấn luyện (.pkl, .cbm, .json)
│   │   └── exports/             # File PDF, CSV sinh ra cho người dùng tải
│   ├── tests/                   # Pytest suite toàn diện (>98 tests)
│   ├── Makefile                 # Makefile riêng của backend
│   └── pyproject.toml           # Định nghĩa dependencies & metadata dự án
│
├── frontend/                     # Next.js 16 (App Router) + React 19 + TypeScript
│   ├── src/
│   │   ├── app/                 # Next.js App Router
│   │   │   ├── page.tsx         # Trang ứng dụng chính (Dashboard + Chat)
│   │   │   ├── layout.tsx       # Root layout & font configurations
│   │   │   ├── globals.css      # CSS reset & base
│   │   │   ├── docs/page.tsx    # Trang nhúng Swagger API UI
│   │   │   └── health/page.tsx  # Trang hiển thị System & DB Health status
│   │   ├── components/          # UI Components
│   │   │   ├── DemandAIShell.tsx# Component gốc điều phối toàn bộ State
│   │   │   ├── chat/            # Hệ thống Chat & Slash Commands
│   │   │   │   ├── ChatPanel.tsx
│   │   │   │   ├── ChatComposer.tsx     # Nhập tin nhắn & menu popup /slash
│   │   │   │   ├── ChatMessages.tsx     # Danh sách tin nhắn & Markdown
│   │   │   │   └── AssistantInquiryCard.tsx # Thẻ xác nhận tương tác
│   │   │   ├── workspace/       # Không gian hiển thị trung tâm (Canvas)
│   │   │   │   ├── WorkspaceCanvas.tsx  # Canvas hiển thị bảng dữ liệu/báo cáo
│   │   │   │   ├── ForecastTable.tsx    # Bảng 3602 SKU có phân trang, tìm kiếm
│   │   │   │   └── ForecastStatusBadge.tsx
│   │   │   └── leftpanel/       # Bảng điều khiển phân tích bên trái
│   │   │       ├── DailyForecastLineChart.tsx # Biểu đồ đường 14 ngày
│   │   │       └── TreeShapComputingVisualizer.tsx # Biểu đồ SHAP Waterfall
│   │   ├── lib/                 # API Clients & Helper functions
│   │   │   ├── api.ts           # Client gọi API chung với Timeout & Retry
│   │   │   ├── forecastApi.ts   # Client gọi các endpoint dự báo & SHAP
│   │   │   └── chatApi.ts       # Client đọc luồng SSE streaming từ backend
│   │   ├── styles/
│   │   │   └── demand-ai.css    # Hệ thống Design Tokens Vanilla CSS cao cấp
│   │   └── types/               # TypeScript Interfaces định kiểu dữ liệu
│   └── package.json             # Cấu hình dependencies frontend
│
├── docs/                         # Tài liệu kiến trúc dự án
│   └── developer_guide.md       # Cẩm nang phát triển chi tiết này
└── Makefile                      # Makefile tổng điều phối toàn bộ monorepo
```

---

## 4. Deep-Dive: Pipeline Dự Báo & TreeSHAP (ML Forecasting & Explainability)

### 4.1. Cơ Chế Dự Báo Đệ Quy (14-day Recursive Ensemble)
Khác với mô hình Direct Forecasting (dự đoán song song 14 bước), DemandAI sử dụng **Recursive Multi-step Forecasting**:
- **Tại ngày t+1**: Mô hình sử dụng các biến trễ có sẵn (Lag 1, Lag 2, ...) từ lịch sử để dự đoán doanh số ngày tiếp theo ŷ(t+1).
- **Tại ngày t+2**: Giá trị ŷ(t+1) vừa dự đoán được đưa ngược trở lại làm Lag 1 mới, cập nhật lại các chỉ số trung bình động (Rolling means), và dự đoán tiếp ŷ(t+2).
- Quá trình này lặp lại liên tục cho đến hết 14 ngày.

```
[Lịch sử Bán hàng] ──────> [Trích xuất Lags/Rolling] ──────> [Mô hình Ensemble]
                                 ▲                                 │
                                 │                                 ▼
                                 └── Cập nhật đệ quy 14 ngày ◄── [Dự báo Ngày t+1]
```

#### Mô Hình Kết Hợp (Ensemble Blend)
Hệ thống sử dụng trọng số kết hợp (Weighted Average) từ 3 mô hình Gradient Boosting đã qua tối ưu hóa siêu tham số:
1. **LightGBM**: Tốc độ xử lý cực nhanh, bộ nhớ tối ưu.
2. **CatBoost**: Xử lý vượt trội các biến phân loại (Store, Category, Department).
3. **XGBoost**: Độ ổn định cao, kiểm soát overfitting tốt.

### 4.2. Tối Ưu Tốc Độ Với Parquet Cache
Tập dữ liệu lịch sử bán hàng của hơn 3.600 SKU trong 2 năm có dung lượng hàng chục triệu dòng. Nếu truy vấn trực tiếp từ PostgreSQL mỗi khi chạy dự báo sẽ mất hàng phút.
- Giải pháp: Khi chạy lần đầu, dữ liệu đã làm sạch và các ma trận đặc trưng được lưu vào `data/cache/processed_features.parquet`.
- Parquet là định dạng lưu trữ theo cột (columnar format) có nén, giúp giảm kích thước 80% và tốc độ đọc nhanh gấp 30 lần so với CSV/SQL.

### 4.3. Giải Thích Quyết Định Bằng TreeSHAP Chạy Ngầm
**TreeSHAP (SHapley Additive exPlanations)** tính toán mức độ đóng góp (Shapley value) của từng đặc trưng vào kết quả dự báo.
- **Vấn đề**: Tính toán SHAP cho toàn bộ 3.602 SKU x 14 ngày tốn rất nhiều CPU và RAM (có thể mất 5-10 phút).
- **Kiến trúc giải quyết của DemandAI**:
  1. **Lazy Computing**: Chỉ tính toán SHAP khi người dùng nhấp chọn một SKU cụ thể trên bảng hoặc khi Chat Agent yêu cầu.
  2. **Background Thread**: `app/services/item_shap.py` chạy tính toán SHAP trong luồng riêng và trả về `status: computing`.
  3. **File Caching**: Kết quả SHAP sau khi tính được lưu thành file JSON tạm `.shap_cache_{run_id}_{item_id}.json`. Các lần truy vấn sau sẽ trả về ngay lập tức trong 5ms.
  4. **Nhóm đặc trưng (Driver Grouping)**: Thay vì hiển thị hàng trăm biến kỹ thuật phức tạp cho người dùng kinh doanh, hệ thống gom thành 4 nhóm trực quan:
     - **Sales Lags**: Tác động từ đà bán hàng các tuần trước.
     - **Pricing**: Tác động từ việc tăng/giảm giá bán so với mức trung bình.
     - **Promotions**: Tác động từ các sự kiện giảm giá hoặc ngày lễ.
     - **Seasonality**: Tác động từ chu kỳ ngày trong tuần (thứ 7, CN) hoặc tháng.

### 4.4. Tính Tất Định Tuyệt Đối & Khử Nhiễu Đa Luồng (Strict Determinism)
Một yêu cầu sống còn của các hệ thống dự báo tài chính và tồn kho doanh nghiệp là **tính tái lập (Reproducibility)**: Cùng một tập dữ liệu đầu vào thì kết quả dự báo của mô hình phải đồng nhất 100% qua mọi lượt chạy.

#### Thực nghiệm kiểm chứng 5 lượt chạy độc lập:
Hệ thống được kiểm thử thực nghiệm bằng script `backend/scripts/test_reproducibility_5runs.py` trên toàn bộ **3.602 active SKUs** qua 7 kho hàng (**50.428 điểm dự báo** chu kỳ 14 ngày):
- **Sai số tuyệt đối tối đa ($\max |\Delta|$):** **`0.00000000`** qua tất cả 50.428 điểm dự báo và 14 ngày horizon.
- **Tỷ lệ trùng khớp bit-for-bit:** **`100.0%`**.
- **Sai số tích lũy đệ quy (Horizon Drift):** Độ lệch chuẩn $\sigma = 0.00000000$ từ Ngày 1 đến Ngày 14.

#### Kỹ thuật khử nhiễu đa luồng trong Feature Engineering:
Trong thư viện **Polars**, việc gọi `.unique()` trên dữ liệu lớn sử dụng thuật toán gom hash đa luồng (multi-threaded hash bucketing), khiến thứ tự của danh sách `unique_id` có thể bị hoán đổi ngẫu nhiên nếu thiếu `.sort()`. Khi danh sách SKU bị xáo trộn, hàm sinh giá và khuyến mãi tương lai `np.random.default_rng` sẽ gán nhầm số ngẫu nhiên giữa các item.
- **Giải pháp triệt để:** Tại [backend/app/pipeline/feature_engineering.py](../backend/app/pipeline/feature_engineering.py#L1041), luôn bọc `sorted(forecast_items.select([item_col]).unique().to_series().to_list())` để bảo đảm thứ tự bất biến tuyệt đối. Nhờ đó, cả bước sinh feature engineering lẫn bước suy luận đệ quy đều đạt độ tất định 100%.

### 4.5. Cơ Chế Lọc SKU Ngưng Hoạt Động (Inactive Items Filtering)
Để tránh lãng phí tài nguyên tính toán và không làm méo mó các chỉ số KPI tồn kho, hệ thống áp dụng bộ lọc tự động:
- **Tiêu chuẩn lọc:** Mặt hàng không phát sinh bất kỳ đơn hàng nào trong **$\ge 10$ ngày gần nhất** (`min_days_no_sale = 10`) được xếp vào nhóm ngưng hoạt động / tạm ngừng kinh doanh.
- **Quy mô danh mục:** Lọc từ 5.390 tổng SKU ban đầu $
ightarrow$ **3.602 SKU hoạt động thực tế**.
- **Tính nhất quán dữ liệu 100%:** Bộ lọc này được áp dụng đồng bộ xuyên suốt từ Data Pipeline, API `/forecast/get_forecast_14d`, Bảng Dashboard UI, tệp CSV xuất bổ sung hàng cho đến Báo cáo quản trị PDF.

---

## 5. Deep-Dive: SKU Assistant & Hệ Thống Agent AI (LLM Agent & Tools)

### 5.1. Kiến Trúc ReAct Agent & Streaming SSE
SKU Assistant được xây dựng trên nền tảng LangChain theo mẫu thiết kế **ReAct (Reasoning + Acting)**:
1. Nhận câu hỏi người dùng kèm ngữ cảnh (ví dụ SKU đang chọn trên màn hình).
2. Mô hình suy luận (Thought): Cần lấy dữ liệu gì để trả lời?
3. Ra quyết định hành động (Action): Chọn gọi một Tool trong danh sách.
4. Nhận kết quả từ Tool (Observation).
5. Trả lời người dùng bằng ngôn ngữ tự nhiên, súc tích và có căn cứ số liệu.

Tất cả các bước trên được stream trực tiếp về trình duyệt qua giao thức **Server-Sent Events (SSE)** tại endpoint:
`POST /api/v1/chat/stream`

#### Cấu Trúc Sự Kiện SSE:
Mỗi gói tin SSE mang một dòng `data: {"type": ...}\n\n`:
- `agent_thought`: Bộc lộ suy nghĩ của Agent (hiển thị hiệu ứng mờ trên UI).
- `tool_start`: Báo hiệu Agent bắt đầu gọi công cụ (ví dụ: `get_sku_inventory_and_forecast`).
- `tool_end`: Báo hiệu công cụ đã hoàn thành xử lý.
- `content_chunk`: Từng mảnh văn bản phản hồi được sinh ra theo thời gian thực (hiệu ứng gõ chữ).
- `done`: Báo hiệu kết thúc lượt hội thoại.

### 5.2. Danh Sách 9 Công Cụ Nghiệp Vụ Cốt Lõi (Agent Skills & Tools)
Hệ thống trợ lý AI được trang bị 9 kỹ năng chuyên gia được đăng ký chuẩn hóa trong [backend/app/agent/skills.py](../backend/app/agent/skills.py) và [backend/app/agent/tools.py](../backend/app/agent/tools.py):

| Kỹ Năng (Skill) | Tên Tool Function | Chức Năng Nghiệp Vụ Cốt Lõi | Dữ Liệu Đầu Vào |
|---|---|---|---|
| **Skill 1** | `get_sku_inventory_and_forecast` | Tra cứu tồn kho thực tế, dự báo 14 ngày, ROP, Safety Stock, Lead time, Days of Supply và cảnh báo nguy cơ cạn kho | `sku_or_id: str` |
| **Skill 2** | `get_daily_forecast_series` | Chuỗi dự báo hàng ngày 14 ngày, phân tích tốc độ bán, ngày bán đỉnh điểm (Spike) và ngày cạn kiệt tồn kho | `sku_or_id: str` |
| **Skill 3** | `get_sku_shap_drivers` | Bóc tách 4 nhóm động lực TreeSHAP (Lags, Pricing, Promotions, Seasonality) chi phối nhu cầu tăng hay giảm | `sku_or_id: str, day: int` |
| **Skill 4** | `compare_sku_peers` | So sánh thị phần, tỷ trọng tồn kho so với đối thủ cùng ngành hàng và tìm sản phẩm thay thế khi đứt hàng | `sku_or_id: str` |
| **Skill 5** | `get_portfolio_overview` | Báo cáo toàn diện danh mục toàn kho: Số SKU khẩn cấp (Critical), top 3 mặt hàng cần đặt bù và tổng tồn kho | `focus: str` |
| **Skill 6** | `query_inventory_wiki` | Tra cứu định nghĩa Wiki chính thức, công thức tính toán và ngưỡng cảnh báo cho ROP, DOS, Safety Stock, Deadstock | `topic: str` |
| **Skill 7** | `export_replenishment_csv` | Sinh file CSV danh sách đặt hàng an toàn theo công thức kho vận cho một kho cụ thể hoặc toàn bộ kho và trả link tải | `warehouse: str` |
| **Skill 8** | `generate_pdf_report` | Tạo báo cáo PDF điều hành đa trang (Executive English PDF) kèm biểu đồ Donut ngành hàng. **Hiện tại hỗ trợ chính thức loại `overview` (Full Overview)**; 3 loại chuyên biệt (`critical`, `deadstock`, `best_seller`) đang trong quá trình phát triển (In Development). | `focus_area: str, warehouse: str` |
| **Skill 9** | `simulate_demand` | **Mô phỏng biến đổi giá 2 chiều & Độ co giãn doanh thu (Two-Way Price Decision & Elasticity Engine)**: Tái suy luận Ensemble ML khi giảm giá xả hàng (-%) hoặc tăng giá tối ưu doanh thu (+%), đo độ co giãn giá (PED), phân tích Delta R doanh thu 14 ngày, đánh giá giải phóng Deadstock hoặc kéo dài chu kỳ tồn kho (Demand Throttling), tự động phân tích đa kho | `sku_code: str, price_change_percent: float, warehouse: str = ""` |
| **Tiện ích** | `show_clarification_card` | Hiển thị thẻ bấm lựa chọn tương tác trên UI khi câu hỏi mơ hồ, cần chọn SKU hoặc xác nhận tính TreeSHAP | `title, description, options, card_type, sku` |
| **Tiện ích** | `list_warehouses_summary` | Liệt kê danh mục các kho, tổng sản phẩm và phân bổ mạng lưới | `warehouse: str` |

### 5.3. Hệ Thống Slash Commands
Trên thanh nhập liệu của Chat Composer, người dùng có thể gõ dấu gạch chéo `/` để gọi nhanh các lệnh nghiệp vụ:
- **`/simulate`**: Chạy mô phỏng biến đổi giá 2 chiều (Giảm giá xả hàng -% hoặc Tăng giá tối ưu doanh thu +%), đo độ co giãn của cầu (PED), phân tích doanh thu 14 ngày (P x Q), đánh giá cứu Deadstock và cân đối mạng lưới đa kho.
- **`/warehouse`**: Tìm kiếm thông tin và tình trạng tồn kho theo từng kho bãi hoặc mở menu xuất file PDF/CSV.
- **`/reorder`**: Đề xuất kế hoạch đặt hàng bù tồn kho (Replenishment Recommendation) kèm ROP.
- **`/overview`**: Tóm tắt tổng quan sức khỏe toàn bộ danh mục hàng hóa.
- **`/risks`**: Lọc nhanh các mặt hàng có nguy cơ đứt hàng hoặc hàng tồn chết chôn vốn.
- **`/timeline`**: Xem biểu đồ và lịch trình nhu cầu chi tiết 14 ngày tới.
- **`/drivers`**: Bóc tách các yếu tố chi phối dự báo bằng TreeSHAP.
- **`/peers`**: So sánh SKU đang chọn với các đối thủ cùng phân khúc.
- **`/report`**: Sinh và tải file PDF báo cáo quản trị điều hành (Hiện tại hỗ trợ chính thức loại `Full Overview`; các loại `Critical Stockout`, `Deadstock`, `Best Sellers` đang trong quá trình phát triển).
- **`/help`**: Xem hướng dẫn sử dụng các kỹ năng và câu lệnh.

### 5.4. Deep-Dive: Động Cơ Mô Phỏng Biến Đổi Giá 2 Chiều & Đo Độ Co Giãn Doanh Thu (Two-Way Price Decision & Elasticity Engine)

Chức năng mô phỏng giá được phát triển thành **Two-Way Price Decision & Elasticity Engine** toàn diện tại [`backend/app/services/simulation_service.py`](../backend/app/services/simulation_service.py), vận hành theo **Phương án 1: Tái suy luận trực tiếp từ Ensemble ML (Direct Ensemble Re-inference)** kết hợp phân tích tài chính vi mô:

```mermaid
flowchart TD
    UserQuery["Người dùng: 'Nếu tăng giá 15%...' hoặc 'Nếu giảm giá 20%...'"] --> Guard["evaluate_intent_guard (Bypass Disambiguation)"]
    Guard --> Agent["LangChain Agent -> simulate_demand(sku, price_change_percent)"]
    Agent --> Service["simulation_service.simulate_sku_price_change"]
    
    Service --> Detect{"SKU bán tại 1 kho hay Đa kho?"}
    Detect -- "1 Kho" --> Single["Tái suy luận 14 ngày cho 1 SKU"]
    Detect -- "Nhiều Kho" --> Multi["Multi-Warehouse Auto Detection (Mô phỏng cả 4 kho)"]
    
    Single --> FeatureEng{"Kịch bản Giá: Giảm hay Tăng?"}
    Multi --> FeatureEng
    
    FeatureEng -- "Giảm giá (-%)" --> FeatDisc["type_0_discount, max_discount, discounted_price"]
    FeatureEng -- "Tăng giá (+%)" --> FeatIncr["sell_price_main, discounted_price, zero discounts"]
    
    FeatDisc --> Predict["Ensemble ML (LightGBM + XGBoost + CatBoost)"]
    FeatIncr --> Predict
    
    Predict --> Metrics["Tính toán Chỉ số: Nhu cầu (Q), Doanh thu (P x Q), Co giãn (PED), DOS, Tồn dư"]
    Metrics --> Verdict["Nhận định Điều hành BLUF + Bảng Markdown + Khuyến nghị Chuyên sâu"]
    Verdict --> Stream["Stream toàn vẹn bảng Markdown về Chatbox UI"]
```

#### Các thành phần và nguyên lý trọng yếu:
1. **Biến Đổi Giá 2 Chiều (Two-Way Price Decision Space):**
   - **Giảm giá xả hàng (Discounts: -1% đến -90%):** Kích hoạt các tín hiệu giảm giá (`type_0_discount`, `max_discount`, `discounted_price`), đánh giá khả năng dứt điểm tồn kho chết (*Deadstock Clearance*), tính số ngày cần để bán hết tồn kho và ước tính mức chiết khấu tối ưu.
   - **Tăng giá tối ưu doanh thu & Kéo dài chu kỳ tồn kho (Price Increases: +1% đến +150%):** Cập nhật giá bán cơ sở `sell_price_main` và `discounted_price`, triệt tiêu biến khuyến mãi. Hệ thống đánh giá xem liệu tăng giá có giúp mở rộng biên lợi nhuận gộp và tăng tổng doanh thu ($\Delta R \ge 0$), đồng thời kiểm tra khả năng giảm tốc bán (*Demand Throttling*) giúp kéo dài số ngày cung ứng (*DOS Expansion*) để câu giờ chờ lô hàng PO mới cập bến.

2. **Mô Hình Kinh Tế Vi Mô & Phân Tích Độ Co Giãn (Price Elasticity of Demand - PED):**
   - **Doanh thu dự kiến 14 ngày ($P 	imes Q$):**
     $$	ext{Baseline Revenue} = \sum Q_{	ext{base}} 	imes P_{	ext{sell}}, \quad 	ext{Simulated Revenue} = \sum Q_{	ext{sim}} 	imes P_{	ext{new}}$$
     $$\Delta 	ext{Revenue} = 	ext{Simulated Revenue} - 	ext{Baseline Revenue}, \quad \%\Delta R = rac{\Delta 	ext{Revenue}}{	ext{Baseline Revenue}} 	imes 100\%$$
   - **Độ co giãn của cầu theo giá (PED):**
     $$PED = rac{\%\Delta Q}{\%\Delta P} = rac{(Q_{	ext{sim}} - Q_{	ext{base}}) / Q_{	ext{base}}}{(P_{	ext{new}} - P_{	ext{sell}}) / P_{	ext{sell}}}$$
   - **Phân loại độ nhạy cảm giá tự động:**
     - **Co giãn cao (Price Elastic, $|PED| > 1.2$):** Người tiêu dùng cực kỳ nhạy cảm giá; giảm giá kích cầu mạnh mẽ nhưng tăng giá sẽ gây tổn thất doanh thu nghiêm trọng.
     - **Co giãn đơn vị (Unit Elastic, $0.8 \le |PED| \le 1.2$):** Tỷ lệ thay đổi nhu cầu tương đương tỷ lệ thay đổi giá.
     - **Bất co giãn (Inelastic, $|PED| < 0.8$):** Mặt hàng thiết yếu (như thực phẩm, bánh mì); tăng giá chỉ làm giảm nhẹ sức mua và trực tiếp thúc đẩy tổng doanh thu tăng trưởng vượt bậc.

3. **Multi-Warehouse Network Rebalancing & Stock Transfer:**
   Khi sản phẩm hiện diện ở nhiều kho (như `Baguette_40` ở 4 kho), hệ thống mô phỏng song song toàn mạng lưới và lập bảng so sánh chi tiết:
   - Tổng hợp doanh thu, lượng cầu thay đổi, và độ co giãn theo từng trung tâm phân phối.
   - Phát hiện hiện tượng lệch pha cung - cầu vùng (ví dụ: kho `Brno_1` và `Prague_1` dư thừa hàng chục nghìn cái trong khi `Prague_2` và `Prague_3` cháy hàng cạn kho).
   - Đưa ra khuyến nghị điều phối điều chuyển kho nội bộ (*Inter-Warehouse Stock Transfer*) trước khi triển khai chiến dịch.

4. **Intent Guard & Prompt Rule 13:**
   - [backend/app/agent/fallback.py](../backend/app/agent/fallback.py): Bộ lọc Intent Guard nhận diện các từ khóa tăng/giảm giá, độ co giãn, xả hàng (`giảm`, `tăng`, `tăng giá`, `co giãn`, `elasticity`, `what-if`, `discount`, `deadstock`) để trực tiếp chuyển vào Agent, không ngắt quãng người dùng bằng menu chọn rời rạc.
   - [backend/app/agent/sku_agent.py](../backend/app/agent/sku_agent.py): Rule 13 bắt buộc Agent phải duy trì 100% định dạng bảng Markdown so sánh kịch bản, các chỉ số PED, doanh thu, tồn kho và các khuyến nghị chuyên sâu mà không được tóm tắt sơ sài.

---

## 6. Deep-Dive: Cơ Sở Dữ Liệu & Lưu Trữ Phiên (Database & Persistence)

### 6.1. Thiết Kế Hai Phân Vùng Schema (`core` vs `raw`)
Để đảm bảo nguyên tắc kiến trúc dữ liệu sạch (Clean Architecture), database được chia thành 2 schema riêng biệt:

```
PostgreSQL Database (demand_ai)
├── schema "raw"    (Dữ liệu thô, bất biến từ quá trình ETL Ingestion)
│   ├── raw.sales_train          # Lịch sử bán lẻ từng giao dịch
│   ├── raw.inventory            # Bản ghi kiểm kê kho định kỳ
│   ├── raw.calendar             # Dữ liệu ngày lễ, sự kiện, thời tiết
│   ├── raw.test_weights         # Trọng số tính điểm benchmark
│   └── raw.ingestion_log        # Nhật ký kiểm toán các lượt nạp dữ liệu
│
└── schema "core"   (Dữ liệu kinh doanh đã qua xử lý & kết quả phân tích)
    ├── core.dim_items           # Danh mục 3.602 SKU chuẩn hóa
    ├── core.dim_stores          # Danh sách cửa hàng
    ├── core.dim_warehouses      # Danh sách trung tâm phân phối (Kho)
    ├── core.fact_sales_daily    # Bảng tổng hợp doanh số ngày
    ├── core.forecast_runs       # Lưu metadata từng phiên dự báo
    └── core.forecast_records    # Lưu chi tiết 14 ngày dự báo cho từng SKU
```

### 6.2. Quy Tắc Vàng: Async Session vs Sync Session trong SQLAlchemy 2.0

> [!WARNING]
> **Quy Tắc Sống Còn Cho Developer**:
> - Trong các **FastAPI Endpoint bất đồng bộ (`async def`)**: Luôn sử dụng `Depends(get_async_db)`. Engine là `asyncpg`. Tuyệt đối không gọi các hàm I/O chặn (blocking I/O).
> - Trong các **Scripts, Alembic Migrations, Worker Threads nền hoặc Data Pipeline (`def`)**: Sử dụng `SessionLocal` (Sync session). Engine là `psycopg2`.
> - *Không bao giờ chia sẻ đối tượng Session giữa các luồng (threads) khác nhau!*

Ví dụ chuẩn trong API Route:
```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_async_db
from app.models.core.tables import DimItem

router = APIRouter()

@router.get("/my-items")
async def read_items(db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(DimItem).limit(10))
    return result.scalars().all()
```

### 6.3. Quản Trị Migration Bằng Alembic
Mỗi khi bạn thay đổi một Model trong thư mục `backend/app/models/`, bạn cần tạo một migration script để đồng bộ cấu trúc bảng:

```bash
# Bước 1: Sinh file migration tự động từ schema model
cd backend
.venv/bin/alembic revision --autogenerate -m "add_reorder_point_to_dim_items"

# Bước 2: Kiểm tra file vừa sinh ra trong thư mục backend/alembic/versions/
# Bước 3: Áp dụng migration lên database
.venv/bin/alembic upgrade head

# Nếu cần rollback lại 1 phiên bản:
.venv/bin/alembic downgrade -1
```

---

## 7. Deep-Dive: Giao Diện Người Dùng (Frontend Architecture & Canvas)

### 7.1. Cấu Trúc Thành Phần Giao Diện (Component Hierarchy)

```text
DemandAIShell (Quản lý State: runId, activeItem, chatHistory, sseStatus)
├── DemandAIHeader (Hiển thị Status Badge, nút Run Forecast, nút Save Forecast)
└── Main Content (Chia làm 3 khu vực linh hoạt)
    ├── LeftPanel (Biểu đồ phân tích)
    │   ├── DailyForecastLineChart (Vẽ đường xu hướng doanh số 14 ngày tới)
    │   └── TreeShapComputingVisualizer (Biểu đồ cột ngang SHAP Waterfall 4 nhóm)
    ├── WorkspaceCanvas (Không gian làm việc trung tâm)
    │   ├── ForecastStatusBadge (Báo trạng thái phiên: In-Memory / Saved RDS)
    │   └── ForecastTable (Bảng dữ liệu 3.602 SKU, hỗ trợ sort/filter/search)
    └── ChatPanel (Trợ lý ảo thông minh)
        ├── ChatMessages (Hiển thị tin nhắn dạng Markdown, khối code, thẻ báo cáo)
        └── ChatComposer (Thanh input, tự động nhận diện slash commands)
```

### 7.2. Xử Lý Luồng Streaming SSE Phía Client
File [frontend/src/lib/chatApi.ts](../frontend/src/lib/chatApi.ts) xử lý việc kết nối tới backend bằng `fetch` với `ReadableStream`:

```typescript
// Cơ chế đọc từng chunk SSE an toàn không bị cắt đứt dòng:
const response = await fetch(`${API_URL}/api/v1/chat/stream`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ message, current_sku: activeSku }),
});

const reader = response.body?.getReader();
const decoder = new TextDecoder();
let buffer = '';

while (true) {
  const { value, done } = await reader.read();
  if (done) break;
  buffer += decoder.decode(value, { stream: true });
  
  // Tách dòng theo chuẩn SSE: \n\n
  const lines = buffer.split('\n\n');
  buffer = lines.pop() || ''; // Giữ lại phần dư chưa hoàn thiện
  
  for (const block of lines) {
    if (block.startsWith('data: ')) {
      const payload = JSON.parse(block.slice(6));
      onEvent(payload); // Dispatch cập nhật React State
    }
  }
}
```

---

## 8. Cookbook: Cẩm Nang Thực Hành Cho Developer (Step-by-Step Practical Recipes)

### Recipe 1: Thêm Một Agent Tool Mới
*Giả sử bạn cần tạo tool `check_lead_time(supplier_id)` để tra cứu thời gian giao hàng của nhà cung ứng.*

**Bước 1**: Mở file [backend/app/agent/tools.py](../backend/app/agent/tools.py), định nghĩa hàm xử lý nghiệp vụ:
```python
def check_supplier_lead_time(supplier_id: str) -> str:
    """Tra cứu thời gian đặt hàng (lead time) dự kiến của nhà cung cấp tính theo số ngày."""
    # Logic tra cứu database hoặc tính toán nghiệp vụ
    lead_days = 7 # Giả định trả về 7 ngày
    return f"Nhà cung cấp {supplier_id} có thời gian giao hàng tiêu chuẩn là {lead_days} ngày."
```

**Bước 2**: Đóng gói thành LangChain Tool và thêm vào danh sách công cụ được cấp quyền cho Agent:
```python
from langchain.tools import Tool

supplier_lead_time_tool = Tool(
    name="check_supplier_lead_time",
    func=check_supplier_lead_time,
    description="Hữu ích khi cần kiểm tra số ngày giao hàng dự kiến của nhà cung cấp."
)

# Thêm vào mảng AGENT_TOOLS:
AGENT_TOOLS.append(supplier_lead_time_tool)
```

---

### Recipe 2: Thêm Một Slash Command Mới Trên Chat Composer
*Giả sử bạn muốn thêm lệnh `/supplier` để người dùng tra cứu nhanh nhà cung ứng.*

**Bước 1**: Mở file [frontend/src/components/chat/ChatComposer.tsx](../frontend/src/components/chat/ChatComposer.tsx).
Tìm mảng `SLASH_COMMANDS` và thêm lệnh mới:
```typescript
{
  command: '/supplier',
  label: '/supplier [mã]',
  description: 'Tra cứu thông tin nhà cung cấp và thời gian giao hàng',
  template: 'Kiểm tra thông tin và thời gian giao hàng của nhà cung cấp: ',
}
```

**Bước 2**: Trong [backend/app/agent/skills.py](../backend/app/agent/skills.py), bổ sung phân loại intent cho `/supplier` để điều hướng chính xác vào tool vừa tạo.

---

### Recipe 3: Thêm Một API Endpoint Mới Trong FastAPI
*Giả sử bạn muốn tạo endpoint `GET /api/v1/forecast/summary-stats`.*

**Bước 1**: Mở file [backend/app/api/routes/forecast.py](../backend/app/api/routes/forecast.py).  
Định nghĩa Pydantic schema phản hồi và route:
```python
from pydantic import BaseModel

class SummaryStatsResponse(BaseModel):
    total_skus: int
    critical_stock_count: int
    average_daily_demand: float

@router.get(
    "/summary-stats",
    response_model=SummaryStatsResponse,
    summary="Get High-level Forecast Summary Statistics"
)
async def get_summary_statistics(
    db: AsyncSession = Depends(get_async_db)
):
    """Tính toán nhanh các chỉ số tóm tắt của danh mục hàng hóa."""
    # Thực hiện câu lệnh truy vấn
    return SummaryStatsResponse(
        total_skus=3602,
        critical_stock_count=42,
        average_daily_demand=128.5
    )
```

**Bước 2**: Swagger UI tại `http://localhost:8000/docs` sẽ tự động cập nhật endpoint mới này kèm đầy đủ tài liệu và giao diện test tương tác.

---

### Recipe 4: Tạo Và Chạy Database Migration Với Alembic
Khi cần thêm một trường dữ liệu (ví dụ: `reorder_threshold`) vào bảng `core.dim_items`:

1. Khai báo thuộc tính mới trong model:
   Mở [backend/app/models/core/tables.py](../backend/app/models/core/tables.py):
   ```python
   reorder_threshold: Mapped[int | None] = mapped_column(Integer, default=50)
   ```
2. Mở terminal và chạy lệnh sinh migration:
   ```bash
   cd backend
   .venv/bin/alembic revision --autogenerate -m "add_reorder_threshold_to_dim_items"
   ```
3. Xem lại file mới trong `backend/alembic/versions/` để chắc chắn mã Python chính xác.
4. Chạy migration:
   ```bash
   .venv/bin/alembic upgrade head
   ```

---

### Recipe 5: Đồng Bộ & Kiểm Thử Swagger OpenAPI Khi Thêm Hoặc Cập Nhật API Endpoint
Để đảm bảo Swagger UI tại `http://localhost:8000/docs` và trang nhúng `http://localhost:3000/docs` luôn đạt chuẩn chất lượng cao nhất:

1. **Khai báo Pydantic Schema đúng chuẩn Pydantic v2**:
   Luôn sử dụng `Field(..., description="...", examples=[...])` thay vì `example=...` (tránh deprecation warning):
   ```python
   class SimulationRequest(BaseModel):
       sku_code: str = Field(..., description="Mã SKU hoặc tên sản phẩm", examples=["Baguette_40"])
       price_change_percent: float = Field(default=-20.0, ge=-90.0, le=150.0, description="Tỷ lệ biến động giá (-% giảm, +% tăng)", examples=[15.0])
   ```

2. **Khai báo đầy đủ Metadata cho Route**:
   Cung cấp `summary`, `description`, và `response_description` rõ ràng:
   ```python
   @router.post(
       "/simulate",
       summary="Run What-If Demand & Two-Way Price Simulation",
       description="Tái suy luận Ensemble ML 14 ngày, đo độ co giãn PED và doanh thu.",
       response_description="Kết quả mô phỏng và báo cáo markdown chi tiết.",
   )
   def run_simulation(req: SimulationRequest) -> dict[str, Any]:
       ...
   ```

3. **Đồng bộ File Fallback Schema cho Frontend**:
   Khi bổ sung hoặc thay đổi endpoint, chạy lệnh sau để cập nhật file tĩnh fallback:
   ```bash
   backend/.venv/bin/python -c "from app.main import app; import json; json.dump(app.openapi(), open('frontend/src/lib/openapi-fallback.json', 'w'), indent=2, ensure_ascii=False)"
   ```

4. **Kiểm thử tự động tính toàn vẹn Swagger**:
   ```bash
   backend/.venv/bin/pytest backend/tests/test_openapi_swagger.py -v
   ```

---

## 9. Kiểm Thử & Tiêu Chuẩn Chất Lượng Mã Nguồn (Testing & Quality Assurance)

### 9.1. Chạy Bộ Kiểm Thử Backend (Pytest)
Hệ thống backend đã được thiết lập bộ kiểm thử toàn diện với hơn 98 test cases, bao gồm:
- Kiểm thử các API Endpoints (FastAPI TestClient)
- Kiểm thử logic phân giải SKU và các công cụ Agent Tools
- Kiểm thử khả năng phục hồi đường dẫn (Path Resilience)
- Kiểm thử tính toán SHAP và sinh báo cáo PDF

Cách chạy test:
```bash
# Chạy toàn bộ test suite
backend/.venv/bin/pytest backend/tests/ -q

# Chạy kiểm thử What-If Demand Simulation (14 tests):
backend/.venv/bin/pytest backend/tests/test_simulation.py -v

# Chạy kiểm thử OpenAPI & Swagger API Docs parity (6 tests):
backend/.venv/bin/pytest backend/tests/test_openapi_swagger.py -v

# Chạy kiểm thử xuất Báo Cáo PDF Điều Hành & File CSV Đặt Hàng (22 tests):
backend/.venv/bin/pytest backend/tests/test_pdf_report.py backend/tests/test_export_replenishment.py -v

# Chạy kiểm thử Recursive Ensemble Predictor (14 tests):
backend/.venv/bin/pytest backend/tests/test_recursive_ensemble.py -v

# Chạy thực nghiệm kiểm thử độ tái lập tất định 5 lượt chạy (Strict Determinism):
backend/.venv/bin/python backend/scripts/test_reproducibility_5runs.py
```

### 9.2. Chạy Kiểm Thử Frontend & TypeScript Typecheck
```bash
# Kiểm tra định kiểu TypeScript toàn bộ dự án
npm --prefix frontend run typecheck

# Chạy bộ test kiểm tra API timeout & xử lý lỗi mạng
npm --prefix frontend test

# Chạy build thử nghiệm sản phẩm hoàn chỉnh
npm --prefix frontend run build
```

### 9.3. Tiêu Chuẩn Viết Docstrings (Theo Chuẩn `code-documenter`)
Khi viết hàm hoặc class mới trong backend, bạn **bắt buộc** phải tuân thủ chuẩn **Google-style docstring**:
```python
def calculate_reorder_quantity(current_stock: int, forecasted_demand: float, safety_stock: int = 20) -> int:
    """Tính toán số lượng hàng cần đặt bổ sung dựa trên tồn kho và nhu cầu dự báo.

    Args:
        current_stock: Số lượng đơn vị sản phẩm hiện còn trong kho.
        forecasted_demand: Tổng nhu cầu dự báo trong chu kỳ bổ sung hàng.
        safety_stock: Lượng tồn kho an toàn tối thiểu quy định (mặc định: 20).

    Returns:
        Số lượng đơn vị hàng khuyến nghị cần đặt thêm (luôn >= 0).

    Raises:
        ValueError: Nếu current_stock hoặc safety_stock là số âm.
    """
    if current_stock < 0 or safety_stock < 0:
        raise ValueError("Stock values cannot be negative")
    
    needed = int(forecasted_demand + safety_stock - current_stock)
    return max(0, needed)
```

---

## 10. Lỗi Thường Gặp & Cẩm Nang Khắc Phục (Troubleshooting & FAQs)

### 10.1. Lỗi Thường Gặp (Common Gotchas)

#### ⚠️ Gotcha 1: Bẫy Symlink Workspace Trên Linux
- **Triệu chứng**: Khi dùng IDE hoặc công cụ AI đọc file, xuất hiện lỗi `Permission denied` hoặc đường dẫn bị biến thành `/home/intern-cqvinh1/Desktop/DemandAIApplication`.
- **Nguyên nhân**: Thư mục `/home/intern-cqvinh1/Desktop/backend` thực chất là một symbolic link trỏ về `DemandAIApplication`.
- **Giải pháp**: Trong mã nguồn Python, luôn sử dụng `pathlib.Path(__file__).resolve().parent` để lấy đường dẫn tuyệt đối chuẩn xác theo file vật lý thay vì hard-code chuỗi đường dẫn.

#### ⚠️ Gotcha 2: Lỗi "InterfaceError: cannot perform operation: another operation is in progress"
- **Triệu chứng**: Xuất hiện khi gọi nhiều câu lệnh SQL trong cùng một route async.
- **Nguyên nhân**: Dùng chung một kết nối `asyncpg` cho hai câu lệnh chạy đồng thời (`asyncio.gather`) mà không đợi tuần tự.
- **Giải pháp**: Luôn gọi `await db.execute(...)` tuần tự, hoặc nếu muốn chạy song song thì phải mở các session độc lập.

#### ⚠️ Gotcha 3: Hiện Tượng SSE Bị Chặn Hoặc Giật Cục (Buffering)
- **Triệu chứng**: Giao diện chat không hiển thị hiệu ứng gõ chữ từng từ mà đợi cả câu xong mới bung ra một lần.
- **Nguyên nhân**: Proxy trung gian (Nginx) hoặc buffer của trình duyệt tích trữ dữ liệu trước khi xả ra.
- **Giải pháp**: Header của FastAPI `StreamingResponse` bắt buộc phải có:
  ```python
  headers={
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no"
  }
  ```

#### ⚠️ Gotcha 4: Chế Độ Fallback Khi Không Có Khóa OpenAI
- **Triệu chứng**: Hệ thống vẫn trả lời các câu hỏi về SKU, nhưng không có khả năng đàm thoại tự do.
- **Giải thích**: Đây là tính năng dự phòng an toàn (Resilience Fallback). Khi biến `OPENAI_API_KEY` bị thiếu hoặc không hợp lệ, hệ thống tự kích hoạt `app/agent/fallback.py` để phân tích bằng biểu thức chính quy (Regex) và gọi trực tiếp các tool nghiệp vụ, đảm bảo hệ thống không bao giờ bị sập (Crash).

---

### 10.2. Câu Hỏi Thường Gặp (Intern/Fresher FAQ)

**Q1: Khi chạy `make dev` bị báo cổng 8000 hoặc 3000 đang được sử dụng, tôi phải làm sao?**  
*Trả lời*: Kiểm tra xem có tiến trình nào đang chạy ngầm bằng lệnh:
```bash
lsof -i :8000
lsof -i :3000
# Dừng tiến trình cũ:
kill -9 <PID>
```

**Q2: Dữ liệu dự báo 14 ngày có tự động mất đi khi tắt server không?**  
*Trả lời*: Nếu bạn chưa bấm nút **"Save Forecast"**, phiên dự báo nằm trong bộ nhớ RAM và file cache tạm trong `data/cache/`. Khi server restart hoặc qua ngày mới, cache có thể hết hạn. Khi bạn bấm **"Save Forecast"**, toàn bộ số liệu được ghi vĩnh viễn vào các bảng `core.forecast_runs` và `core.forecast_records` trên database PostgreSQL.

**Q3: Tôi muốn thêm một cột mới vào bảng hiển thị trên Canvas Workspace thì sửa ở đâu?**  
*Trả lời*: Bạn cần sửa ở 2 nơi:
1. File kiểu dữ liệu: [frontend/src/types/forecast.ts](../frontend/src/types/forecast.ts) (Thêm thuộc tính vào interface `ForecastRow`).
2. File giao diện bảng: [frontend/src/components/workspace/ForecastTable.tsx](../frontend/src/components/workspace/ForecastTable.tsx) (Thêm thẻ `<th>` ở header và thẻ `<td>` tương ứng trong vòng lặp render dòng).

---
*DemandAI Engineering Team • Last updated: 2026*
