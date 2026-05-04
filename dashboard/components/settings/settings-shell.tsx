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

      <div className="flex max-w-3xl flex-col gap-12">
        <RestaurantInfoForm restaurant={restaurant} />
        <HoursEditor restaurant={restaurant} />

        <section className="flex flex-col gap-2 rounded-lg border border-dashed border-border p-6">
          <h3 className="text-base font-medium">Stripe Connect</h3>
          <p className="text-xs text-muted-foreground">
            Configured during onboarding when delivery or prepay-for-pickup is
            enabled. Lands in Sprint 2.3.
          </p>
        </section>

        <section className="flex flex-col gap-2 rounded-lg border border-dashed border-border p-6">
          <h3 className="text-base font-medium">SMS preferences</h3>
          <p className="text-xs text-muted-foreground">
            Order confirmations send by default. Opt-out toggles arrive
            post-pilot.
          </p>
        </section>
      </div>
    </section>
  );
}
