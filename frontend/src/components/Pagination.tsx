import { useText } from "../i18n/useText";
import { Button } from "./Button";

export interface LoadMoreProps {
  onLoadMore: () => void;
  hasMore: boolean;
  isLoading?: boolean;
  label?: string;
  loadingLabel?: string;
  className?: string;
}

export function LoadMore({
  onLoadMore,
  hasMore,
  isLoading = false,
  label,
  loadingLabel,
  className = "",
}: LoadMoreProps) {
  const { t } = useText();
  if (!hasMore && !isLoading) {
    return (
      <p className="text-center text-xs text-ink-muted py-4 select-none">
        {t("controls.youHaveReachedTheEnd")}
      </p>
    );
  }

  return (
    <div className={`flex justify-center py-4 ${className}`}>
      <Button
        variant="outline"
        size="md"
        onClick={onLoadMore}
        isLoading={isLoading}
        disabled={isLoading}
        className="min-w-36"
      >
        {isLoading
          ? (loadingLabel ?? t("controls.loadingMore"))
          : (label ?? t("controls.loadMore"))}
      </Button>
    </div>
  );
}

export interface PaginationProps {
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  className?: string;
}

export function Pagination({
  currentPage,
  totalPages,
  onPageChange,
  className = "",
}: PaginationProps) {
  const { t } = useText();
  if (totalPages <= 1) return null;

  return (
    <nav
      role="navigation"
      aria-label={t("controls.paginationNavigation")}
      className={`flex items-center justify-center gap-1.5 py-4 ${className}`}
    >
      <Button
        variant="outline"
        size="sm"
        disabled={currentPage <= 1}
        onClick={() => onPageChange(currentPage - 1)}
        aria-label={t("controls.previousPage")}
      >
        {t("controls.previous")}
      </Button>

      <span className="text-xs text-ink-muted px-2 font-medium">
        {t("controls.pageOf", { current: currentPage, total: totalPages })}
      </span>

      <Button
        variant="outline"
        size="sm"
        disabled={currentPage >= totalPages}
        onClick={() => onPageChange(currentPage + 1)}
        aria-label={t("controls.nextPage")}
      >
        {t("controls.next")}
      </Button>
    </nav>
  );
}
