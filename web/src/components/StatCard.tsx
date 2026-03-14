interface StatCardProps {
  label: string;
  value: string | number;
  tone?: "default" | "good" | "warn";
}

export function StatCard({ label, value, tone = "default" }: StatCardProps) {
  return (
    <article className={`stat-card stat-card--${tone}`}>
      <span className="stat-card__label">{label}</span>
      <strong className="stat-card__value">{value}</strong>
    </article>
  );
}
