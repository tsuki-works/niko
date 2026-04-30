import { UtensilsCrossed } from 'lucide-react';

export function MenuEmptyState({ restaurantName }: { restaurantName: string }) {
  return (
    <section className="flex flex-1 items-center justify-center p-6">
      <div className="flex max-w-md flex-col items-center gap-3 rounded-xl border bg-card p-10 text-center">
        <UtensilsCrossed
          className="h-8 w-8 text-muted-foreground"
          aria-hidden
        />
        <h2 className="text-lg font-medium">No menu yet</h2>
        <p className="text-sm text-muted-foreground">
          {restaurantName} hasn&apos;t loaded a menu into the platform.
          Onboard the menu via{' '}
          <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">
            scripts/provision_restaurant.py
          </code>{' '}
          (or the upcoming menu editor) and refresh.
        </p>
      </div>
    </section>
  );
}
