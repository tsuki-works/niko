import { Skeleton } from '@/components/ui/skeleton';

export default function MenuLoading() {
  return (
    <section className="flex flex-1 flex-col gap-10 p-6 lg:p-10">
      <header className="flex max-w-3xl flex-col gap-3">
        <div className="flex items-baseline gap-3">
          <Skeleton className="h-9 w-24" />
          <span aria-hidden className="h-px flex-1 translate-y-[-0.5rem] bg-border" />
        </div>
        <Skeleton className="h-4 w-72" />
        <Skeleton className="h-3 w-56" />
      </header>

      <div className="grid gap-10 lg:grid-cols-[12rem_minmax(0,1fr)] lg:gap-16">
        <div className="hidden flex-col gap-2 lg:flex">
          <Skeleton className="mb-2 h-3 w-16" />
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-5 w-full" />
          ))}
        </div>
        <div className="flex flex-col gap-14">
          {Array.from({ length: 2 }).map((_, c) => (
            <section key={c}>
              <header className="mb-6 flex items-baseline gap-4 border-b border-border pb-3">
                <Skeleton className="h-7 w-40" />
                <span aria-hidden className="h-px flex-1 bg-border/60" />
                <Skeleton className="h-4 w-16" />
              </header>
              <ul className="grid gap-x-12 gap-y-6 sm:grid-cols-2">
                {Array.from({ length: 6 }).map((_, i) => (
                  <li key={i}>
                    <div className="flex items-baseline gap-3">
                      <Skeleton className="h-5 w-40" />
                      <span aria-hidden className="min-w-4 flex-1 translate-y-[-0.25rem] border-b border-dotted border-border" />
                      <Skeleton className="h-5 w-14" />
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      </div>
    </section>
  );
}
