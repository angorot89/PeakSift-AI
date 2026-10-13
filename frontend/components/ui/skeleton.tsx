/** Placeholder block for content that is loading; announced once by the surrounding status. */
export function Skeleton({ className = "" }: { className?: string }) {
  return <div aria-hidden="true" className={`animate-shimmer rounded-lg bg-surface-3 ${className}`} />;
}
