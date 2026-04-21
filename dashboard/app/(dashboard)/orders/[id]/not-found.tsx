import Link from 'next/link';

import { Button } from '@/components/ui/button';

export default function NotFound() {
  return (
    <section className="mx-auto flex max-w-md flex-col items-center gap-4 p-12 text-center">
      <div className="rounded-xl border bg-card p-8">
        <h2 className="text-xl font-medium">Order not found</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          This order may have been deleted, or the link is wrong.
        </p>
        <Button asChild className="mt-4">
          <Link href="/">Back to orders</Link>
        </Button>
      </div>
    </section>
  );
}
