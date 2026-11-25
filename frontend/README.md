# DemandAI — Frontend Application

Giao diện người dùng hiện đại cho hệ thống dự báo nhu cầu bán lẻ (**DemandAI**), xây dựng bằng **Next.js 16 (App Router)**, **React 19**, **TypeScript** và **Tailwind CSS**.

---

## Cấu trúc thư mục (`src/`)

```
src/
├── app/                  # Next.js App Router (Routing, Layouts, Pages)
│   ├── layout.tsx        # Root layout (Metadata, Google Fonts)
│   ├── page.tsx          # Trang chủ: Forecast Workspace & AI Assistant Shell
│   ├── globals.css       # Global CSS & Tailwind configuration
│   └── health/           # Trang kiểm tra kết nối Backend & System Status
├── components/           # UI Components chia theo Domain
│   ├── common/           # Các component dùng chung (Header, Icons)
│   ├── workspace/        # Khu vực Forecast Workspace Canvas
│   ├── chat/             # Phân hệ AI Assistant (Panel, Messages, Composer)
│   └── DemandAIShell.tsx # Shell Orchestrator điều phối Workspace và Chat
├── styles/               # Stylesheets chuyên biệt
│   └── demand-ai.css     # CSS layout, hiệu ứng chuyển động & responsive
├── types/                # TypeScript Interfaces & Types tập trung
│   ├── chat.ts           # Types cho chat & messages
│   └── health.ts         # Types cho API health check
└── lib/                  # Utilities & API Client
    └── api.ts            # Client giao tiếp với FastAPI Backend
```

---

## Các lệnh khả dụng (Scripts)

| Lệnh | Mục đích |
| :--- | :--- |
| `npm run dev` | Khởi chạy máy chủ phát triển (mặc định tại `http://localhost:3000`) |
| `npm run build` | Tạo production bundle tối ưu hóa bằng Turbopack |
| `npm start` | Chạy ứng dụng production đã build |
| `npm run typecheck` | Kiểm tra tính hợp lệ của TypeScript (`tsc --noEmit`) |
| `npm run lint` | Chạy ESLint kiểm tra quy chuẩn mã nguồn |
| `npm test` | Chạy kiểm thử tự động API timeout & error handling (`test-api-timeout.mjs`) |

---

## Biến môi trường (Environment Variables)

File `.env.local` hoặc cấu hình hệ thống:

```env
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

## Live Run Forecast progress

The forecast workspace starts one backend job and observes its four real stages.
Stage statuses and messages come from SSE snapshots, with status polling to
recover interrupted streams. The progress bar counts completed stages; it is
not an estimate of elapsed processing time. A failed stage is shown explicitly,
with later stages still pending and a retry action.

The current request/job IDs are kept in `sessionStorage` so reloading the same
tab resumes monitoring. Retrying a connection or results-download failure
reattaches to that job; retrying a failed pipeline starts a new job. Results are
loaded in pages of 500 items from the completed job's `run_id`, including when
loading an item's SHAP details. No mock forecasts are displayed.

The backend must have the three trained model binaries documented in
[`backend/README.md`](../backend/README.md). Missing models are reported at stage 3.

```bash
node --test tests/forecast-api.test.cjs
```

### Forecast readiness and SHAP

The fourth stage now saves inventory analysis and forecast results, without
waiting for SHAP. The table shows **Forecast ready · SHAP on demand**. Opening
an item starts/reuses its SHAP job and polls status without blocking the table.
Switching items cancels the old client poll; the backend finishes its work and
caches it by run and item. Returning to a completed item reuses the result.
A SHAP error appears in the details panel with **Retry SHAP**, while forecasts
remain available. Breakdown and daily driver charts no longer synthesize
missing feature contributions.
