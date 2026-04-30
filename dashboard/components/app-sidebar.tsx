'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { ListOrdered, Menu, Phone, Settings } from 'lucide-react';

import { NikoMark } from '@/components/shared/niko-mark';
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from '@/components/ui/sidebar';

type NavItem = {
  label: string;
  href: string;
  icon: typeof ListOrdered;
  /** If set, the item is highlighted when the pathname starts with any of these prefixes. */
  matchPrefixes?: string[];
};

const NAV: NavItem[] = [
  {
    label: 'Orders',
    href: '/',
    icon: ListOrdered,
    matchPrefixes: ['/', '/orders'],
  },
  { label: 'Calls', href: '/calls', icon: Phone },
  { label: 'Menu', href: '/menu', icon: Menu },
  { label: 'Settings', href: '/settings', icon: Settings },
];

function isActive(pathname: string, item: NavItem): boolean {
  if (item.matchPrefixes) {
    return item.matchPrefixes.some((p) =>
      p === '/' ? pathname === '/' : pathname === p || pathname.startsWith(`${p}/`),
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
    // `collapsible="none"` means the sidebar is always expanded.
    // The ShadCN primitive gives this variant only `h-full`, which
    // doesn't resolve when SidebarProvider has only `min-h-svh` (no
    // explicit parent height) — the sidebar collapses to nav content
    // height. `min-h-svh` here gives it a viewport-height floor; the
    // parent flex row's default `align-items: stretch` then grows it
    // with tall pages (e.g. /menu) so the sidebar reaches the bottom.
    <Sidebar collapsible="none" className="min-h-svh border-r">
      <SidebarHeader>
        <div className="flex items-center gap-2.5 px-2 py-3">
          {/* 48px lines up with the "Niko" + "by Tsuki Works" stack
              (text-2xl ≈ 30px + text-xs ≈ 17px); collapsed → 28px. */}
          <NikoMark size={54} className="group-data-[collapsible=icon]:size-7" />
          {/* Wordmark — hidden when the sidebar collapses to icons.
              Font-weight 600 is an intentional exception to the
              dashboard's "400/500 only" rule: this is brand typography,
              not body copy. */}
          <div className="flex flex-col leading-tight group-data-[collapsible=icon]:hidden">
            <span className="text-2xl font-semibold tracking-tight text-primary">
              Niko
            </span>
            <span className="text-xs text-muted-foreground">
              by Tsuki Works
            </span>
          </div>
        </div>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {NAV.map((item) => {
                const Icon = item.icon;
                const active = isActive(pathname, item);
                return (
                  <SidebarMenuItem key={item.href}>
                    <SidebarMenuButton
                      asChild
                      isActive={active}
                      tooltip={item.label}
                    >
                      <Link href={item.href}>
                        <Icon />
                        <span>{item.label}</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter>
        <div className="flex flex-col gap-0.5 px-2 py-1 text-xs text-muted-foreground group-data-[collapsible=icon]:hidden">
          {restaurantName ? (
            <span className="truncate font-medium text-foreground">
              {restaurantName}
            </span>
          ) : null}
          {userEmail ? <span className="truncate">{userEmail}</span> : null}
          {buildSha ? (
            <span className="truncate font-mono text-[10px] opacity-50">
              {buildSha.slice(0, 7)}
            </span>
          ) : null}
        </div>
      </SidebarFooter>
    </Sidebar>
  );
}
