"""app.agent.rag — Unified RAG context and portfolio overview generator.

Constructs grounded inventory knowledge from real database inventory records.
Zero hardcoded mock data.
"""
from __future__ import annotations

from typing import Any
from app.api.routes.forecast import _load_all_inventory_items


def get_all_inventory_items() -> list[dict[str, Any]]:
    """Retrieve full inventory items from database cache."""
    try:
        items = _load_all_inventory_items(use_inactive_items=False)
        if items:
            return items
    except Exception:
        pass
    return []


def build_overview_rag(selected_item: dict[str, Any] | None = None, focus: str = "all") -> str:
    """Build aggregated portfolio health context for high-level queries across all tracked SKUs."""
    items = get_all_inventory_items()
    total_items = len(items)
    total_forecast_14d = round(sum(float(i.get("forecast14d", 0)) for i in items))
    total_stock = sum(int(i.get("onHandStock", 0)) for i in items)

    warehouses = ", ".join(sorted(set(str(i.get("warehouse", "Central")) for i in items)))

    status_counts: dict[str, int] = {}
    for i in items:
        st = i.get("status", "In Stock")
        status_counts[st] = status_counts.get(st, 0) + 1

    def _get_dos(i: dict[str, Any]) -> float:
        if "days_of_supply" in i:
            return float(i["days_of_supply"])
        f14 = float(i.get("forecast14d", 0))
        stock = int(i.get("onHandStock", 0))
        return round(stock / max(f14 / 14.0, 0.05), 1)

    def _sku(it: dict[str, Any]) -> str:
        return str(it.get("sku") or f"SKU-{it.get('id', '')}")

    focus_clean = (focus or "all").strip().lower()

    # Critical stockout risks
    sorted_critical = sorted(
        [i for i in items if i.get("status") == "Critical"],
        key=_get_dos,
    )
    crit_limit = 30 if focus_clean == "critical" else 10
    critical_items = [
        f"- {i['name']} ({_sku(i)} | {i.get('warehouse', 'Central')}): {i.get('onHandStock', 0)} units in stock vs {round(float(i.get('forecast14d', 0)))} forecast ({_get_dos(i)} days supply) [STATUS: CRITICAL]"
        for i in sorted_critical[:crit_limit]
    ]
    if len(sorted_critical) > crit_limit:
        critical_items.append(f"- *...and {len(sorted_critical) - crit_limit} more critical items in portfolio.*")

    # Reorder items
    sorted_reorder = sorted(
        [i for i in items if i.get("status") == "Reorder"],
        key=_get_dos,
    )
    reorder_limit = 30 if focus_clean == "reorder" else 10
    reorder_items = [
        f"- {i['name']} ({_sku(i)} | {i.get('warehouse', 'Central')}): {i.get('onHandStock', 0)} on hand vs {round(float(i.get('forecast14d', 0)))} forecast ({_get_dos(i)} days supply)"
        for i in sorted_reorder[:reorder_limit]
    ]
    if len(sorted_reorder) > reorder_limit:
        reorder_items.append(f"- *...and {len(sorted_reorder) - reorder_limit} more reorder items.*")

    # Deadstock items (all items provided without artificial cutoff)
    sorted_deadstock = sorted(
        [i for i in items if i.get("status") == "Deadstock"],
        key=lambda x: -int(x.get("onHandStock", 0)),
    )
    deadstock_items = [
        f"- {i['name']} ({_sku(i)} | {i.get('warehouse', 'Central')}): {i.get('onHandStock', 0)} units sitting on {round(float(i.get('forecast14d', 0)))} 14d forecast ({_get_dos(i):.0f} days supply)"
        for i in sorted_deadstock
    ]

    # Category summaries
    cat_summary: dict[str, dict[str, Any]] = {}
    for i in items:
        c = i.get("category", "General")
        if c not in cat_summary:
            cat_summary[c] = {"forecast": 0.0, "stock": 0, "count": 0}
        cat_summary[c]["forecast"] += float(i.get("forecast14d", 0))
        cat_summary[c]["stock"] += int(i.get("onHandStock", 0))
        cat_summary[c]["count"] += 1

    cat_lines = [
        f"- **{cat}** ({data['count']} SKUs): 14d Demand={round(data['forecast']):,} | On-Hand={data['stock']:,} | Ratio={data['stock']/max(1.0, data['forecast']):.2f}x"
        for cat, data in sorted(cat_summary.items(), key=lambda x: x[1]["forecast"], reverse=True)
    ]

    selected_snippet = ""
    if selected_item:
        selected_sku = _sku(selected_item)
        selected_snippet = (
            f"\n> **USER'S CURRENTLY SELECTED ITEM ON SCREEN**:\n"
            f"> The user currently has `{selected_item['name']} ({selected_sku})` "
            f"open in their workspace panel (Status: {selected_item.get('status')}, "
            f"14d Forecast: {selected_item.get('forecast14d')}, On-Hand Stock: {selected_item.get('onHandStock')}). "
            f"You can refer to it naturally if relevant.\n"
        )

    return f"""### WORKSPACE PORTFOLIO OVERVIEW KNOWLEDGE (ON-THE-RUN RAG)
{selected_snippet}
- **Total Tracked SKUs**: {total_items} items across {warehouses}.
- **Aggregate 14-Day Expected Demand**: {total_forecast_14d:,} units.
- **Total Current On-Hand Inventory**: {total_stock:,} units.
- **Portfolio Health Status**:
  * Critical (Immediate Stockout Risk): {status_counts.get('Critical', 0)} items
  * Reorder Required: {status_counts.get('Reorder', 0)} items
  * Monitor Closely: {status_counts.get('Monitor', 0)} items
  * In Stock (Healthy): {status_counts.get('In Stock', 0)} items
  * Deadstock (Excess Capital Sink): {status_counts.get('Deadstock', 0)} items

#### Top Stockout Alerts (Immediate Order Required):
{chr(10).join(critical_items)}

#### Reorder Priority Items:
{chr(10).join(reorder_items)}

#### Deadstock Items (Capital Tied Up):
{chr(10).join(deadstock_items)}

#### Category Demand Distribution:
{chr(10).join(cat_lines)}
"""


def generate_rag_context(query: str, selected_item_id: str | None = None) -> tuple[str, str]:
    """Compatibility wrapper for RAG context generation."""
    selected_item = None
    if selected_item_id:
        items = get_all_inventory_items()
        selected_item = next((it for it in items if str(it.get("id")) == str(selected_item_id) or str(it.get("sku", "")).upper() == str(selected_item_id).upper()), None)
    return build_overview_rag(selected_item), "overview"
