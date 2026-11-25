"use client";

import React, { useMemo, useState, useRef, useEffect, useCallback } from "react";
import { createPortal } from "react-dom";
import type { ForecastedItem, ForecastStatus } from "@/types/forecast";
import ForecastStatusBadge from "./ForecastStatusBadge";
import { WikiHover } from "@/wiki";
import {
  SearchIcon,
  FilterIcon,
  ArrowDownIcon,
  ArrowUpIcon,
  RefreshIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  GripVerticalIcon,
  SlidersIcon,
} from "../common/Icons";

interface ForecastTableProps {
  items: ForecastedItem[];
  onRerunForecast?: () => void;
  isRerunning?: boolean;
  selectedItemId?: string | null;
  onSelectItem?: (item: ForecastedItem) => void;
}

const DEFAULT_PAGE_SIZE = 5;
const STATUS_OPTIONS: Array<"All" | ForecastStatus> = [
  "All",
  "In Stock",
  "Monitor",
  "Reorder",
  "Critical",
  "Deadstock",
];

// Default priority order per business rules: Critical, Reorder, Monitor, Deadstock, In Stock
const DEFAULT_STATUS_ORDER: ForecastStatus[] = [
  "Critical",
  "Reorder",
  "Monitor",
  "Deadstock",
  "In Stock",
];

type ColumnKey = "name" | "forecast" | "stock" | "status";

interface ColumnDef {
  key: ColumnKey;
  label: string;
  isPrimary?: boolean;
  minTableWidth?: number; // threshold: table width below which column hides (right-to-left)
}

// Columns ordered from left to right; minTableWidth defines the right-to-left hiding threshold
const TABLE_COLUMNS: ColumnDef[] = [
  { key: "name", label: "Item name", isPrimary: true },
  { key: "forecast", label: "Total 14d forecasted", minTableWidth: 420 },
  { key: "stock", label: "On-hand stock", minTableWidth: 540 },
  { key: "status", label: "Status", minTableWidth: 680 },
];

const HIDE_PRIORITY_ORDER: ColumnKey[] = ["status", "stock", "forecast"];

export default function ForecastTable({
  items,
  onRerunForecast,
  isRerunning = false,
  selectedItemId,
  onSelectItem,
}: ForecastTableProps) {
  const [search, setSearch] = useState("");
  const [selectedStatus, setSelectedStatus] = useState<"All" | ForecastStatus>("All");
  const [selectedCategories, setSelectedCategories] = useState<string[]>([]);
  const [selectedWarehouses, setSelectedWarehouses] = useState<string[]>([]);
  const [isFilterOpen, setIsFilterOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [filterCoords, setFilterCoords] = useState<{ top: number; left: number } | null>(null);
  const [columnsCoords, setColumnsCoords] = useState<{ top: number; left: number } | null>(null);

  const filterDropdownRef = useRef<HTMLDivElement>(null);
  const columnsDropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setMounted(true);
  }, []);

  const updateFilterCoords = useCallback(() => {
    if (!filterRef.current) return;
    const buttonRect = filterRef.current.getBoundingClientRect();
    const container = filterRef.current.closest(".forecast-table-wrapper") || document.body;
    const containerRect = container.getBoundingClientRect();

    const dropdownWidth = 275;
    let left = buttonRect.left;

    // Constrain within middle table container if room permits
    if (containerRect.width >= dropdownWidth + 16) {
      if (left + dropdownWidth > containerRect.right - 8) {
        left = containerRect.right - dropdownWidth - 8;
      }
      if (left < containerRect.left + 8) {
        left = containerRect.left + 8;
      }
    } else {
      // Viewport safety boundary
      if (left + dropdownWidth > window.innerWidth - 12) {
        left = window.innerWidth - dropdownWidth - 12;
      }
      if (left < 12) {
        left = 12;
      }
    }

    setFilterCoords({
      top: buttonRect.bottom + 6,
      left,
    });
  }, []);

  const updateColumnsCoords = useCallback(() => {
    if (!columnsRef.current) return;
    const buttonRect = columnsRef.current.getBoundingClientRect();
    const container = columnsRef.current.closest(".forecast-table-wrapper") || document.body;
    const containerRect = container.getBoundingClientRect();

    const dropdownWidth = 240;
    let left = buttonRect.left;

    if (containerRect.width >= dropdownWidth + 16) {
      if (left + dropdownWidth > containerRect.right - 8) {
        left = containerRect.right - dropdownWidth - 8;
      }
      if (left < containerRect.left + 8) {
        left = containerRect.left + 8;
      }
    } else {
      if (left + dropdownWidth > window.innerWidth - 12) {
        left = window.innerWidth - dropdownWidth - 12;
      }
      if (left < 12) {
        left = 12;
      }
    }

    setColumnsCoords({
      top: buttonRect.bottom + 6,
      left,
    });
  }, []);
  const [sortBy, setSortBy] = useState<"forecast14d" | "onHandStock" | "name" | "status">("status");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("asc");
  const [statusPriorityOrder, setStatusPriorityOrder] = useState<ForecastStatus[]>([
    ...DEFAULT_STATUS_ORDER,
  ]);
  const [isStatusOrderOpen, setIsStatusOrderOpen] = useState(false);
  const [draggedIndex, setDraggedIndex] = useState<number | null>(null);
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [jumpPageInput, setJumpPageInput] = useState("");

  const [pageSize, setPageSize] = useState<number>(DEFAULT_PAGE_SIZE);
  const [pageSizeMode, setPageSizeMode] = useState<"auto" | number>("auto");
  const tbodyRef = useRef<HTMLTableSectionElement>(null);

  const [userColumnVisibility, setUserColumnVisibility] = useState<Record<ColumnKey, boolean>>({
    name: true,
    forecast: true,
    stock: true,
    status: true,
  });
  const [columnModes, setColumnModes] = useState<Record<ColumnKey, "auto" | "override">>({
    name: "auto",
    forecast: "auto",
    stock: "auto",
    status: "auto",
  });
  const [tableWidth, setTableWidth] = useState<number>(1000);
  const tableContainerRef = useRef<HTMLDivElement>(null);
  const [isColumnsOpen, setIsColumnsOpen] = useState(false);

  // Extract distinct categories from items (stdlib Set)
  const categories = useMemo(() => {
    const set = new Set<string>();
    items.forEach((it) => it.category && set.add(it.category));
    return ["All", ...Array.from(set).sort()];
  }, [items]);

  // Extract distinct warehouses from items (stdlib Set)
  const warehouses = useMemo(() => {
    const set = new Set<string>();
    items.forEach((it) => it.warehouse && set.add(it.warehouse));
    return ["All", ...Array.from(set).sort()];
  }, [items]);

  const filterRef = useRef<HTMLDivElement>(null);
  const columnsRef = useRef<HTMLDivElement>(null);
  const statusHeaderRef = useRef<HTMLTableCellElement>(null);

  // Measure table container width dynamically with ResizeObserver
  useEffect(() => {
    const el = tableContainerRef.current;
    if (!el) return;

    const updateWidth = () => {
      const w = el.clientWidth;
      if (w > 0) setTableWidth(w);
    };
    updateWidth();

    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const w = entry.contentRect.width;
        if (w > 0) setTableWidth(w);
      }
    });
    ro.observe(el);

    return () => ro.disconnect();
  }, []);

  // Priority order for hiding: right-to-left ("status" -> "stock" -> "forecast")


  // Target number of optional columns to hide based on current table width
  const targetHideCount = useMemo(() => {
    if (tableWidth >= 680) return 0;
    if (tableWidth >= 540) return 1;
    if (tableWidth >= 420) return 2;
    return 3;
  }, [tableWidth]);

  // Compute set of auto-hidden columns:
  // If a column is in "override" mode and active, skip it and hide the nearest "auto" active column!
  const autoHiddenSet = useMemo(() => {
    const hidden = new Set<ColumnKey>();
    let remainingToHide = targetHideCount;

    if (remainingToHide <= 0) return hidden;

    for (const key of HIDE_PRIORITY_ORDER) {
      if (remainingToHide <= 0) break;

      // Only consider columns currently enabled by user
      if (!userColumnVisibility[key]) continue;

      // If column is in "override" mode, skip it!
      if (columnModes[key] === "override") {
        continue;
      }

      // Hide the nearest "auto" mode active column
      hidden.add(key);
      remainingToHide--;
    }

    return hidden;
  }, [targetHideCount, userColumnVisibility, columnModes]);

  // Determine actively visible columns
  const visibleColumns = useMemo(() => {
    return TABLE_COLUMNS.filter((col) => {
      if (col.isPrimary) return true;
      if (!userColumnVisibility[col.key]) return false;
      if (autoHiddenSet.has(col.key)) return false;
      return true;
    });
  }, [userColumnVisibility, autoHiddenSet]);

  const hiddenColumnsCount = TABLE_COLUMNS.length - visibleColumns.length;

  // Toggle column checkbox: if auto-hidden and user enables it, set to "override"
  const handleToggleColumnCheckbox = (key: ColumnKey) => {
    const isCurrentlyHidden = !userColumnVisibility[key] || autoHiddenSet.has(key);

    if (isCurrentlyHidden) {
      setUserColumnVisibility((prev) => ({ ...prev, [key]: true }));
      if (targetHideCount > 0) {
        setColumnModes((prev) => ({ ...prev, [key]: "override" }));
      }
    } else {
      setUserColumnVisibility((prev) => ({ ...prev, [key]: false }));
    }
  };

  // Toggle column mode between "auto" and "override"
  const handleToggleColumnMode = (key: ColumnKey, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();

    const currentMode = columnModes[key] || "auto";
    const nextMode = currentMode === "auto" ? "override" : "auto";

    setColumnModes((prev) => ({
      ...prev,
      [key]: nextMode,
    }));
    if (nextMode === "override") {
      setUserColumnVisibility((prev) => ({ ...prev, [key]: true }));
    }
  };

  const [autoPageSize, setAutoPageSize] = useState<number>(DEFAULT_PAGE_SIZE);

  // Dynamic page size calculation: measure table container height to fit rows with little to no overflow
  useEffect(() => {
    const container = tableContainerRef.current;
    if (!container) return;

    const calculateDynamicRows = () => {
      const containerHeight = container.clientHeight;
      if (containerHeight <= 80) return;

      const thead = container.querySelector("thead") as HTMLElement | null;
      const theadHeight = thead && thead.offsetHeight > 0 ? thead.offsetHeight : 32;
      const availableHeight = containerHeight - theadHeight;

      const firstRow = container.querySelector("tr.forecast-row") as HTMLElement | null;
      // In compact multi-pane mode, row height with padding is ~44-46px; in standard mode ~48-50px
      const rowHeight =
        firstRow && firstRow.offsetHeight > 25
          ? firstRow.offsetHeight
          : 44;

      // Smart dynamic row count:
      // If remaining height after N rows has room for at least 22px (about half a row),
      // allow displaying N + 1 rows so rows fill the space gracefully with zero gap.
      const rawCount = availableHeight / rowHeight;
      const floorCount = Math.floor(rawCount);
      const remainder = availableHeight - floorCount * rowHeight;
      const dynamicCount = Math.max(3, remainder >= 22 ? floorCount + 1 : floorCount);

      setAutoPageSize(dynamicCount);
      if (pageSizeMode === "auto") {
        setPageSize(dynamicCount);
      }
    };

    calculateDynamicRows();

    const resizeObserver = new ResizeObserver(() => {
      calculateDynamicRows();
    });
    resizeObserver.observe(container);

    // Re-check after layout commit to get real row and thead dimensions
    const rafId = requestAnimationFrame(() => {
      calculateDynamicRows();
    });

    return () => {
      cancelAnimationFrame(rafId);
      resizeObserver.disconnect();
    };
  }, [pageSizeMode, items.length]);

  // Auto-calculate portal coordinates on open, scroll, or resize
  useEffect(() => {
    if (isFilterOpen) updateFilterCoords();
  }, [isFilterOpen, updateFilterCoords]);

  useEffect(() => {
    if (isColumnsOpen) updateColumnsCoords();
  }, [isColumnsOpen, updateColumnsCoords]);

  useEffect(() => {
    if (!isFilterOpen && !isColumnsOpen) return;
    const handleReposition = () => {
      if (isFilterOpen) updateFilterCoords();
      if (isColumnsOpen) updateColumnsCoords();
    };
    window.addEventListener("resize", handleReposition);
    window.addEventListener("scroll", handleReposition, true);
    return () => {
      window.removeEventListener("resize", handleReposition);
      window.removeEventListener("scroll", handleReposition, true);
    };
  }, [isFilterOpen, isColumnsOpen, updateFilterCoords, updateColumnsCoords]);

  // Close filter and status reorder dropdowns when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      const target = event.target as Node;
      if (
        filterRef.current &&
        !filterRef.current.contains(target) &&
        (!filterDropdownRef.current || !filterDropdownRef.current.contains(target))
      ) {
        setIsFilterOpen(false);
      }
      if (
        columnsRef.current &&
        !columnsRef.current.contains(target) &&
        (!columnsDropdownRef.current || !columnsDropdownRef.current.contains(target))
      ) {
        setIsColumnsOpen(false);
      }
      if (statusHeaderRef.current && !statusHeaderRef.current.contains(target)) {
        setIsStatusOrderOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // Filter and sort items list
  const filteredAndSortedItems = useMemo(() => {
    let result = [...items];

    // Filter by search query (name or SKU)
    if (search.trim()) {
      const query = search.trim().toLowerCase();
      result = result.filter(
        (item) =>
          item.name.toLowerCase().includes(query) ||
          item.sku.toLowerCase().includes(query)
      );
    }

    // Filter by business status
    if (selectedStatus !== "All") {
      result = result.filter((item) => item.status === selectedStatus);
    }

    // Filter by category (allow multiple selection)
    if (selectedCategories.length > 0) {
      result = result.filter((item) => item.category && selectedCategories.includes(item.category));
    }

    // Filter by warehouse (allow multiple selection)
    if (selectedWarehouses.length > 0) {
      result = result.filter((item) => item.warehouse && selectedWarehouses.includes(item.warehouse));
    }

    // Sorting logic
    result.sort((a, b) => {
      let comparison = 0;
      if (sortBy === "name") {
        comparison = a.name.localeCompare(b.name);
      } else if (sortBy === "status") {
        const indexA = statusPriorityOrder.indexOf(a.status);
        const indexB = statusPriorityOrder.indexOf(b.status);
        const rankA = indexA === -1 ? 999 : indexA;
        const rankB = indexB === -1 ? 999 : indexB;
        comparison = rankA - rankB;
        if (comparison === 0) {
          // When same status, tie-break by highest forecasted demand first
          comparison = b.forecast14d - a.forecast14d;
        }
      } else {
        comparison = a[sortBy] - b[sortBy];
      }
      return sortOrder === "desc" ? -comparison : comparison;
    });

    return result;
  }, [items, search, selectedStatus, selectedCategories, selectedWarehouses, sortBy, sortOrder, statusPriorityOrder]);

  // Pagination calculation
  const totalPages = Math.max(1, Math.ceil(filteredAndSortedItems.length / pageSize));
  const safePage = Math.min(currentPage, totalPages);
  const startIndex = (safePage - 1) * pageSize;
  const paginatedItems = filteredAndSortedItems.slice(startIndex, startIndex + pageSize);

  if (currentPage > totalPages) {
    setCurrentPage(totalPages);
  }

  function handleSort(column: "forecast14d" | "onHandStock" | "name" | "status") {
    if (column === "status") {
      setSortBy("status");
      setIsStatusOrderOpen((prev) => !prev);
      return;
    }
    setIsStatusOrderOpen(false);
    if (sortBy === column) {
      if (sortOrder === "desc") {
        setSortOrder("asc");
      } else {
        // Return to normal (status priority order)
        setSortBy("status");
        setSortOrder("asc");
      }
    } else {
      setSortBy(column);
      setSortOrder("desc");
    }
  }

  // Drag & drop status priority reordering
  const handleDragStart = (e: React.DragEvent, index: number) => {
    setDraggedIndex(index);
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", `${index}`);
  };

  const handleDragOver = (e: React.DragEvent, index: number) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    if (dragOverIndex !== index) {
      setDragOverIndex(index);
    }
  };

  const handleDrop = (e: React.DragEvent, targetIndex: number) => {
    e.preventDefault();
    if (draggedIndex === null || draggedIndex === targetIndex) {
      setDraggedIndex(null);
      setDragOverIndex(null);
      return;
    }
    const updated = [...statusPriorityOrder];
    const [moved] = updated.splice(draggedIndex, 1);
    updated.splice(targetIndex, 0, moved);
    setStatusPriorityOrder(updated);
    setSortBy("status");
    setDraggedIndex(null);
    setDragOverIndex(null);
  };

  const handleDragEnd = () => {
    setDraggedIndex(null);
    setDragOverIndex(null);
  };

  const handleMoveStatus = (index: number, direction: "up" | "down") => {
    const targetIndex = direction === "up" ? index - 1 : index + 1;
    if (targetIndex < 0 || targetIndex >= statusPriorityOrder.length) return;
    const updated = [...statusPriorityOrder];
    const [moved] = updated.splice(index, 1);
    updated.splice(targetIndex, 0, moved);
    setStatusPriorityOrder(updated);
    setSortBy("status");
  };

  const handleResetStatusOrder = () => {
    setStatusPriorityOrder([...DEFAULT_STATUS_ORDER]);
    setSortBy("status");
    setSortOrder("asc");
  };

  function handleResetFilters() {
    setSearch("");
    setSelectedStatus("All");
    setSelectedCategories([]);
    setSelectedWarehouses([]);
    setCurrentPage(1);
    setSortBy("status");
    setSortOrder("asc");
    setStatusPriorityOrder([...DEFAULT_STATUS_ORDER]);
  }



  const renderHeaderCell = (col: ColumnDef) => {
    switch (col.key) {
      case "name":
        return (
          <th
            key="name"
            className={`th-item-name ${sortBy === "name" ? "is-sorted" : ""}`}
            scope="col"
          >
            <button
              type="button"
              className="th-sort-btn"
              onClick={() => handleSort("name")}
            >
              <span>Item name</span>
              {sortBy === "name" && (
                sortOrder === "desc" ? <ArrowDownIcon /> : <ArrowUpIcon />
              )}
            </button>
          </th>
        );

      case "forecast":
        return (
          <th
            key="forecast"
            className={`th-forecast ${sortBy === "forecast14d" ? "is-sorted" : ""}`}
            scope="col"
          >
            <button
              type="button"
              className="th-sort-btn"
              onClick={() => handleSort("forecast14d")}
            >
              <WikiHover term="forecast">
                <span>Total 14d forecasted</span>
              </WikiHover>
              {sortBy === "forecast14d" ? (
                sortOrder === "desc" ? <ArrowDownIcon /> : <ArrowUpIcon />
              ) : (
                <ArrowDownIcon className="th-sort-hint" />
              )}
            </button>
          </th>
        );

      case "stock":
        return (
          <th
            key="stock"
            className={`th-stock ${sortBy === "onHandStock" ? "is-sorted" : ""}`}
            scope="col"
          >
            <button
              type="button"
              className="th-sort-btn"
              onClick={() => handleSort("onHandStock")}
            >
              <WikiHover term="stock">
                <span>On-hand stock</span>
              </WikiHover>
              {sortBy === "onHandStock" && (
                sortOrder === "desc" ? <ArrowDownIcon /> : <ArrowUpIcon />
              )}
            </button>
          </th>
        );

      case "status":
        return (
          <th
            key="status"
            className={`th-status ${sortBy === "status" ? "is-sorted" : ""}`}
            scope="col"
            ref={statusHeaderRef}
          >
            <div className="th-status-wrapper">
              <button
                type="button"
                className="th-sort-btn th-status-header-btn"
                onClick={() => handleSort("status")}
                aria-expanded={isStatusOrderOpen}
                aria-haspopup="dialog"
                title="Click to sort by status or customize order"
              >
                <span>Status</span>
                <span className="th-status-tune-pill" title="Drag & customize status order">
                  <SlidersIcon size={12} />
                </span>
              </button>

              {isStatusOrderOpen && (
                <div
                  className="status-order-dropdown"
                  role="dialog"
                  aria-label="Status priority sort order"
                  onClick={(e) => e.stopPropagation()}
                >
                  <div className="status-order-header">
                    <div className="status-order-title-group">
                      <span className="status-order-title">Status Sort Order</span>
                      <span className="status-order-subtitle">Drag rows to adjust priority</span>
                    </div>
                    <button
                      type="button"
                      className="status-order-reset-btn"
                      onClick={handleResetStatusOrder}
                      title="Reset to default order (Critical, Reorder, Monitor, Deadstock, In Stock)"
                    >
                      Reset
                    </button>
                  </div>

                  <div className="status-order-list" role="list">
                    {statusPriorityOrder.map((status, index) => (
                      <div
                        key={status}
                        role="listitem"
                        draggable
                        onDragStart={(e) => handleDragStart(e, index)}
                        onDragOver={(e) => handleDragOver(e, index)}
                        onDrop={(e) => handleDrop(e, index)}
                        onDragEnd={handleDragEnd}
                        className={`status-order-item ${
                          draggedIndex === index ? "is-dragging" : ""
                        } ${dragOverIndex === index ? "is-drag-over" : ""}`}
                      >
                        <span className="status-order-grip" title="Hold and drag to reorder">
                          <GripVerticalIcon size={13} />
                        </span>
                        <span className="status-order-rank">{index + 1}</span>
                        <div className="status-order-badge-wrap">
                          <ForecastStatusBadge status={status} />
                        </div>
                        <div className="status-order-arrows">
                          <button
                            type="button"
                            className="status-order-arrow-btn"
                            disabled={index === 0}
                            onClick={(e) => {
                              e.stopPropagation();
                              handleMoveStatus(index, "up");
                            }}
                            title="Move up"
                            aria-label={`Move ${status} up`}
                          >
                            ▲
                          </button>
                          <button
                            type="button"
                            className="status-order-arrow-btn"
                            disabled={index === statusPriorityOrder.length - 1}
                            onClick={(e) => {
                              e.stopPropagation();
                              handleMoveStatus(index, "down");
                            }}
                            title="Move down"
                            aria-label={`Move ${status} down`}
                          >
                            ▼
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>

                  <div className="status-order-footer">
                    <div className="status-order-direction">
                      <span className="status-order-dir-label">Order:</span>
                      <button
                        type="button"
                        className={`status-order-dir-btn ${
                          sortOrder === "asc" ? "is-active" : ""
                        }`}
                        onClick={() => {
                          setSortBy("status");
                          setSortOrder("asc");
                        }}
                      >
                        1 → 5
                      </button>
                      <button
                        type="button"
                        className={`status-order-dir-btn ${
                          sortOrder === "desc" ? "is-active" : ""
                        }`}
                        onClick={() => {
                          setSortBy("status");
                          setSortOrder("desc");
                        }}
                      >
                        5 → 1
                      </button>
                    </div>
                    <button
                      type="button"
                      className="status-order-done-btn"
                      onClick={() => setIsStatusOrderOpen(false)}
                    >
                      Done
                    </button>
                  </div>
                </div>
              )}
            </div>
          </th>
        );
    }
  };

  const renderDataCell = (key: ColumnKey, item: ForecastedItem) => {
    switch (key) {
      case "name":
        return (
          <td key="name" className="td-item-info">
            <div className="item-meta">
              <div className="item-initial-box">
                <span>{item.name.charAt(0)}</span>
              </div>
              <div className="item-text">
                <div className="item-name-row">
                  <span className="item-name">{item.name}</span>
                  <span
                    className={`item-shap-dot is-${
                      item.shap_status === "completed" || (item.grouped_drivers && item.grouped_drivers.length > 0)
                        ? "ready"
                        : item.shap_status === "running" || item.shap_status === "queued"
                        ? "pending"
                        : "grey"
                    }`}
                    title={
                      item.shap_status === "completed" || (item.grouped_drivers && item.grouped_drivers.length > 0)
                        ? "Forecast Drivers Ready"
                        : item.shap_status === "running" || item.shap_status === "queued"
                        ? "Calculating Forecast Drivers"
                        : "Forecast Drivers Pending"
                    }
                  />
                </div>
                <div
                  className="item-sku-row"
                  title={[
                    `SKU: ${item.sku}`,
                    item.category ? `Category: ${item.category}` : "",
                    item.warehouse ? `Warehouse: ${item.warehouse}` : "",
                  ].filter(Boolean).join(" · ")}
                >
                  <span className="item-sku">{item.sku}</span>
                </div>
              </div>
            </div>
          </td>
        );

      case "forecast":
        return (
          <td key="forecast" className="td-forecast-value">
            <WikiHover term="forecast">
              <span>{Math.ceil(item.forecast14d).toLocaleString()}</span>
            </WikiHover>
          </td>
        );

      case "stock":
        return (
          <td key="stock" className="td-stock-value">
            <WikiHover term="stock">
              <span>{item.onHandStock.toLocaleString()}</span>
            </WikiHover>
          </td>
        );

      case "status":
        return (
          <td key="status" className="td-status-badge">
            <ForecastStatusBadge status={item.status} />
          </td>
        );
    }
  };

  return (
    <div className="forecast-table-wrapper">
      {/* 1. Control Toolbar */}
      <div className="forecast-toolbar">
        <div className="forecast-toolbar-title">
          <h2>Forecasted Items</h2>

        </div>

        <div className="forecast-toolbar-actions">
          {/* Search Input */}
          <div className="forecast-search-box">
            <SearchIcon className="search-icon" />
            <input
              type="text"
              placeholder="Search item name..."
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setCurrentPage(1);
              }}
              aria-label="Search item name"
            />
            {search && (
              <button
                type="button"
                className="search-clear-btn"
                onClick={() => setSearch("")}
                aria-label="Clear search"
              >
                ✕
              </button>
            )}
          </div>

          {/* Filters Button & Popover */}
          <div className="forecast-filter-menu" ref={filterRef}>
            <button
              type="button"
              className={`forecast-filter-btn ${
                selectedStatus !== "All" || selectedCategories.length > 0 || selectedWarehouses.length > 0 ? "is-active" : ""
              }`}
              onClick={() => {
                updateFilterCoords();
                setIsFilterOpen((prev) => !prev);
              }}
              aria-expanded={isFilterOpen}
              aria-haspopup="true"
            >
              <FilterIcon />
              <span>Filters</span>
              {(selectedStatus !== "All" || selectedCategories.length > 0 || selectedWarehouses.length > 0) && (
                <span className="filter-status-dot" />
              )}
            </button>

            {mounted && isFilterOpen && filterCoords && createPortal(
              <div
                ref={filterDropdownRef}
                className="forecast-filter-dropdown is-portal"
                role="menu"
                style={{
                  position: "fixed",
                  top: `${filterCoords.top}px`,
                  left: `${filterCoords.left}px`,
                  width: "275px",
                  zIndex: 99999,
                }}
              >
                <div className="filter-dropdown-header">Filter by Status</div>
                {STATUS_OPTIONS.map((status) => {
                  const count =
                    status === "All"
                      ? items.length
                      : items.filter((item) => item.status === status).length;

                  return (
                    <button
                      key={status}
                      type="button"
                      className={`filter-dropdown-item ${selectedStatus === status ? "is-selected" : ""}`}
                      onClick={() => {
                        setSelectedStatus(status);
                        setCurrentPage(1);
                      }}
                      role="menuitem"
                    >
                      <span>{status}</span>
                      <span className="filter-item-count">{count}</span>
                    </button>
                  );
                })}

                <div className="filter-dropdown-divider" />
                <div className="filter-dropdown-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span>Filter by Category</span>
                  {selectedCategories.length > 0 && (
                    <button
                      type="button"
                      onClick={() => {
                        setSelectedCategories([]);
                        setCurrentPage(1);
                      }}
                      style={{
                        background: "none",
                        border: "none",
                        color: "#2563eb",
                        fontSize: "10.5px",
                        fontWeight: 600,
                        cursor: "pointer",
                        padding: 0,
                        textTransform: "none",
                      }}
                      title="Clear selected categories"
                    >
                      Clear ({selectedCategories.length})
                    </button>
                  )}
                </div>
                <div className="filter-tags-grid">
                  {categories.map((cat) => {
                    const isAll = cat === "All";
                    const isSelected = isAll
                      ? selectedCategories.length === 0
                      : selectedCategories.includes(cat);

                    return (
                      <button
                        key={cat}
                        type="button"
                        className={`filter-category-tag ${isSelected ? "is-selected" : ""}`}
                        onClick={() => {
                          if (isAll) {
                            setSelectedCategories([]);
                          } else {
                            setSelectedCategories((prev) =>
                              prev.includes(cat)
                                ? prev.filter((c) => c !== cat)
                                : [...prev, cat]
                            );
                          }
                          setCurrentPage(1);
                        }}
                      >
                        {cat}
                      </button>
                    );
                  })}
                </div>

                <div className="filter-dropdown-divider" />
                <div className="filter-dropdown-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span>Filter by Warehouse</span>
                  {selectedWarehouses.length > 0 && (
                    <button
                      type="button"
                      onClick={() => {
                        setSelectedWarehouses([]);
                        setCurrentPage(1);
                      }}
                      style={{
                        background: "none",
                        border: "none",
                        color: "#2563eb",
                        fontSize: "10.5px",
                        fontWeight: 600,
                        cursor: "pointer",
                        padding: 0,
                        textTransform: "none",
                      }}
                      title="Clear selected warehouses"
                    >
                      Clear ({selectedWarehouses.length})
                    </button>
                  )}
                </div>
                <div className="filter-tags-grid">
                  {warehouses.map((wh) => {
                    const isAll = wh === "All";
                    const isSelected = isAll
                      ? selectedWarehouses.length === 0
                      : selectedWarehouses.includes(wh);

                    return (
                      <button
                        key={wh}
                        type="button"
                        className={`filter-category-tag ${isSelected ? "is-selected" : ""}`}
                        onClick={() => {
                          if (isAll) {
                            setSelectedWarehouses([]);
                          } else {
                            setSelectedWarehouses((prev) =>
                              prev.includes(wh)
                                ? prev.filter((w) => w !== wh)
                                : [...prev, wh]
                            );
                          }
                          setCurrentPage(1);
                        }}
                      >
                        {wh}
                      </button>
                    );
                  })}
                </div>
              </div>,
              document.body
            )}
          </div>

          {/* Dynamic Columns Visibility Menu */}
          <div className="forecast-filter-menu" ref={columnsRef}>
            <button
              type="button"
              className={`forecast-filter-btn ${hiddenColumnsCount > 0 ? "is-active" : ""}`}
              onClick={() => {
                updateColumnsCoords();
                setIsColumnsOpen((prev) => !prev);
              }}
              aria-expanded={isColumnsOpen}
              aria-haspopup="true"
              title="Dynamically show or hide columns"
            >
              <SlidersIcon size={13} />
              <span>Columns</span>
              {hiddenColumnsCount > 0 && (
                <span className="filter-count-badge">
                  {hiddenColumnsCount} hidden
                </span>
              )}
            </button>

            {mounted && isColumnsOpen && columnsCoords && createPortal(
              <div
                ref={columnsDropdownRef}
                className="forecast-filter-dropdown is-portal"
                role="menu"
                style={{
                  position: "fixed",
                  top: `${columnsCoords.top}px`,
                  left: `${columnsCoords.left}px`,
                  width: "240px",
                  zIndex: 99999,
                }}
              >
                <div className="filter-dropdown-header">Visible Columns</div>
                {TABLE_COLUMNS.filter((c) => !c.isPrimary).map((col) => {
                  const isVisible = visibleColumns.some((c) => c.key === col.key);
                  const mode = columnModes[col.key] || "auto";
                  const isAutoHidden = autoHiddenSet.has(col.key);

                  return (
                    <label key={col.key} className="column-toggle-item">
                      <input
                        type="checkbox"
                        checked={isVisible}
                        onChange={() => handleToggleColumnCheckbox(col.key)}
                      />
                      <span>{col.label}</span>
                      <button
                        type="button"
                        className={`column-mode-tag is-${mode}`}
                        onClick={(e) => handleToggleColumnMode(col.key, e)}
                        title={
                          mode === "override"
                            ? "Override mode: forced visible. Click to switch to Auto."
                            : isAutoHidden
                            ? "Auto mode: hidden by table size. Click to Override."
                            : "Auto mode: visible. Click to switch to Override."
                        }
                      >
                        {mode === "override" ? "Override" : "Auto"}
                      </button>
                    </label>
                  );
                })}
              </div>,
              document.body
            )}
          </div>

          {/* Re-run Forecast Button */}
          {onRerunForecast && (
            <button
              type="button"
              className="forecast-rerun-btn"
              onClick={onRerunForecast}
              disabled={isRerunning}
              title="Re-run forecast models"
              aria-label="Re-run Forecast"
            >
              <RefreshIcon className={isRerunning ? "is-spinning" : ""} />
              <span className="btn-text">Re-run</span>
            </button>
          )}
        </div>
      </div>

      {/* 2. Data Table */}
      <div className="forecast-table-container" ref={tableContainerRef}>
        <table className="forecast-table" aria-label="Forecasted items table">
          <thead>
            <tr>
              {visibleColumns.map((col) => renderHeaderCell(col))}
            </tr>
          </thead>
          <tbody ref={tbodyRef}>
            {paginatedItems.length === 0 ? (
              <tr>
                <td
                  colSpan={visibleColumns.length}
                  className="forecast-empty-td"
                >
                  <div className="table-empty-message">
                    <p>No items found matching your filters.</p>
                    <button
                      type="button"
                      className="reset-filter-link"
                      onClick={handleResetFilters}
                    >
                      Reset filters
                    </button>
                  </div>
                </td>
              </tr>
            ) : (
              paginatedItems.map((item) => (
                <tr
                  key={item.id}
                  className={`forecast-row ${selectedItemId === item.id ? "is-selected" : ""}`}
                  onClick={() => onSelectItem?.(item)}
                >
                  {visibleColumns.map((col) => renderDataCell(col.key, item))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* 3. Pagination calculation (Pagination) */}
      <div className="forecast-pagination-bar">
        <div className="pagination-info">
          {filteredAndSortedItems.length > 0 ? (
            <span>
              Showing <strong>{startIndex + 1}</strong> -{" "}
              <strong>
                {Math.min(startIndex + pageSize, filteredAndSortedItems.length)}
              </strong>{" "}
              of <strong>{filteredAndSortedItems.length}</strong> items
            </span>
          ) : (
            <span>0 items</span>
          )}
        </div>

        {/* Dynamic Page Size Selector */}
        <div className="pagination-size-selector">
          <span className="pagination-size-label">Per page:</span>
          <select
            value={pageSizeMode}
            onChange={(e) => {
              const val = e.target.value;
              if (val === "auto") {
                setPageSizeMode("auto");
                setPageSize(autoPageSize);
              } else {
                const num = parseInt(val, 10);
                setPageSizeMode(num);
                setPageSize(num);
              }
              setCurrentPage(1);
            }}
            className="pagination-size-select"
            title="Choose items per page or Auto-fit"
            aria-label="Items per page"
          >
            <option value="auto">Auto ({autoPageSize})</option>
            <option value="5">5</option>
            <option value="10">10</option>
            <option value="15">15</option>
            <option value="20">20</option>
            <option value="50">50</option>
          </select>
        </div>

        {totalPages > 1 && (() => {
          const handleJump = (e: React.FormEvent) => {
            e.preventDefault();
            const val = parseInt(jumpPageInput.trim(), 10);
            if (!isNaN(val) && val >= 1 && val <= totalPages) {
              setCurrentPage(val);
              setJumpPageInput("");
            }
          };

          const isIntermediatePage = safePage > 1 && safePage < totalPages;

          return (
            <div className="forecast-pagination" role="navigation" aria-label="Pagination">
              {/* Previous page arrow */}
              <button
                type="button"
                className="pagination-btn pagination-arrow-btn"
                onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                disabled={safePage <= 1}
                aria-label="Previous page"
              >
                <ChevronLeftIcon />
              </button>

              {/* Min page (1) */}
              <button
                type="button"
                className={`pagination-btn pagination-num-btn ${safePage === 1 ? "is-active" : ""}`}
                onClick={() => setCurrentPage(1)}
                aria-current={safePage === 1 ? "page" : undefined}
                title="Go to first page"
              >
                1
              </button>

              {/* ... Page input ... */}
              {totalPages > 2 && (
                <>
                  <span className="pagination-ellipsis">…</span>
                  <form className="pagination-jump-form" onSubmit={handleJump}>
                    <input
                      type="number"
                      min={1}
                      max={totalPages}
                      placeholder={isIntermediatePage ? String(safePage) : "Page"}
                      title={`Current / Jump Page (1-${totalPages}). Press Enter to jump.`}
                      aria-label="Jump to page"
                      className={`pagination-page-input ${isIntermediatePage ? "is-active" : ""}`}
                      value={jumpPageInput}
                      onChange={(e) => setJumpPageInput(e.target.value)}
                    />
                  </form>
                  <span className="pagination-ellipsis">…</span>
                </>
              )}

              {/* Max page (totalPages) */}
              <button
                type="button"
                className={`pagination-btn pagination-num-btn ${safePage === totalPages ? "is-active" : ""}`}
                onClick={() => setCurrentPage(totalPages)}
                aria-current={safePage === totalPages ? "page" : undefined}
                title={`Go to last page (${totalPages})`}
              >
                {totalPages}
              </button>

              {/* Next page arrow */}
              <button
                type="button"
                className="pagination-btn pagination-arrow-btn"
                onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                disabled={safePage >= totalPages}
                aria-label="Next page"
              >
                <ChevronRightIcon />
              </button>
            </div>
          );
        })()}
      </div>
    </div>
  );
}
