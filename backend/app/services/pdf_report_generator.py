"""pdf_report_generator.py — Multi-page professional Executive PDF report generation for DemandAI.

Adheres strictly to DemandAI supply chain intelligence guidelines:
- Landscape orientation with NumberedCanvas page numbering (Page X / Y).
- Professional typography via DejaVu TrueType fonts.
- 2-Page Executive Structure:
  A. Section A: Report Information & Data Scope (2x2 Balanced Metadata Grid)
  B. Section B: Executive KPI Summary, Visual Charts (Donut & Bar) & Strategic Insights Box
  C. Section C: Priority Action Plan (Top 15 Focus Items Table)
"""
from __future__ import annotations

from datetime import datetime
import re
import io
import math
from pathlib import Path
from typing import Any, Optional, Union

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image,
    PageBreak,
    KeepTogether,
    HRFlowable,
)
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import registerFontFamily

from app.services.report_data_service import (
    ReportDataset,
    ProcessedReportItem,
    ReportMetadata,
    fetch_report_dataset,
)

# 1. Register Unicode TrueType Fonts for 100% Vietnamese support
FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

pdfmetrics.registerFont(TTFont("DejaVuSans", FONT_REGULAR))
pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", FONT_BOLD))
registerFontFamily(
    "DejaVuSans",
    normal="DejaVuSans",
    bold="DejaVuSans-Bold",
    italic="DejaVuSans",
    boldItalic="DejaVuSans-Bold",
)

plt.rcParams["font.sans-serif"] = ["DejaVu Sans", "Arial", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False


class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas for accurate total page count calculation and headers/footers."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[Any] = []

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count: int) -> None:
        self.saveState()
        self.setFont("DejaVuSans", 7.5)
        self.setFillColor(colors.HexColor("#64748b"))

        page_w, page_h = self._pagesize

        # Footer on all pages
        self.setStrokeColor(colors.HexColor("#e2e8f0"))
        self.setLineWidth(0.5)
        self.line(28.8, 28.8, page_w - 28.8, 28.8)

        page_str = f"Page {self._pageNumber} / {page_count}"
        self.drawRightString(page_w - 28.8, 18, page_str)
        self.drawString(
            28.8,
            18,
            "DemandAI Supply Chain Intelligence • Executive Inventory & 14-Day Replenishment Decision Briefing",
        )

        # Header on pages 2+
        if self._pageNumber > 1:
            self.drawString(28.8, page_h - 22, "DemandAI — Demand Forecasting & Retail Inventory Optimization")
            self.drawRightString(page_w - 28.8, page_h - 22, "Strictly Confidential • Internal Enterprise Use")
            self.setStrokeColor(colors.HexColor("#e2e8f0"))
            self.setLineWidth(0.5)
            self.line(28.8, page_h - 25, page_w - 28.8, page_h - 25)

        self.restoreState()


def render_risk_distribution_chart(risk_counts: dict[str, int]) -> io.BytesIO:
    """Render risk status distribution donut chart with centered donut (only %) and explanation box below."""
    fig, ax = plt.subplots(figsize=(6.2, 3.2), dpi=200)

    labels = ["In Stock", "Reorder", "Monitor", "Critical", "Deadstock"]
    color_map = {
        "In Stock": "#4da20c",
        "Reorder": "#f59e0b",
        "Monitor": "#3b82f6",
        "Critical": "#d21d0a",
        "Deadstock": "#8b5cf6",
    }
    sizes = [risk_counts.get(k, 0) for k in labels]
    filtered_labels = [l for l, s in zip(labels, sizes) if s > 0]
    filtered_sizes = [s for s in sizes if s > 0]
    filtered_colors = [color_map[l] for l in filtered_labels]
    total_items = sum(filtered_sizes)

    if not filtered_sizes or total_items == 0:
        filtered_labels = ["No Data"]
        filtered_sizes = [1]
        filtered_colors = ["#cbd5e1"]
        total_items = 1

    # 1. Display ONLY % values on donut slices (>= 3.0% threshold to avoid overlap)
    def make_autopct(pct):
        if pct >= 3.0:
            return f"{pct:.1f}%"
        return ""

    wedges, texts, autotexts = ax.pie(
        filtered_sizes,
        labels=None,
        autopct=make_autopct,
        pctdistance=0.72,
        startangle=135,
        colors=filtered_colors,
        wedgeprops={"width": 0.42, "edgecolor": "white", "linewidth": 1.8},
        textprops={"fontsize": 7.5, "color": "#0f172a"},
        center=(0, 0.15),  # Center and slightly elevate to make room for bottom explanation box
        radius=0.88,
    )
    for t in autotexts:
        t.set_fontsize(7.5)
        t.set_weight("bold")

    # 2. All legend descriptions placed into bottom explanation box
    legend_labels = []
    for l, s in zip(filtered_labels, filtered_sizes):
        pct = (s / total_items) * 100 if total_items > 0 else 0
        legend_labels.append(f"{l}: {pct:.1f}% ({s:,} units)")

    leg = ax.legend(
        wedges,
        legend_labels,
        loc="lower center",
        bbox_to_anchor=(0.5, -0.12),
        ncol=3,
        fontsize=6.8,
        frameon=True,
        facecolor="#f8fafc",
        edgecolor="#cbd5e1",
        borderpad=0.5,
        labelspacing=0.4,
        columnspacing=1.0,
    )
    leg.get_frame().set_linewidth(0.8)

    ax.set_title("Inventory Risk Status Distribution (SKU–Warehouse Records)", fontsize=8.5, fontweight="bold", pad=6, color="#0f172a")
    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format="png", bbox_inches="tight", dpi=200)
    plt.close(fig)
    buf.seek(0)
    return buf


def render_top_items_bar_chart(
    items: list[ProcessedReportItem],
    focus_key: str,
) -> io.BytesIO:
    """Render horizontal bar chart for top items with exact measurement units."""
    import matplotlib.ticker as ticker

    fig, ax = plt.subplots(figsize=(6.2, 3.2), dpi=200)

    top_subset = items[:8]
    if not top_subset:
        ax.text(0.5, 0.5, "No matching items found", ha="center", va="center", fontsize=8.5)
        ax.axis("off")
        buf = io.BytesIO()
        plt.savefig(buf, format="png", bbox_inches="tight", dpi=200)
        plt.close(fig)
        buf.seek(0)
        return buf

    names = [f"{it.name[:18]}... ({it.sku})" if len(it.name) > 18 else f"{it.name} ({it.sku})" for it in top_subset]

    if focus_key == "critical":
        vals = [float(it.suggested_replenishment_14d or 0) for it in top_subset]
        chart_title = "Top Items by 14-Day Replenishment Requirement (Units)"
        bar_color = "#ea580c"
    elif focus_key == "deadstock":
        vals = [float(it.current_stock) for it in top_subset]
        chart_title = "Top Slow-Moving & Capital-Tied Items (Current Stock Units)"
        bar_color = "#d21d0a"
    elif focus_key == "best_seller":
        vals = [float(it.forecast_14d or 0.0) for it in top_subset]
        chart_title = "Top High-Demand Items (14-Day Forecasted Units)"
        bar_color = "#4da20c"
    else:  # overview
        vals = [float(it.forecast_14d or 0.0) for it in top_subset]
        chart_title = "Top High-Demand Items (14-Day Forecasted Units)"
        bar_color = "#1d4ed8"

    max_val = max(vals) if vals and max(vals) > 0 else 1.0
    bars = ax.barh(names[::-1], vals[::-1], color=bar_color, height=0.52)
    ax.set_xlim(0, max_val * 1.30)
    ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, p: f"{int(x):,}"))

    for bar in bars:
        w = bar.get_width()
        ax.text(
            w + max_val * 0.02,
            bar.get_y() + bar.get_height() / 2,
            f"{w:,.0f} units",
            va="center",
            fontsize=6.8,
            fontweight="bold",
            color="#0f172a",
        )

    ax.set_title(chart_title, fontsize=8.5, fontweight="bold", pad=8, color="#0f172a")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#cbd5e1")
    ax.spines["bottom"].set_color("#cbd5e1")
    ax.tick_params(colors="#475569", labelsize=7.0)

    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format="png", bbox_inches="tight", dpi=200)
    plt.close(fig)
    buf.seek(0)
    return buf


def format_report_filename(
    focus_key: str,
    warehouse_scope: str = "",
    warehouses_included: Optional[list[str]] = None,
    export_datetime: Optional[datetime] = None,
) -> str:
    """Generate standardized English PDF report filename:
    report_{TOPIC}_{WAREHOUSE}_{YYYYMMDD}_{HHMMSS}.pdf
    """
    dt = export_datetime or datetime.now()
    date_str = dt.strftime("%Y%m%d")
    time_str = dt.strftime("%H%M%S")

    # 1. Report topic (English snake_case)
    topic_slug = str(focus_key or "overview").strip().lower()

    # 2. Warehouse scope (English)
    wh_lower = str(warehouse_scope or "").strip().lower()
    if (
        not wh_lower
        or any(k in wh_lower for k in ["all", "tat ca", "tất cả", "toàn bộ", "system", "entire"])
        or (warehouses_included and len(warehouses_included) > 1)
    ):
        warehouse_slug = "all_warehouses"
    else:
        if warehouses_included and len(warehouses_included) == 1:
            raw_wh = warehouses_included[0]
        else:
            raw_wh = warehouse_scope
        warehouse_slug = re.sub(r"[^a-zA-Z0-9]+", "_", raw_wh).strip("_").lower() or "all_warehouses"

    return f"report_{topic_slug}_{warehouse_slug}_{date_str}_{time_str}.pdf"


def generate_multi_page_report(
    items: Union[list[dict[str, Any]], ReportDataset],
    focus_area: str = "overview",
    warehouse_label: str = "",
    output_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Generate multi-page Executive PDF report following DemandAI design standard."""
    if output_path is None:
        fname = format_report_filename(focus_key=focus_area, warehouse_scope=warehouse_label)
        output_path = Path(f"/tmp/{fname}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Resolve Dataset
    if isinstance(items, ReportDataset):
        ds = items
    elif isinstance(items, list):
        # Passed in raw items list (e.g. from mock tests or legacy calls)
        ds = fetch_report_dataset(
            focus_area=focus_area,
            warehouse_filter=warehouse_label,
            raw_items_override=items,
        )
    else:
        # Fallback to query database
        ds = fetch_report_dataset(
            focus_area=focus_area,
            warehouse_filter=warehouse_label,
        )

    meta = ds.metadata
    theme_hex = meta.theme_color
    theme_c = colors.HexColor(theme_hex)

    # If dataset is empty, create clean notice report
    if ds.is_empty:
        return _render_empty_notice_pdf(ds, output_path)

    # Build PDF with landscape letter (792 pt x 612 pt)
    page_width, page_height = landscape(letter)
    left_m, right_m, top_m, bot_m = 28.8, 28.8, 32.0, 32.0
    printable_w = page_width - left_m - right_m  # 734.4 pt

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=landscape(letter),
        leftMargin=left_m,
        rightMargin=right_m,
        topMargin=top_m,
        bottomMargin=bot_m,
    )

    styles = getSampleStyleSheet()

    # Custom Typography Styles
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Heading1"],
        fontName="DejaVuSans-Bold",
        fontSize=16,
        leading=20,
        alignment=1,  # Center alignment
        textColor=colors.HexColor("#ffffff"),
    )
    sub_title_style = ParagraphStyle(
        "ReportSubTitle",
        parent=styles["Normal"],
        fontName="DejaVuSans",
        fontSize=8.0,
        leading=10,
        textColor=colors.HexColor("#e2e8f0"),
    )
    section_h2 = ParagraphStyle(
        "SectionH2",
        parent=styles["Heading2"],
        fontName="DejaVuSans-Bold",
        fontSize=10.0,
        leading=13,
        textColor=theme_c,
        spaceBefore=0,
        spaceAfter=4,
    )
    meta_label = ParagraphStyle(
        "MetaLabel",
        parent=styles["Normal"],
        fontName="DejaVuSans-Bold",
        fontSize=7.2,
        leading=9.5,
        textColor=colors.HexColor("#475569"),
    )
    meta_val = ParagraphStyle(
        "MetaVal",
        parent=styles["Normal"],
        fontName="DejaVuSans",
        fontSize=7.2,
        leading=9.5,
        textColor=colors.HexColor("#0f172a"),
    )
    kpi_number = ParagraphStyle(
        "KPINumber",
        parent=styles["Normal"],
        fontName="DejaVuSans-Bold",
        fontSize=13.0,
        leading=15,
        alignment=1,  # Center
        textColor=colors.HexColor("#0f172a"),
    )
    kpi_label = ParagraphStyle(
        "KPILabel",
        parent=styles["Normal"],
        fontName="DejaVuSans",
        fontSize=6.8,
        leading=8.5,
        alignment=1,
        textColor=colors.HexColor("#64748b"),
    )
    insight_text = ParagraphStyle(
        "InsightText",
        parent=styles["Normal"],
        fontName="DejaVuSans",
        fontSize=7.5,
        leading=10.5,
        textColor=colors.HexColor("#1e293b"),
    )
    tbl_th = ParagraphStyle(
        "TblTH",
        parent=styles["Normal"],
        fontName="DejaVuSans-Bold",
        fontSize=7.0,
        leading=8.5,
        alignment=1,
        textColor=colors.HexColor("#ffffff"),
    )
    tbl_td = ParagraphStyle(
        "TblTD",
        parent=styles["Normal"],
        fontName="DejaVuSans",
        fontSize=6.5,
        leading=8.2,
        textColor=colors.HexColor("#1e293b"),
    )
    tbl_td_reason = ParagraphStyle(
        "TblTDReason",
        parent=styles["Normal"],
        fontName="DejaVuSans",
        fontSize=6.3,
        leading=7.8,
        textColor=colors.HexColor("#1e293b"),
    )
    tbl_td_bold = ParagraphStyle(
        "TblTDBold",
        parent=styles["Normal"],
        fontName="DejaVuSans-Bold",
        fontSize=6.8,
        leading=8.5,
        textColor=colors.HexColor("#0f172a"),
    )
    tbl_td_center = ParagraphStyle(
        "TblTDCenter",
        parent=styles["Normal"],
        fontName="DejaVuSans",
        fontSize=6.8,
        leading=8.5,
        alignment=1,
        textColor=colors.HexColor("#1e293b"),
    )

    story: list[Any] = []

    # ==========================================
    # SECTION A: REPORT HEADER BANNER
    # ==========================================
    header_content = [
        [Paragraph(meta.focus_title_vi, title_style)]
    ]
    header_tbl = Table(header_content, colWidths=[printable_w])
    header_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), theme_c),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(header_tbl)
    story.append(Spacer(1, 8))

    # ==========================================
    # SECTION A: REPORT INFORMATION & DATA SCOPE
    # ==========================================
    story.append(Paragraph("SECTION A: REPORT INFORMATION & DATA SCOPE", section_h2))

    # Balanced 2x2 Metadata Grid (Filtered of internal run_id and data source details)
    meta_rows = [
        [
            Paragraph("<b>Warehouse Scope:</b>", meta_label),
            Paragraph(meta.warehouse_scope_label, meta_val),
            Paragraph("<b>Inventory Snapshot:</b>", meta_label),
            Paragraph(str(meta.snapshot_date), meta_val),
        ],
        [
            Paragraph("<b>14-Day Forecast Window:</b>", meta_label),
            Paragraph(f"{meta.forecast_start_date} → {meta.forecast_end_date} (14 days)", meta_val),
            Paragraph("<b>Export Time & Timezone:</b>", meta_label),
            Paragraph(f"{meta.export_timestamp} ({meta.timezone_name})", meta_val),
        ],
    ]
    col1_label_w = 115
    col1_val_w = printable_w * 0.5 - col1_label_w
    col2_label_w = 140
    col2_val_w = printable_w * 0.5 - col2_label_w
    meta_tbl = Table(meta_rows, colWidths=[col1_label_w, col1_val_w, col2_label_w, col2_val_w])
    meta_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#cbd5e1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(meta_tbl)
    story.append(Spacer(1, 10))

    # ==========================================
    # SECTION B: EXECUTIVE KPI SUMMARY, VISUAL CHARTS & STRATEGIC INSIGHTS
    # ==========================================
    story.append(Paragraph("SECTION B: EXECUTIVE KPI SUMMARY, VISUAL CHARTS & STRATEGIC INSIGHTS", section_h2))

    # 1. 5 KPI Cards in one horizontal row
    card_w = printable_w / 5.0
    crit_reorder = meta.risk_distribution.get("Critical", 0) + meta.risk_distribution.get("Reorder", 0)
    crit_pct = (crit_reorder / meta.total_records_in_scope * 100) if meta.total_records_in_scope else 0.0

    kpi_cards = [
        [
            Paragraph(f"{meta.total_records_in_scope:,}", kpi_number),
            Paragraph(f"{meta.total_on_hand_stock:,.0f}", kpi_number),
            Paragraph(f"{meta.total_forecast_14d:,.0f}", kpi_number),
            Paragraph(f"{meta.total_preliminary_replenishment:,.0f}", kpi_number),
            Paragraph(f"{crit_reorder:,} ({crit_pct:.1f}%)", ParagraphStyle("CritKPINum", parent=kpi_number, textColor=colors.HexColor("#d21d0a"))),
        ],
        [
            Paragraph(f"SKU–Warehouse Records<br/>({meta.unique_skus_in_scope:,} unique SKUs)", kpi_label),
            Paragraph("Current Stock On-Hand<br/>(physical units)", kpi_label),
            Paragraph("Total Forecasted Demand<br/>(next 14 days)", kpi_label),
            Paragraph("Preliminary Replenishment<br/>(14-day target)", kpi_label),
            Paragraph("Stockout Risk Items<br/>(Critical + Reorder)", kpi_label),
        ],
    ]
    kpi_tbl = Table(kpi_cards, colWidths=[card_w] * 5)
    kpi_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#cbd5e1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
        ("TOPPADDING", (0, 0), (-1, 0), 3),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 1.5),
        ("TOPPADDING", (0, 1), (-1, 1), 1),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 3),
    ]))
    story.append(kpi_tbl)
    story.append(Spacer(1, 5))

    # 2. Scaled Visual Charts (Merged directly into Section B on Page 1)
    donut_buf = render_risk_distribution_chart(meta.risk_distribution)
    bar_buf = render_top_items_bar_chart(ds.items, meta.focus_key)

    chart_w = (printable_w - 6) / 2.0
    chart_h = 175.0

    img_donut = Image(donut_buf, width=chart_w, height=chart_h)
    img_bar = Image(bar_buf, width=chart_w, height=chart_h)

    charts_tbl = Table([[img_donut, img_bar]], colWidths=[chart_w, chart_w])
    charts_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#cbd5e1")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#ffffff")),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(charts_tbl)
    story.append(Spacer(1, 5))

    # 3. Executive Key Findings Box
    insights_cells = [
        [
            Paragraph("<b>EXECUTIVE STRATEGIC FINDINGS (DATA-DRIVEN OBSERVATIONS)</b>", ParagraphStyle("InsH", parent=meta_label, textColor=theme_c)),
        ]
    ]
    for idx, insight in enumerate(meta.executive_insights, 1):
        insights_cells.append([Paragraph(f"<b>{idx}.</b> {insight}", insight_text)])

    insights_tbl = Table(insights_cells, colWidths=[printable_w])
    insights_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f0fdf4" if theme_hex == "#4da20c" else ("#fff7ed" if theme_hex == "#ea580c" else ("#fef2f2" if theme_hex == "#d21d0a" else "#eff6ff")))),
        ("BOX", (0, 0), (-1, -1), 0.8, theme_c),
        ("LINEBEFORE", (0, 0), (0, -1), 3.5, theme_c),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(insights_tbl)

    # ==========================================
    # SECTION C: PRIORITY ACTION PLAN (PAGE BREAK TO PAGE 2)
    # ==========================================
    story.append(PageBreak())
    story.append(Paragraph(f"SECTION C: PRIORITY ACTION PLAN — TOP {len(ds.top_action_items)} FOCUS ITEMS", section_h2))

    action_cols = [44, 102, 54, 38, 45, 35, 32, 38, 40, 46, 260.4]
    action_table_data = [
        [
            Paragraph("SKU", tbl_th),
            Paragraph("Product Name", tbl_th),
            Paragraph("Warehouse", tbl_th),
            Paragraph("Stock<br/>(Units)", tbl_th),
            Paragraph("Forecast<br/>14d", tbl_th),
            Paragraph("DOS", tbl_th),
            Paragraph("Lead<br/>Time", tbl_th),
            Paragraph("Safety<br/>Stock", tbl_th),
            Paragraph("Dynamic<br/>ROP", tbl_th),
            Paragraph("Replenish<br/>Target", tbl_th),
            Paragraph("Alert Reason & Recommended Action", tbl_th),
        ]
    ]

    for it in ds.top_action_items:
        replenish_str = f"<b>{it.suggested_replenishment_14d:,}</b>" if it.suggested_replenishment_14d is not None else "N/A"
        name_trunc = f"{it.name[:25]}..." if len(it.name) > 25 else it.name
        action_table_data.append([
            Paragraph(it.sku, tbl_td),
            Paragraph(f"{name_trunc}<br/><font color='{theme_hex}'><b>[{it.status}]</b></font>", tbl_td),
            Paragraph(it.warehouse, tbl_td_center),
            Paragraph(f"{it.current_stock:,}", tbl_td_center),
            Paragraph(f"{it.forecast_14d:,.0f}" if it.forecast_14d is not None else "N/A", tbl_td_center),
            Paragraph(it.dos_display, tbl_td_center),
            Paragraph(f"{it.lead_time_days}d", tbl_td_center),
            Paragraph(f"{it.safety_stock:.0f}", tbl_td_center),
            Paragraph(f"{it.dynamic_rop:.0f}", tbl_td_center),
            Paragraph(replenish_str, tbl_td_center),
            Paragraph(f"{it.alert_reason} {it.recommended_action}", tbl_td_reason),
        ])

    action_tbl = Table(action_table_data, colWidths=action_cols, repeatRows=1)
    action_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), theme_c),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#ffffff"), colors.HexColor("#f8fafc")]),
        ("TOPPADDING", (0, 0), (-1, -1), 1.8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.8),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(action_tbl)

    # Build Document (2-Page Executive Briefing Report)
    doc.build(story, canvasmaker=NumberedCanvas)

    return {
        "status": "success",
        "output_path": str(output_path),
        "filename": output_path.name,
        "focus_key": meta.focus_key,
        "focus_display": meta.focus_display_vi,
        "warehouse_scope": meta.warehouse_scope_label,
        "total_records": meta.total_records_in_scope,
        "matching_records": meta.matching_records_count,
        "total_stock": meta.total_on_hand_stock,
        "total_forecast": meta.total_forecast_14d,
        "total_replenishment": meta.total_preliminary_replenishment,
        "insights": meta.executive_insights,
    }


def _render_empty_notice_pdf(ds: ReportDataset, output_path: Path) -> dict[str, Any]:
    """Generate a clean notice PDF report when no items match filters without misleading clean bills of health."""
    meta = ds.metadata
    theme_c = colors.HexColor(meta.theme_color)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=landscape(letter),
        leftMargin=28.8,
        rightMargin=28.8,
        topMargin=32.0,
        bottomMargin=32.0,
    )
    styles = getSampleStyleSheet()

    story: list[Any] = []
    # Header
    hdr = Table(
        [
            [Paragraph(meta.focus_title_vi, ParagraphStyle("H1", fontName="DejaVuSans-Bold", fontSize=16, leading=20, alignment=1, textColor=colors.white))],
        ],
        colWidths=[734.4],
    )
    hdr.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), theme_c),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(hdr)
    story.append(Spacer(1, 20))

    # Notice card
    notice_text = (
        f"<b>INVENTORY CATALOG AUDIT SUMMARY</b><br/><br/>"
        f"{ds.empty_reason or 'No items matching specified audit criteria.'}<br/><br/>"
        f"<b>Audit Scope & Parameters:</b><br/>"
        f"• Warehouse Scope: {meta.warehouse_scope_label}<br/>"
        f"• Snapshot Date: {meta.snapshot_date}<br/>"
        f"• Forecast Window: {meta.forecast_start_date} → {meta.forecast_end_date} (14 days)<br/>"
        f"• Export Timestamp: {meta.export_timestamp} ({meta.timezone_name})<br/>"
        f"• Data Source: {meta.data_source}<br/><br/>"
        f"<i>Recommendation: Re-evaluate following subsequent forecast runs or upon arrival of updated stock snapshots.</i>"
    )
    tbl = Table([[Paragraph(notice_text, ParagraphStyle("NText", fontName="DejaVuSans", fontSize=8.5, leading=12, textColor=colors.HexColor("#1e293b")))]], colWidths=[734.4])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("BOX", (0, 0), (-1, -1), 0.8, theme_c),
        ("LINEBEFORE", (0, 0), (0, -1), 4, theme_c),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
    ]))
    story.append(tbl)

    doc.build(story, canvasmaker=NumberedCanvas)

    return {
        "status": "empty",
        "output_path": str(output_path),
        "filename": output_path.name,
        "focus_key": meta.focus_key,
        "focus_display": meta.focus_display_vi,
        "warehouse_scope": meta.warehouse_scope_label,
        "total_records": meta.total_records_in_scope,
        "matching_records": 0,
        "total_stock": 0,
        "total_forecast": 0.0,
        "total_replenishment": 0,
        "insights": [],
        "message": ds.empty_reason,
    }
