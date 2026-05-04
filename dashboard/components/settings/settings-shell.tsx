import type { Restaurant } from '@/lib/schemas/restaurant';

import { HoursEditor } from '@/components/settings/hours-editor';
import { RestaurantInfoForm } from '@/components/settings/restaurant-info-form';
import { PageHeader } from '@/components/shared/page-header';

export function SettingsShell({ restaurant }: { restaurant: Restaurant }) {
  return (
    <section className="flex flex-1 flex-col p-6 lg:p-10">
      <PageHeader
        title="Settings"
        subtitle="Restaurant info, hours, and call-handling fallbacks. Changes take effect on the next call."
      />

      <div className="flex max-w-3xl flex-col gap-6">
        <RestaurantInfoForm restaurant={restaurant} />
        <HoursEditor restaurant={restaurant} />

        <Placeholder
          title="Stripe Connect"
          body="Configured during onboarding when delivery or prepay-for-pickup is enabled. Lands in Sprint 2.3."
        />

        <Placeholder
          title="SMS preferences"
          body="Order confirmations send by default. Opt-out toggles arrive post-pilot."
        />
      </div>
    </section>
  );
}

function Placeholder({ title, body }: { title: string; body: string }) {
  return (
    <section className="rounded-md border border-dashed border-border-subtle bg-surface-1 p-6">
      <h3 className="text-md font-medium text-foreground-muted">{title}</h3>
      <p className="mt-1 text-sm text-foreground-subtle">{body}</p>
    </section>
  );
}
