export function LiveIndicator() {
  return (
    <div className="flex items-center gap-2 text-sm text-muted-foreground">
      <span className="inline-block h-2 w-2 rounded-full bg-emerald-500" />
      Live
    </div>
  );
}
