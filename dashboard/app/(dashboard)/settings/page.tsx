import { redirect } from 'next/navigation';

import { SettingsShell } from '@/components/settings/settings-shell';
import { PageHeader } from '@/components/shared/page-header';
import { getMyRestaurant } from '@/lib/api/restaurant';
import { getServerSession } from '@/lib/auth/session';

export const dynamic = 'force-dynamic';

export default async function SettingsPage() {
  const session = await getServerSession();
  if (!session) redirect('/login');

  let restaurant;
  try {
    restaurant = await getMyRestaurant();
  } catch (err) {
    console.error('[settings page] /restaurants/me fetch failed', err);
    return (
      <section className="flex flex-1 flex-col p-6 lg:p-10">
        <PageHeader
          title="Settings"
          subtitle="Could not reach the backend to load your restaurant configuration."
        />
      </section>
    );
  }

  return <SettingsShell restaurant={restaurant} />;
}
