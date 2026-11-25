import { useState, useEffect, useRef, useMemo } from "react";
import type { ForecastedItem } from "@/types/forecast";
import { ChevronRightIcon, CloseIcon, Sparkle, PackageIcon, CheckIcon, AlertOctagonIcon } from "./common/Icons";
import ForecastStatusBadge from "./workspace/ForecastStatusBadge";
import { WikiHover } from "@/wiki";
import ForecastBreakdownChart from "./leftpanel/ForecastBreakdownChart";
import DailyForecastLineChart from "./leftpanel/DailyForecastLineChart";
import TreeShapComputingVisualizer from "./leftpanel/TreeShapComputingVisualizer";

interface LeftPanelProps {
  onRetryShap?: () => void;
  open: boolean;
  onToggle: () => void;
  onClose: () => void;
  selectedItem?: ForecastedItem | null;
  language?: "en" | "vi";
  onAskAssistant?: (item: ForecastedItem, prompt?: string) => void;
}

export default function LeftPanel({
  open,
  onToggle,
  onClose,
  selectedItem,
  language = "en",
  onAskAssistant,
  onRetryShap,
}: LeftPanelProps) {
  const [activeTab, setActiveTab] = useState<"breakdown" | "detail">("detail");
  const [elapsedMs, setElapsedMs] = useState(0);
  const startRef = useRef<number | null>(null);
  const prevItemIdRef = useRef<string | null>(null);

  const currentItemId = selectedItem ? String(selectedItem.id) : null;

  const shapStatus =
    selectedItem?.shap_status ||
    (selectedItem?.grouped_drivers && selectedItem.grouped_drivers.length > 0
      ? "completed"
      : "not_requested");

  // Reset tab and timer only when switching to a DIFFERENT item
  useEffect(() => {
    if (currentItemId !== prevItemIdRef.current) {
      prevItemIdRef.current = currentItemId;
      startRef.current = null;
      setElapsedMs(0);
      if (selectedItem) {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setActiveTab("breakdown");
      }
    }
  }, [currentItemId, selectedItem]);

  // Maintain smooth continuous timer while current item is queued/running
  useEffect(() => {
    if (!currentItemId) {
      startRef.current = null;
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setElapsedMs(0);
      return;
    }

    if (shapStatus === "running" || shapStatus === "queued") {
      if (!startRef.current) {
        startRef.current = Date.now();
      }
      const interval = setInterval(() => {
        if (startRef.current) {
          setElapsedMs(Date.now() - startRef.current);
        }
      }, 100);
      return () => clearInterval(interval);
    } else {
      startRef.current = null;
      setElapsedMs(0);
    }
  }, [currentItemId, shapStatus]);

  const progressPct = useMemo(() => {
    if (shapStatus === "completed") return 100;
    if (shapStatus === "failed") return 0;
    const sec = elapsedMs / 1000;
    if (shapStatus === "queued") {
      return Math.min(20, Math.round(sec * 10));
    }
    return Math.min(95, Math.round(15 + 80 * (1 - Math.exp(-sec / 1.5))));
  }, [shapStatus, elapsedMs]);

  return (
    <>
      {open && (
        <div
          className="chat-backdrop"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      <div className="left-slot">
        <button
          type="button"
          className={`left-toggle ${open ? "is-open" : ""}`}
          onClick={onToggle}
          aria-expanded={open}
          aria-controls="left-side-panel"
          aria-label={open ? "Close side panel" : "Open side panel"}
          title={open ? "Close side panel" : "Open side panel"}
        >
          {open ? <CloseIcon size={18} /> : <ChevronRightIcon size={20} />}
        </button>

        <aside
          id="left-side-panel"
          className="left-panel"
          inert={!open}
          aria-hidden={!open}
          aria-label="Item details panel"
        >
          <div className="chat-header left-panel-header">
            <span className="left-panel-title-icon">
              <PackageIcon size={16} />
            </span>
            <div className="chat-header-title">
              <h2>Item Details</h2>
            </div>
            {selectedItem && onAskAssistant && (
              <button
                type="button"
                className="left-panel-ask-btn"
                onClick={() => onAskAssistant(selectedItem)}
                title={`Ask Assistant to analyze ${selectedItem.name}`}
              >
                <Sparkle size={13} />
                <span>Ask Assistant</span>
              </button>
            )}
          </div>
          <div className="left-panel-body">
            {selectedItem ? (
              <>
                {/* Compact Item Header & Key Stats */}
                <div className="item-detail-content">
                  <div className="item-detail-header">
                    <div className="item-initial-box">
                      <span>{selectedItem.name.charAt(0)}</span>
                    </div>
                    <div className="item-detail-header-info">
                      <div className="item-detail-name-row">
                        <h3 className="item-detail-name" title={selectedItem.name}>{selectedItem.name}</h3>
                        <ForecastStatusBadge status={selectedItem.status} />
                      </div>
                      <div className="item-detail-sku-row">
                        <span className="item-detail-sku">{selectedItem.sku}</span>
                        {selectedItem.category && (
                          <>
                            <span className="meta-sep" aria-hidden="true">·</span>
                            <span className="item-meta-category" title={`Category: ${selectedItem.category}`}>
                              {selectedItem.category}
                            </span>
                          </>
                        )}
                        {selectedItem.warehouse && (
                          <>
                            <span className="meta-sep" aria-hidden="true">·</span>
                            <span className="item-meta-warehouse" title={`Warehouse: ${selectedItem.warehouse}`}>
                              {selectedItem.warehouse}
                            </span>
                          </>
                        )}
                        {selectedItem.price != null && (
                          <>
                            <span className="meta-sep" aria-hidden="true">·</span>
                            <span
                              className="item-meta-price"
                              title={`Price: ${selectedItem.price.toLocaleString("vi-VN", { maximumFractionDigits: 2 })} K VND`}
                            >
                              {selectedItem.price.toLocaleString("vi-VN", { maximumFractionDigits: 2 })} K VND
                            </span>
                          </>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Compact 1-Row 4-Col Metric Strip */}
                  <div className="item-detail-metric-strip">
                    <div className="item-metric-strip-col">
                      <WikiHover term="forecast" className="item-metric-strip-inner">
                        <span className="item-metric-strip-label">14d Forecast</span>
                        <span className="item-metric-strip-val is-forecast">
                          {Math.ceil(selectedItem.forecast14d).toLocaleString()}
                        </span>
                      </WikiHover>
                    </div>

                    <div className="item-metric-strip-col">
                      <WikiHover term="stock" className="item-metric-strip-inner">
                        <span className="item-metric-strip-label">On-hand Stock</span>
                        <span className="item-metric-strip-val is-stock">
                          {selectedItem.onHandStock.toLocaleString()}
                        </span>
                      </WikiHover>
                    </div>

                    <div className="item-metric-strip-col">
                      <WikiHover term="reorderPoint" className="item-metric-strip-inner">
                        <span className="item-metric-strip-label">Reorder Point</span>
                        <span className="item-metric-strip-val is-rop">
                          {selectedItem.reorderPoint !== undefined ? Math.ceil(selectedItem.reorderPoint).toLocaleString() : "N/A"}
                        </span>
                      </WikiHover>
                    </div>

                    <div className="item-metric-strip-col">
                      <WikiHover term="safetyStock" className="item-metric-strip-inner">
                        <span className="item-metric-strip-label">Safety Stock</span>
                        <span className="item-metric-strip-val is-safety">
                          {selectedItem.safetyStock !== undefined ? Math.ceil(selectedItem.safetyStock).toLocaleString() : "N/A"}
                        </span>
                      </WikiHover>
                    </div>
                  </div>
                </div>

                {/* Tabs taking all remaining space below */}
                <div className="left-panel-tabs-container">
                  {/* <div className="left-panel-tab-bar" role="tablist">
                    <button
                      type="button"
                      role="tab"
                      aria-selected={activeTab === "breakdown"}
                      className={`left-panel-tab-btn ${
                        activeTab === "breakdown" ? "is-active" : ""
                      }`}
                      onClick={() => setActiveTab("breakdown")}
                    >
                      <WikiHover term="breakdown">
                        <span>Breakdown</span>
                      </WikiHover>
                    </button>
                    <button
                      type="button"
                      role="tab"
                      aria-selected={activeTab === "detail"}
                      className={`left-panel-tab-btn ${
                        activeTab === "detail" ? "is-active" : ""
                      }`}
                      onClick={() => setActiveTab("detail")}
                    >
                      <WikiHover term="shap_mirror">
                        <span>Detail</span>
                      </WikiHover>
                    </button>
                  </div> */}

                  <div className="left-panel-tab-content">
                    {/* {activeTab === "breakdown" && selectedItem.shap_status !== "completed" ? (
                      <TreeShapComputingVisualizer
                        item={selectedItem}
                        language={language}
                        onRetryShap={onRetryShap}
                        onFastInquiry={(prompt) => onAskAssistant?.(selectedItem, prompt)}
                      />
                    ) : activeTab === "breakdown" ? ( */}
                      {/* <ForecastBreakdownChart
                        key={selectedItem.id}
                        item={selectedItem}
                        language={language}
                        onFastInquiry={(prompt) => onAskAssistant?.(selectedItem, prompt)}
                      /> */}
                    {/* ) : ( */}
                      <DailyForecastLineChart
                        key={selectedItem.id}
                        item={selectedItem}
                        language={language}
                        onFastInquiry={(prompt) => onAskAssistant?.(selectedItem, prompt)}
                      />
                    {/* )}  */}
                  </div>
                </div>
              </>
            ) : (
              <div className="item-detail-empty">
                <div className="item-detail-empty-card">
                  <div className="item-detail-empty-icon-wrap">
                    <PackageIcon size={30} className="empty-package-icon" />
                  </div>

                  <h3 className="item-detail-empty-title">
                    No Item Selected
                  </h3>

                  <p className="item-detail-empty-instruction">
                    Select an item from the <strong>forecast table</strong> to view details.
                  </p>
                </div>
              </div>
            )}
          </div>
        </aside>
      </div>
    </>
  );
}
