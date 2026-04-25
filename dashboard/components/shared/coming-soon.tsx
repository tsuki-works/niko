import { Construction } from 'lucide-react';

export function ComingSoon({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <section className="flex flex-1 items-center justify-center p-6">
      <div className="flex max-w-md flex-col items-center gap-3 rounded-xl border bg-card p-10 text-center">
        <Construction className="h-8 w-8 text-muted-foreground" aria-hidden />
        <h2 className="text-lg font-medium">{title}</h2>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
    </section>
  );
}
