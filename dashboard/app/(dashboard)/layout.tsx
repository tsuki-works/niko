import { redirect } from 'next/navigation';

import { AppSidebar } from '@/components/app-sidebar';
import { SignOutButton } from '@/components/shared/sign-out-button';
import { ThemeToggle } from '@/components/shared/theme-toggle';
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar';
import { humanizeRestaurantId } from '@/lib/formatters/restaurant';
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

  const restaurantName = humanizeRestaurantId(session.restaurantId);

  return (
    <SidebarProvider>
      <AppSidebar
        restaurantName={restaurantName}
        userEmail={session.email ?? ''}
      />
      <SidebarInset>
        <header className="flex items-center justify-between gap-2 border-b px-4 py-3">
          <div className="flex items-center gap-2">
            <h1 className="text-lg font-medium">{restaurantName}</h1>
          </div>
          <div className="flex items-center gap-2">
            <SignOutButton />
            <ThemeToggle />
          </div>
        </header>
        <div className="flex flex-1 flex-col">{children}</div>
      </SidebarInset>
    </SidebarProvider>
  );
}
