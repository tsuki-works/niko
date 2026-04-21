'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import Image from 'next/image';
import { ListOrdered, Menu, Phone, Settings } from 'lucide-react';

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

export function AppSidebar() {
  const pathname = usePathname();

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <div className="flex items-center gap-2 px-2 py-1.5">
          <Image
            src="/icon.svg"
            alt=""
            width={24}
            height={24}
            className="shrink-0 dark:invert"
            aria-hidden
          />
          <div className="flex flex-col leading-tight group-data-[collapsible=icon]:hidden">
            <span className="text-sm font-medium">Niko</span>
            <span className="text-xs text-muted-foreground">Pizza Kitchen</span>
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
        <div className="px-2 py-1 text-xs text-muted-foreground group-data-[collapsible=icon]:hidden">
          Phase 1 POC
        </div>
      </SidebarFooter>
    </Sidebar>
  );
}
