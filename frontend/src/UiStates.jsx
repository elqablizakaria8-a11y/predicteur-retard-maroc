export function Skeleton({ className = '' }) {
  return <span className={`skeleton ${className}`} aria-hidden="true" />;
}

export function EmptyState({ children }) {
  return <p className="ui-empty">{children}</p>;
}
