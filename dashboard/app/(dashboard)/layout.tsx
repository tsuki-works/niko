import { ThemeToggle } from '@/components/shared/theme-toggle';

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex items-center justify-between border-b px-6 py-3">
        <h1 className="text-lg font-medium">Niko Pizza Kitchen</h1>
        <ThemeToggle />
      </header>
      <main className="flex-1">{children}</main>
    </div>
  );
}
