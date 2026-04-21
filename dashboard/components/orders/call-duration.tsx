import type { Order } from '@/lib/schemas/order';

export function CallDuration({ order }: { order: Order }) {
  if (order.status === 'in_progress') return <>Call in progress</>;
  if (!order.confirmed_at) return <>Call · duration unknown</>;

  const ms = order.confirmed_at.getTime() - order.created_at.getTime();
  if (ms <= 0) return <>Call · duration unknown</>;

  const totalSec = Math.round(ms / 1000);
  const min = Math.floor(totalSec / 60);
  const sec = totalSec % 60;
  return (
    <>
      Call · {min} min {sec} sec
    </>
  );
}
