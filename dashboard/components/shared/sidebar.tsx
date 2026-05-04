'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  LayoutDashboard,
  ListOrdered,
  Menu,
  Phone,
  Settings,
  type LucideIcon,
} from 'lucide-react';

import { NikoMark } from '@/components/shared/niko-mark';
import { UserMenu } from '@/components/shared/user-menu';
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
} from '@/components/ui/sidebar';
import { cn } from '@/lib/utils';

type NavItem = {
  label: string;
  href: string;
  icon: LucideIcon;
  matchPrefixes?: string[];
};

const NAV: NavItem[] = [
  { label: 'Overview', href: '/', icon: LayoutDashboard, matchPrefixes: ['/'] },
  { label: 'Orders', href: '/orders', icon: ListOrdered },
  { label: 'Calls', href: '/calls', icon: Phone },
  { label: 'Menu', href: '/menu', icon: Menu },
  { label: 'Settings', href: '/settings', icon: Settings },
];

function isActive(pathname: string, item: NavItem): boolean {
  if (item.matchPrefixes) {
    return item.matchPrefixes.some((p) =>
      p === '/'
        ? pathname === '/'
        : pathname === p || pathname.startsWith(`${p}/`),
    );
  }
  return pathname === item.href || pathname.startsWith(`${item.href}/`);
}

export function AppSidebar({
  restaurantName,
  userEmail,
  buildSha,
}: {
  restaurantName?: string;
  userEmail?: string;
  buildSha?: string;
}) {
  const pathname = usePathname();

  return (
    // `collapsible="none"` keeps the sidebar always-expanded. Sticky
    // positioning + explicit `h-svh` give us the standard always-visible
    // pattern (cf. GitHub, Stripe). Inline styles back the Tailwind
    // classes in case `tailwind-merge` mishandles `min-h` conflicts on
    // Tailwind v4. The 200px width is set on `<SidebarProvider>` via
    // a `--sidebar-width` style override in (dashboard)/layout.tsx.
    <Sidebar
      collapsible="none"
      className="sticky top-0 h-svh self-start border-r border-border-subtle bg-surface-1"
      style={
        {
          position: 'sticky',
          top: 0,
          height: '100svh',
          alignSelf: 'flex-start',
        } as React.CSSProperties
      }
    >
      <SidebarHeader className="px-3 py-3">
        <Link
          href="/"
          className="flex items-center gap-2"
          aria-label="Niko · go to overview"
        >
          <NikoMark size={24} />
          <span className="text-base font-semibold tracking-tight text-foreground">
            Niko
          </span>
        </Link>
      </SidebarHeader>

      <SidebarContent className="px-2">
        <nav aria-label="Main">
          <ul className="flex flex-col gap-2">
            {NAV.map((item) => {
              const Icon = item.icon;
              const active = isActive(pathname, item);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={active ? 'page' : undefined}
                    className={cn(
                      'flex h-8 items-center gap-2 rounded-sm px-3 text-sm transition-colors',
                      active
                        ? 'bg-brand-muted text-foreground'
                        : 'text-foreground-muted hover:bg-surface-2 hover:text-foreground',
                    )}
                  >
                    <Icon className="size-4 shrink-0" aria-hidden />
                    <span>{item.label}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      </SidebarContent>

      <SidebarFooter className="p-2">
        <UserMenu
          restaurantName={restaurantName ?? ''}
          userEmail={userEmail ?? ''}
          buildSha={buildSha}
        />
      </SidebarFooter>
    </Sidebar>
  );
}
