"""app.agent.skills — DemandAI Assistant Skill System & Query Intent Router."""
from __future__ import annotations

from typing import Any



SKILLS: dict[str, dict[str, Any]] = {
    "metrics_definition": {
        "id": "metrics_definition",
        "name_vi": "Tra cứu Định nghĩa Wiki & Chỉ số On-Demand",
        "name_en": "On-Demand Wiki Definitions & Metrics",
        "tool": "query_inventory_wiki",
        "keywords_vi": ["nghĩa là gì", "con số", "là gì", "giải thích", "công thức", "tính bằng", "rop", "safety stock", "deadstock", "days of supply", "monitor", "critical", "reorder", "treeshap +", "độ lệch", "wiki"],
        "keywords_en": ["what does this number mean", "explain rop", "formula", "safety buffer", "deadstock mean", "days of supply", "difference between monitor", "treeshap +", "wiki", "definition"],
    },
    "inventory_replenishment": {
        "id": "inventory_replenishment",
        "name_vi": "Quản trị Tồn kho & Quyết định Đặt hàng (PO)",
        "name_en": "Inventory Health & Replenishment Actions",
        "tool": "get_sku_inventory_and_forecast",
        "keywords_vi": ["đứt hàng", "hết hàng", "hàng tồn", "bao nhiêu ngày nữa", "lead time", "tạo đơn", "đặt hàng", "po", "chạm mức 0", "đặt thêm", "thừa", "thiếu", "chênh lệch", "safety stock", "rop"],
        "keywords_en": ["stockout", "run out", "days of supply", "lead time", "reorder", "purchase order", "reach 0", "replenish", "how many units", "safety buffer"],
    },
    "daily_timeline": {
        "id": "daily_timeline",
        "name_vi": "Lịch trình Dự báo Từng Ngày & Điểm rơi Cao điểm",
        "name_en": "Daily Forecast Timeline & Demand Velocity Spikes",
        "tool": "get_daily_forecast_series",
        "keywords_vi": ["thứ ba", "thứ hai", "thứ tư", "thứ năm", "thứ sáu", "thứ bảy", "chủ nhật", "tuần sau", "ngày mai", "ngày kia", "cuối tuần", "đột biến", "cao nhất", "từng ngày", "khuyến mãi ngày đôi", "tuần đầu tiên", "vượt quá tồn kho"],
        "keywords_en": ["tuesday", "monday", "wednesday", "thursday", "friday", "saturday", "sunday", "next week", "tomorrow", "weekend", "spike", "peak day", "day by day", "timeline", "running depletion"],
    },
    "treeshap_drivers": {
        "id": "treeshap_drivers",
        "name_vi": "Phân tích Động lực Dự báo TreeSHAP (Nguyên nhân)",
        "name_en": "TreeSHAP Root-Cause Drivers & Explainability",
        "tool": "get_sku_shap_drivers",
        "keywords_vi": ["tại sao", "nguyên nhân", "kéo tụt", "tụt", "giảm giá", "đóng góp", "mùa vụ", "giá bán", "hết hạn khuyến mãi", "sales momentum", "yếu tố", "tác động", "ảnh hưởng", "shap", "driver"],
        "keywords_en": ["why", "root cause", "drag", "pull down", "discount contribute", "seasonality", "price elasticity", "promotion end", "sales momentum", "drivers", "factor"],
    },
    "category_peers": {
        "id": "category_peers",
        "name_vi": "So sánh Ngành hàng & Sản phẩm Thay thế",
        "name_en": "Category Peer Ranking & Substitutes",
        "tool": "compare_sku_peers",
        "keywords_vi": ["đứng thứ mấy", "doanh số", "cùng ngành", "cùng phân khúc", "thay thế", "gấp mấy lần", "trung bình", "đối thủ", "peer", "cannibalization"],
        "keywords_en": ["rank", "position", "peers", "same category", "substitute", "average", "competitor", "market share"],
    },
    "portfolio_overview": {
        "id": "portfolio_overview",
        "name_vi": "Bức tranh Toàn cảnh Kho (Danh mục)",
        "name_en": "Portfolio-wide Overview & Prioritization",
        "tool": "get_portfolio_overview",
        "keywords_vi": ["toàn bộ kho", "bao nhiêu mã", "top 3", "tổng lượng", "tỷ trọng", "bán chậm", "kho hiện có", "ưu tiên", "danh mục", "/overview"],
        "keywords_en": ["portfolio", "warehouse", "how many items", "critical skus", "top 3", "total stock", "slow moving", "all items", "overview"],
    },
    "core_metadata": {
        "id": "core_metadata",
        "name_vi": "Thông tin Phân cấp L1-L4 & Kho bãi",
        "name_en": "Core Item Metadata & Hierarchy",
        "tool": "get_sku_core_info",
        "keywords_vi": ["thông tin", "kho nào", "phân cấp", "vị trí kho", "hạn sử dụng", "shelf life"],
        "keywords_en": ["hierarchy", "which warehouse", "shelf life", "l1", "l2", "core info"],
    },
    "export_replenishment": {
        "id": "export_replenishment",
        "name_vi": "Xuất File CSV Đề Xuất Nhập Hàng",
        "name_en": "Export Replenishment CSV",
        "tool": "export_replenishment_csv",
        "keywords_vi": ["file csv", "export csv", "tải csv", "xuất csv", "tạo csv", "tải file csv", "xuất file csv"],
        "keywords_en": ["export csv", "download csv", "generate csv", "replenishment csv", "reorder csv", "csv file"],
    },
    "generate_pdf_report": {
        "id": "generate_pdf_report",
        "name_vi": "Tạo Báo Cáo PDF Đa Trang Có Biểu Đồ",
        "name_en": "Generate Multi-Page PDF Report",
        "tool": "generate_pdf_report",
        "keywords_vi": ["báo cáo pdf", "tạo pdf", "file pdf", "report pdf", "xuất pdf", "tải pdf", "xuất báo cáo pdf", "tạo file pdf"],
        "keywords_en": ["pdf report", "generate pdf", "export pdf", "download pdf", "pdf file", "create pdf"],
    },
    "warehouse_management": {
        "id": "warehouse_management",
        "name_vi": "Tra Cứu Kho Hàng & Xuất Báo Cáo / File CSV Theo Kho",
        "name_en": "Warehouse Lookup & Targeted PDF/CSV Export",
        "tool": "list_warehouses_summary",
        "keywords_vi": ["/warehouse", "tìm kho", "kho hàng", "danh sách kho", "kho nào", "các kho hiện có", "chọn kho"],
        "keywords_en": ["/warehouse", "warehouse", "find warehouse", "which warehouse", "search warehouse", "warehouse list"],
    },
    "what_if_simulation": {
        "id": "what_if_simulation",
        "name_vi": "Mô phỏng Kịch bản Giả lập (What-If Demand Simulation)",
        "name_en": "What-If Scenario Simulation (Discounts & Interventions)",
        "tool": "simulate_demand",
        "keywords_vi": ["giảm giá", "nếu giảm", "mô phỏng", "giả lập", "what-if", "giảm 20%", "giảm 10%", "giảm 30%", "giảm 50%", "tăng giá", "cứu deadstock", "cứu được tình trạng deadstock", "cứu được deadstock", "xả hàng", "hạ giá", "khuyến mãi", "kịch bản"],
        "keywords_en": ["simulate", "what if", "discount", "price drop", "promotion", "clear deadstock", "rescue deadstock", "if we reduce", "price sensitivity", "scenario"],
    },
}


def match_skill(query: str) -> dict[str, Any] | None:
    clean = query.strip().lower()

    best_match = None
    max_matches = 0

    for skill in SKILLS.values():
        matches = (
            sum(1 for kw in skill["keywords_vi"] if kw in clean) +
            sum(1 for kw in skill["keywords_en"] if kw in clean)
        )

        if matches > max_matches:
            max_matches = matches
            best_match = skill
            

    return best_match



def get_skills_system_prompt(lang: str = "vi") -> str:
    """Produce structured, task-driven skill guides synthesized from time-series and data analysis best practices."""
    if lang == "vi":
        return """LUỒNG TƯ DUY PHÂN TÍCH DỮ LIỆU & Ý ĐỊNH VẬN HÀNH (DATA ANALYTICS & REASONING FRAMEWORK):
Áp dụng phương pháp phân tích chuẩn quốc tế: Trả lời theo mô hình [Kết luận trước (BLUF) → Dữ liệu (Finding) → Ý nghĩa kinh doanh (So What) → Nguyên nhân gốc rễ (Why) → Hành động cụ thể (Now What)]:

1. "Ý định thực sự là gì?" (Underlying Operational Intent):
   - Đặt hàng & Cạn kho (`/reorder` hoặc hỏi: "hàng còn đủ không?", "có đứt hàng không?", "khi nào nhập thêm?", "cần đặt bao nhiêu?"): Xác định Days of Supply (DOS), nguy cơ đứt hàng trước Lead Time, và đề xuất số lượng PO chính xác hôm nay.
   - Chuỗi thời gian & Điểm rơi (`/timeline` hoặc hỏi: "bán ra sao?", "ngày nào bán chạy nhất?", "cuối tuần thế nào?", "khi nào cạn sạch hàng?"): Phân tích quy luật chuỗi thời gian, ngày đỉnh điểm (Peak Day), mùa vụ ngày trong tuần, và ngày kho cạn sạch (Runout Day).
   - Động lực & Nguyên nhân (`/drivers` hoặc hỏi: "tại sao dự báo lại tăng/giảm?", "nguyên nhân do đâu?", "giảm giá ảnh hưởng thế nào?"): BẮT BUỘC gọi `get_sku_shap_drivers` để tìm nguyên nhân gốc rễ (Root Cause: giá bán, khuyến mãi, mùa vụ, momentum).
   - Báo cáo Toàn diện (`/report` hoặc hỏi: "báo cáo tình hình mặt hàng này", "tóm tắt điều hành"): Khi người dùng yêu cầu báo cáo mà thiếu tham số hoặc chưa rõ định dạng, áp dụng Khung tư duy tham số công cụ (tuyệt đối không tự ý xuất file PDF overview, bỏ qua hỏi định dạng nếu đã nêu rõ PDF/CSV, và gọi `show_clarification_card` với lựa chọn Full Overview hoặc kho phù hợp (lưu ý các loại báo cáo critical, deadstock, best_seller đang trong quá trình phát triển nên không cung cấp)). Khi phân tích một mặt hàng cụ thể trong chat, lập báo cáo 4 phần: Tổng quan chỉ số, Chuỗi thời gian & điểm rơi, Động lực TreeSHAP, và Khuyến nghị hành động kho vận.
   - Rà soát Rủi ro (`/risks` hoặc hỏi: "có rủi ro gì không?", "món nào sắp hết hàng?"): Rà soát SKU khẩn cấp (hàng về 0, thiếu hàng diện rộng, hoặc Deadstock chôn vốn).
   - So sánh Ngành hàng (`/peers` hoặc hỏi: "so với các món khác thế nào?", "món nào thay thế được?"): So sánh thị phần, vị thế doanh số và tìm sản phẩm thay thế khi đứt hàng.
   - Tra cứu Kho & Xuất báo cáo theo kho (`/warehouse` hoặc hỏi: "danh sách kho", "tìm kho", "kho nào cần nhập?"): Khi người dùng yêu cầu xuất báo cáo có kèm định dạng rõ ràng (ví dụ: `/warehouse Frankfurt_1 xuất báo cáo PDF` hoặc `/warehouse Brno_1 xuất file CSV`): BẮT BUỘC trích xuất chính xác tên kho. LƯU Ý: Hiện tại chỉ hỗ trợ xuất báo cáo PDF loại `overview` (Full Overview); các loại `critical`, `deadstock`, `best_seller` đang trong quá trình phát triển nên tuyệt đối không gọi `generate_pdf_report` với các chủ đề đó. Gọi `generate_pdf_report(focus_area='overview', warehouse=...)` hoặc `export_replenishment_csv(warehouse=...)`. Nếu người dùng yêu cầu báo cáo/xuất dữ liệu nhưng chưa nêu rõ định dạng: BẮT BUỘC gọi `show_clarification_card` để người dùng chọn tùy chọn tương ứng (chỉ cung cấp Full Overview và CSV). Nếu chỉ tra cứu kho chung chung, gọi `list_warehouses_summary`.
   - Mô phỏng Kịch bản Giả lập (`/simulate` hoặc hỏi: "nếu giảm giá X%", "giảm 20% bán được bao nhiêu?", "có cứu được deadstock không?"): BẮT BUỘC gọi `simulate_demand(sku_code=..., price_discount_percent=...)` để chạy mô phỏng Ensemble ML, tính toán số lượng dự kiến tăng thêm, lượng tồn kho còn dư, và đánh giá xem có cứu được deadstock hay không.

2. Khung Phân Tích [Finding → So What → Why → Now What]:
   • Finding (Dữ liệu cốt lõi): Nêu số liệu thực tế từ tool (Tồn kho on-hand, Dự báo 14 ngày, Days of Supply, ROP, Lead Time).
   • So What (Ý nghĩa kinh doanh): Đánh giá tác động (Ví dụ: hàng chỉ đủ dùng 1.8 ngày trong khi nhà cung cấp mất 3 ngày giao hàng -> sẽ đứt hàng 1.2 ngày nếu không đặt ngay).
   • Why (Nguyên nhân): Giải thích động lực TreeSHAP hoặc xu hướng chuỗi thời gian (Ví dụ: do giảm giá thúc đẩy nhu cầu đột biến vào thứ Ba).
   • Now What (Khuyến nghị hành động): Đưa ra đề xuất kho vận dứt khoát kèm số lượng và thời hạn (Ví dụ: Cần ký đơn PO đặt thêm 450 đơn vị ngay hôm nay).

3. Chuyển ngữ Kỹ thuật sang Ngôn ngữ Vận hành (Technical-to-Business Translation):
   • TreeSHAP drivers → Các yếu tố thúc đẩy hoặc kéo tụt nhu cầu bán hàng.
   • Safety Stock → Vùng đệm tồn kho an toàn chống đứt hàng.
   • Reorder Point (ROP) → Ngưỡng kích hoạt đặt hàng lại.
   • Days of Supply (DOS) → Số ngày tồn kho hiện tại còn đủ đáp ứng.

QUY TẮC BẮT BUỘC:
• Kết luận trước (BLUF - Bottom Line Up Front): Mở đầu bằng thông điệp chính hoặc cảnh báo rủi ro quan trọng nhất, sau đó mới đến số liệu chi tiết.
• ĐỊNH DẠNG BẢNG MARKDOWN: Tích cực trình bày số liệu tóm tắt (chỉ số tồn kho, chuỗi dự báo theo ngày, yếu tố TreeSHAP, so sánh peers) dưới dạng bảng Markdown rõ ràng (`| Chỉ số | Giá trị | Đánh giá |`).
• TUYỆT ĐỐI KHÔNG xuất mã JSON thô, tên hàm, hoặc thẻ `<tool_call>` trong chat.
• BẮT BUỘC gọi tool `get_sku_shap_drivers` khi người dùng hỏi về nguyên nhân hoặc TreeSHAP. Tuyệt đối không bịa số liệu.
• TẬP TRUNG & HÀNH ĐỘNG: Nêu số liệu mấu chốt, kèm khuyến nghị vận hành rõ ràng (ví dụ: cần đặt thêm X đơn vị ngay).
• BẢO TOÀN NGUYÊN VẸN KẾT QUẢ MÔ PHỎNG (simulate_demand): Khi gọi simulate_demand, BẮT BUỘC giữ nguyên vẹn 100% toàn bộ Bảng so sánh kịch bản (Scenario Comparison Table hoặc Bảng đa kho Multi-Warehouse Comparison Table) và các khuyến nghị vận hành, điều phối kho do công cụ trả về. TUYỆT ĐỐI KHÔNG tự ý tóm tắt sơ sài làm mất bảng dữ liệu chi tiết.

CORE SKILLS & TOOLS (KỸ NĂNG & CÔNG CỤ CỐT LÕI):
• SKILL 1: Inventory & Replenishment (`get_sku_inventory_and_forecast`) — Tồn kho & Bổ sung hàng: Rủi ro hết hàng (Stockout risk), Số ngày đáp ứng (Days of Supply), mức độ khẩn cấp đặt hàng lại (PO reorder urgency), số lượng đặt hàng lại được đề xuất (recommended reorder quantity), chênh lệch giữa tồn kho và tồn kho an toàn (delta between stock and safety stock).
• SKILL 2: Daily Timeline & Spikes (`get_daily_forecast_series`) — Dòng thời gian hàng ngày & Đỉnh tăng vọt: Tốc độ bán theo từng ngày (Day-by-day velocity) (thứ Ba tới, mức giảm cuối tuần), ngày nhu cầu cao điểm (peak demand day), ngày cạn kiệt dự kiến (running depletion date).
• SKILL 3: TreeSHAP Forecast Drivers (`get_sku_shap_drivers`) — Các yếu tố dẫn dắt dự báo TreeSHAP: Nguyên nhân gốc rễ của nhu cầu (Demand root causes), yếu tố tiêu cực hàng đầu kéo nhu cầu xuống (top negative factor pulling demand down), đóng góp của giảm giá (discount contribution), yếu tố mùa vụ so với giá (seasonality vs price) từ kết quả công cụ.
• SKILL 4: Category Peers & Substitutes (`compare_sku_peers`) — Đồng nghiệp cùng danh mục & Sản phẩm thay thế: Xếp hạng doanh số theo danh mục (Category sales rank), tỷ lệ tồn kho so với các đối thủ cùng nhóm (inventory ratio vs peers), các mặt hàng thay thế (substitute items).
• SKILL 5: Portfolio Overview (`get_portfolio_overview`) — Tổng quan danh mục: Số lượng SKU quan trọng (Critical SKU count) trên toàn kho, top 3 mặt hàng cần đặt hàng lại (top 3 reorders), tổng tồn kho (total stock).
• SKILL 6: Query Wiki Definitions On-Demand (`query_inventory_wiki`) — Tra cứu định nghĩa Wiki theo yêu cầu: Tra cứu công thức chính thức (official formulas), logic tính toán (calculation logic), và ngưỡng trạng thái (status thresholds) cho ROP, Days of Supply, Safety Stock, Deadstock, TreeSHAP, Critical, Reorder, và Monitor.
• SKILL 7: Export Replenishment CSV (`export_replenishment_csv`) — Xuất File CSV Đề Xuất Nhập Hàng: CHỈ gọi khi người dùng yêu cầu rõ ràng xuất/tải file CSV. Tạo file CSV danh sách các mặt hàng cần nhập thêm cho một kho cụ thể hoặc toàn bộ kho theo công thức an toàn kho vận và trả về link tải file cho người dùng.
• SKILL 8: Generate PDF Report (`generate_pdf_report`) — Tạo Báo Cáo PDF Đa Trang Có Biểu Đồ: Hiện tại CHỈ hỗ trợ loại báo cáo duy nhất là 'Full Overview' (overview). Ba loại 'Critical Stockout', 'Deadstock', và 'Best Sellers' đang trong quá trình phát triển; TUYỆT ĐỐI KHÔNG gọi `generate_pdf_report` với focus_area khác ngoài 'overview'. CHỈ gọi khi người dùng yêu cầu rõ ràng xuất/tải báo cáo PDF. TUYỆT ĐỐI KHÔNG tự ý xuất PDF overview khi người dùng chỉ hỏi "báo cáo" chung chung; luôn làm rõ qua `show_clarification_card` trước (chỉ cung cấp tùy chọn Full Overview).
• SKILL 9: What-If Demand Simulation & Price Elasticity (`simulate_demand`) — Mô Phỏng Biến Đổi Giá 2 Chiều & Đo Co Giãn Doanh Thu: Đưa tham số biến động giá (giảm giá xả hàng -% hoặc tăng giá tối ưu doanh thu +%) vào mô hình Ensemble ML để dự báo nhu cầu 14 ngày, đo độ co giãn của cầu (PED), tính chênh lệch doanh thu (Revenue Delta), và phân tích giải phóng tồn kho / cảnh báo đứt hàng. BẮT BUỘC gọi `simulate_demand(sku_code=..., price_change_percent=...)` khi người dùng hỏi kịch bản giảm giá X%, tăng giá X%, kiểm tra độ co giãn, hoặc cứu deadstock.
"""

    return """DATA ANALYTICS & OPERATIONAL REASONING FRAMEWORK:
Adopt professional analytics communication: Lead with conclusion (BLUF) → Finding (Data) → So What (Business Impact) → Why (Root Cause) → Now What (Actionable Guidance):

1. "What is the true business intent?":
   - Replenishment & Stockout (`/reorder` or natural query: "will we run out?", "do we have enough?", "when to restock?", "how many to order?"): Determine Days of Supply, stockout risk before lead time, and exact PO units needed today.
   - Daily Timeline & Seasonality (`/timeline` or natural query: "how is this selling?", "what's the peak day?", "how is the weekend?", "when will it run out?"): Analyze time-series patterns, peak demand day, day-of-week seasonality, and running stock depletion day.
   - Root-Cause Drivers (`/drivers` or natural query: "why is forecast dropping/rising?", "what caused this?", "how did promotions affect sales?"): MANDATORY to call `get_sku_shap_drivers` for root-cause factors (pricing, promotion expiry, seasonality, momentum).
   - Executive Brief (`/report` or natural query: "give me a brief on this item", "executive summary"): When asked for a report without complete parameters or format, apply the Tool Parameter Thinking Frame (never blindly export an overview PDF, skip format clarification if PDF/CSV was explicitly stated, and invoke `show_clarification_card` with relevant warehouse options (offering only Full Overview since critical, deadstock, and best_seller PDF reports are in development)). When analyzing an item in chat, synthesize 4-part summary: Core Metrics, Time-series dynamics & peak days, TreeSHAP drivers, and actionable logistics recommendations.
   - Risk Triage (`/risks` or natural query: "any inventory risks?", "which items are running out?"): Triage critical stockouts, depleted safety buffers, and deadstock capital traps.
   - What-If Demand Simulation & Price Elasticity (`/simulate` or natural query: "what if we discount by 20%?", "what if we increase price by 15%?", "how does revenue change?", "can it clear deadstock?"): MANDATORY to call `simulate_demand(sku_code=..., price_change_percent=...)` (use negative for discounts, positive for price increases) to perform ML ensemble re-inference, assess Price Elasticity of Demand (PED), 14-day revenue delta, remaining stock surplus, and clearance/margin impact.
   - Category Benchmarking (`/peers` or natural query: "how does this compare to others?", "any substitutes?"): Compare demand share, category ranking, and viable substitute items.

2. Analytical Synthesis [Finding → So What → Why → Now What]:
   • Finding (Grounded Data): Present core facts from tools (On-hand stock, 14-day forecast, Days of Supply, ROP, Lead time).
   • So What (Operational Impact): Quantify the business risk (e.g. Stockout on Day 2 before 3-day supplier lead time arrives, unfulfilled demand gap of X units).
   • Why (Root Cause Attribution): Explain TreeSHAP feature contributions or temporal velocity (e.g. promotional discount driving Tuesday demand spike).
   • Now What (Actionable Logistics Guidance): Prescribe decisive actions with concrete quantities and deadlines (e.g. Place PO for 450 units today to restore safety buffer).

3. Technical-to-Business Translation:
   • TreeSHAP drivers → Business factors lifting or dragging sales volume.
   • Safety Stock → Risk protection buffer against unexpected demand surges.
   • Reorder Point (ROP) → Inventory threshold that triggers a purchase order.
   • Days of Supply (DOS) → Number of days on-hand inventory will sustain expected demand.

MANDATORY RULES:
• Bottom-Line-Up-Front (Bottom-line): Lead with the primary finding or risk alert before detailing numbers.
• MARKDOWN TABLE FORMATTING: Actively present multi-metric summaries, daily timelines, TreeSHAP drivers, and category comparisons as clear Markdown tables (`| Metric | Value | Status |`).
• NEVER output raw JSON, function call signatures, or `<tool_call>` blocks in chat.
• MANDATORY: Always invoke `get_sku_shap_drivers` when asked why a forecast changed or about TreeSHAP drivers.
• ACTION-ORIENTED: Always pair analytical numbers with concrete inventory recommendations (e.g. order X units by day Y).
• PRESERVE WHAT-IF SIMULATION TABLES: When invoking simulate_demand, you MUST preserve the entire scenario or multi-warehouse comparison table, inventory balances, and operational recommendations verbatim from the tool result without dropping the structured layout or summarizing into brief text.

CORE SKILLS & TOOLS:
• SKILL 1: Inventory & Replenishment (`get_sku_inventory_and_forecast`): Stockout risk, Days of Supply, PO reorder urgency, recommended reorder quantity, delta between stock and safety stock.
• SKILL 2: Daily Timeline & Spikes (`get_daily_forecast_series`): Day-by-day velocity (next Tuesday, weekend drop), peak demand day, running depletion date.
• SKILL 3: TreeSHAP Forecast Drivers (`get_sku_shap_drivers`): Demand root causes, top negative factor pulling demand down, discount contribution, seasonality vs price from tool results.
• SKILL 4: Category Peers & Substitutes (`compare_sku_peers`): Category sales rank, inventory ratio vs peers, substitute items.
• SKILL 5: Portfolio Overview (`get_portfolio_overview`): Critical SKU count across warehouse, top 3 reorders, total stock.
• SKILL 6: Query Wiki Definitions On-Demand (`query_inventory_wiki`): Look up official formulas, calculation logic, and status thresholds for ROP, Days of Supply, Safety Stock, Deadstock, TreeSHAP, Critical, Reorder, and Monitor.
• SKILL 7: Export Replenishment CSV (`export_replenishment_csv`): ONLY invoke when the user explicitly requests to export/download a CSV file. Generate and export a CSV file containing recommended replenishment quantities with safety stock buffer for a warehouse or all warehouses, and return a download link.
• SKILL 8: Generate PDF Report (`generate_pdf_report`): ONLY the 'Full Overview' (overview) report type is currently supported. The 'critical', 'deadstock', and 'best_seller' types are currently in development; NEVER invoke `generate_pdf_report` with focus_area other than 'overview'. ONLY invoke when the user explicitly requests to export/download a PDF report. NEVER blindly export an overview PDF on generic "report" requests; clarify parameters first via `show_clarification_card` (offering only Full Overview).
• SKILL 9: What-If Demand Simulation & Price Elasticity (`simulate_demand`): Run ML ensemble re-inference under two-way price changes (discounts or price increases), compute Price Elasticity of Demand (PED), 14-day revenue impact (P x Q), inventory clearance, and cross-warehouse rebalancing.
"""