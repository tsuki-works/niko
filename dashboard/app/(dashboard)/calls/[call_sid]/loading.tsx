import { Skeleton } from '@/components/ui/skeleton';

export default function Loading() {
  return (
    <section className="flex flex-1 flex-col gap-4 p-6">
      <Skeleton className="h-4 w-24" />
      <Skeleton className="h-6 w-48" />
      <Skeleton className="h-3 w-72" />
      <div className="flex flex-col gap-2 rounded-xl border bg-card p-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-8 w-full" />
        ))}
      </div>
    </section>
  );
}
