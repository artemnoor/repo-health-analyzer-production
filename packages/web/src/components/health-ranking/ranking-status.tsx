import * as React from "react";
import { AlertCircle, Info, LoaderCircle } from "lucide-react";

export function RankingStatus({
  state,
  total = 0,
  onRetry,
}: {
  state: "loading" | "error" | "empty";
  total?: number;
  onRetry?: () => void;
}) {
  if (state === "loading") {
    return (
      <div
        className="flex min-h-40 items-center justify-center gap-2 text-sm text-[var(--color-text-secondary)]"
        role="status"
        aria-label="Loading repository ranking"
      >
        <LoaderCircle className="h-4 w-4 motion-safe:animate-spin" aria-hidden />
        Loading public repository health…
      </div>
    );
  }

  if (state === "error") {
    return (
      <div className="flex min-h-40 flex-col items-center justify-center gap-2 text-center">
        <AlertCircle className="h-5 w-5 text-[var(--color-error)]" aria-hidden />
        <p className="text-sm font-medium text-[var(--color-text-primary)]">
          Couldn’t load the repository ranking
        </p>
        <p className="max-w-[48ch] text-xs text-[var(--color-text-secondary)]">
          The public ranking endpoint is unavailable. Try again in a moment.
        </p>
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="text-xs font-medium text-[var(--color-accent-primary)] hover:underline"
          >
            Try again
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="flex min-h-40 flex-col items-center justify-center gap-2 text-center">
      <Info className="h-5 w-5 text-[var(--color-text-tertiary)]" aria-hidden />
      <p className="text-sm font-medium text-[var(--color-text-primary)]">
        {total > 0 ? "No repositories match these filters" : "No public health scores yet"}
      </p>
      <p className="max-w-[52ch] text-xs text-[var(--color-text-secondary)]">
        A repository appears here after a completed health analysis is published and meets the
        ranking freshness and evidence requirements.
      </p>
    </div>
  );
}
