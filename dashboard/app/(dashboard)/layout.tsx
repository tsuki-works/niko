import { CircleAlert } from 'lucide-react';
import { redirect } from 'next/navigation';

import { AppSidebar } from '@/components/shared/sidebar';
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar';
import { getMyRestaurant } from '@/lib/api/restaurant';
import { humanizeRestaurantId } from '@/lib/formatters/restaurant';
import { isAwaitingNumber } from '@/lib/schemas/restaurant';
import { getServerSession } from '@/lib/auth/session';

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // Middleware bounces unauthenticated requests, but it can only do a
  // cookie *presence* check (Edge runtime). The verified session is
  // the actual gate — re-check here so a forged cookie still ends
  // up at /login.
  const session = await getServerSession();
  if (!session) {
    redirect('/login');
  }

  // Fall back to the humanized rid if the restaurant doc fetch fails —
  // the dashboard should still render auth-aware chrome even when the
  // backend is unreachable. Logged so it's visible in Cloud Run logs.
  let restaurantName = humanizeRestaurantId(session.restaurantId);
  let awaitingNumber = false;
  try {
    const restaurant = await getMyRestaurant();
    restaurantName = restaurant.name || restaurantName;
    awaitingNumber = isAwaitingNumber(restaurant);
  } catch (err) {
    console.error('[layout] /restaurants/me fetch failed', err);
  }

  return (
    <SidebarProvider
      style={
        {
          // 200px sidebar per design-system.md (overrides the shadcn default of 14rem).
          '--sidebar-width': '200px',
        } as React.CSSProperties
      }
    >
      <AppSidebar
        restaurantName={restaurantName}
        userEmail={session.email ?? ''}
        buildSha={process.env.NEXT_PUBLIC_COMMIT_SHA}
      />
      <SidebarInset>
        {awaitingNumber ? (
          <div
            role="status"
            className="flex items-center gap-2 border-b border-amber-500/30 bg-amber-50 px-4 py-2 text-xs text-amber-900 dark:bg-amber-950/40 dark:text-amber-200"
          >
            <CircleAlert className="size-4 shrink-0" aria-hidden />
            <span>
              No Twilio number assigned to this restaurant yet — incoming calls
              won&apos;t route here until one is provisioned.
            </span>
          </div>
        ) : null}
        <div className="flex flex-1 flex-col">{children}</div>
      </SidebarInset>
    </SidebarProvider>
  );
}
