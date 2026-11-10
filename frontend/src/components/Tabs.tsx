import {
  useState,
  useRef,
  useId,
  type ReactNode,
  type KeyboardEvent,
} from "react";

export interface TabItem {
  id: string;
  label: ReactNode;
  content: ReactNode;
  disabled?: boolean;
  badge?: ReactNode;
}

export interface TabsProps {
  tabs: TabItem[];
  defaultTabId?: string;
  activeTabId?: string;
  onTabChange?: (tabId: string) => void;
  variant?: "line" | "pill";
  className?: string;
}

export function Tabs({
  tabs,
  defaultTabId,
  activeTabId: controlledActiveId,
  onTabChange,
  variant = "line",
  className = "",
}: TabsProps) {
  const [internalActiveId, setInternalActiveId] = useState(
    defaultTabId || (tabs[0] ? tabs[0].id : ""),
  );
  const activeId =
    controlledActiveId !== undefined ? controlledActiveId : internalActiveId;
  const baseId = useId();
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const handleSelect = (tabId: string) => {
    if (controlledActiveId === undefined) {
      setInternalActiveId(tabId);
    }
    onTabChange?.(tabId);
  };

  const handleKeyDown = (
    e: KeyboardEvent<HTMLButtonElement>,
    index: number,
  ) => {
    let nextIndex: number | null = null;
    if (e.key === "ArrowRight") {
      let candidate = (index + 1) % tabs.length;
      while (candidate !== index && tabs[candidate]?.disabled) {
        candidate = (candidate + 1) % tabs.length;
      }
      if (!tabs[candidate]?.disabled) nextIndex = candidate;
    } else if (e.key === "ArrowLeft") {
      let candidate = (index - 1 + tabs.length) % tabs.length;
      while (candidate !== index && tabs[candidate]?.disabled) {
        candidate = (candidate - 1 + tabs.length) % tabs.length;
      }
      if (!tabs[candidate]?.disabled) nextIndex = candidate;
    } else if (e.key === "Home") {
      let candidate = 0;
      while (candidate < tabs.length && tabs[candidate]?.disabled) {
        candidate++;
      }
      if (candidate < tabs.length) nextIndex = candidate;
    } else if (e.key === "End") {
      let candidate = tabs.length - 1;
      while (candidate >= 0 && tabs[candidate]?.disabled) {
        candidate--;
      }
      if (candidate >= 0) nextIndex = candidate;
    }

    if (nextIndex !== null) {
      e.preventDefault();
      const nextTab = tabs[nextIndex];
      if (nextTab && !nextTab.disabled) {
        handleSelect(nextTab.id);
        tabRefs.current[nextIndex]?.focus();
      }
    }
  };

  const activeTab = tabs.find((t) => t.id === activeId);

  return (
    <div className={`w-full text-start ${className}`}>
      <div
        role="tablist"
        aria-orientation="horizontal"
        className={`flex items-center gap-1 ${
          variant === "line"
            ? "border-b border-border"
            : "p-1 bg-paper-subtle rounded-lg border border-border"
        }`}
      >
        {tabs.map((tab, idx) => {
          const isSelected = tab.id === activeId;
          const tabButtonId = `${baseId}-tab-${tab.id}`;
          const tabPanelId = `${baseId}-panel-${tab.id}`;

          const lineStyles = isSelected
            ? "border-b-2 border-ink text-ink font-semibold"
            : "border-b-2 border-transparent text-ink-muted hover:text-ink";

          const pillStyles = isSelected
            ? "bg-surface text-ink font-semibold shadow-xs"
            : "text-ink-muted hover:text-ink";

          return (
            <button
              key={tab.id}
              ref={(el) => {
                tabRefs.current[idx] = el;
              }}
              id={tabButtonId}
              role="tab"
              type="button"
              tabIndex={isSelected ? 0 : -1}
              aria-selected={isSelected}
              aria-controls={tabPanelId}
              disabled={tab.disabled}
              onClick={() => handleSelect(tab.id)}
              onKeyDown={(e) => handleKeyDown(e, idx)}
              className={`flex items-center gap-2 py-2 px-3 text-sm transition-colors rounded-t-md focus-visible:ring-2 focus-visible:ring-ink focus-visible:outline-hidden disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer ${
                variant === "line" ? lineStyles : pillStyles
              }`}
            >
              <span>{tab.label}</span>
              {tab.badge ? <span>{tab.badge}</span> : null}
            </button>
          );
        })}
      </div>

      {activeTab ? (
        <div
          id={`${baseId}-panel-${activeTab.id}`}
          role="tabpanel"
          aria-labelledby={`${baseId}-tab-${activeTab.id}`}
          tabIndex={0}
          className="pt-4 focus-visible:outline-hidden"
        >
          {activeTab.content}
        </div>
      ) : null}
    </div>
  );
}
