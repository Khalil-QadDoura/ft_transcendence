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
  label = "Load more",
  loadingLabel = "Loading more...",
  className = "",
}: LoadMoreProps) {
  if (!hasMore && !isLoading) {
    return (
      <p className="text-center text-xs text-ink-muted py-4 select-none">
        You have reached the end.
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
        {isLoading ? loadingLabel : label}
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
  if (totalPages <= 1) return null;

  return (
    <nav
      role="navigation"
      aria-label="Pagination Navigation"
      className={`flex items-center justify-center gap-1.5 py-4 ${className}`}
    >
      <Button
        variant="outline"
        size="sm"
        disabled={currentPage <= 1}
        onClick={() => onPageChange(currentPage - 1)}
        aria-label="Previous Page"
      >
        Previous
      </Button>

      <span className="text-xs text-ink-muted px-2 font-medium">
        Page {currentPage} of {totalPages}
      </span>

      <Button
        variant="outline"
        size="sm"
        disabled={currentPage >= totalPages}
        onClick={() => onPageChange(currentPage + 1)}
        aria-label="Next Page"
      >
        Next
      </Button>
    </nav>
  );
}
