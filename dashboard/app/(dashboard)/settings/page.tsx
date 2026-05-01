import { redirect } from 'next/navigation';

import { SettingsShell } from '@/components/settings/settings-shell';
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
      <section className="flex flex-1 flex-col gap-3 p-6 lg:p-10">
        <h2 className="text-3xl font-medium tracking-tight">Settings</h2>
        <p className="text-sm text-muted-foreground">
          Could not reach the backend to load your restaurant configuration.
        </p>
      </section>
    );
  }

  return <SettingsShell restaurant={restaurant} />;
}
