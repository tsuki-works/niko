export function Tile({
  label,
  value,
  unit,
  hint,
}: {
  label: string;
  value: string;
  unit?: string;
  hint?: string;
}) {
  return (
    <article className="flex flex-col gap-2 rounded-lg border border-border p-6">
      <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <div className="flex items-baseline gap-2">
        <span className="text-3xl font-medium tabular-nums tracking-tight">
          {value}
        </span>
        {unit ? (
          <span className="text-sm text-muted-foreground">{unit}</span>
        ) : null}
      </div>
      {hint ? (
        <p className="text-xs text-muted-foreground">{hint}</p>
      ) : null}
    </article>
  );
}
