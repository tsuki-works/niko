import { redirect } from 'next/navigation';

import { MenuEmptyState } from '@/components/menu/menu-empty-state';
import { MenuParseError } from '@/components/menu/menu-parse-error';
import { MenuView } from '@/components/menu/menu-view';
import { getMyRestaurant } from '@/lib/api/restaurant';
import { getServerSession } from '@/lib/auth/session';
import { humanizeRestaurantId } from '@/lib/formatters/restaurant';
import { parseMenu } from '@/lib/schemas/menu';

// Menu config is admin-driven — Firestore writes are rare and we want the
// page to always reflect the latest doc, not a cached render.
export const dynamic = 'force-dynamic';

export default async function MenuPage() {
  const session = await getServerSession();
  if (!session) redirect('/login');

  let restaurantName = humanizeRestaurantId(session.restaurantId);
  let rawMenu: Record<string, unknown> = {};

  try {
    const restaurant = await getMyRestaurant();
    restaurantName = restaurant.name || restaurantName;
    rawMenu = restaurant.menu;
  } catch (err) {
    console.error('[menu page] /restaurants/me fetch failed', err);
    return (
      <MenuParseError reason="Could not reach the backend to load the restaurant configuration." />
    );
  }

  const hasCategories = Object.keys(rawMenu).some((k) => !k.startsWith('_'));
  if (!hasCategories) {
    return <MenuEmptyState restaurantName={restaurantName} />;
  }

  const result = parseMenu(rawMenu);
  if ('error' in result) {
    return <MenuParseError reason={result.error} />;
  }

  return (
    <MenuView
      categories={result.categories}
      itemCount={result.itemCount}
      restaurantName={restaurantName}
    />
  );
}
