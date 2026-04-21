import { Skeleton } from '@/components/ui/skeleton';

export default function Loading() {
  return (
    <section className="mx-auto flex max-w-4xl flex-col gap-4 p-6">
      <div className="flex items-center gap-3">
        <Skeleton className="h-8 w-16" />
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-6 w-20 rounded-full" />
        <Skeleton className="ml-auto h-4 w-32" />
      </div>
      <div className="rounded-xl border p-4">
        <Skeleton className="mb-2 h-5 w-40" />
        <Skeleton className="h-4 w-24" />
      </div>
      {Array.from({ length: 2 }).map((_, i) => (
        <div key={i} className="rounded-xl border p-4">
          <div className="flex justify-between">
            <Skeleton className="h-5 w-56" />
            <Skeleton className="h-5 w-16" />
          </div>
        </div>
      ))}
      <div className="rounded-xl border bg-muted/40 p-4">
        <div className="flex justify-between">
          <Skeleton className="h-5 w-24" />
          <Skeleton className="h-5 w-16" />
        </div>
      </div>
    </section>
  );
}
