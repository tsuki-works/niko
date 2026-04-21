import { notFound } from 'next/navigation';

import { OrderDetail } from '@/components/orders/order-detail';
import { getOrder } from '@/lib/api/orders';

export const dynamic = 'force-dynamic';

export default async function OrderDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const order = await getOrder(id);
  if (!order) notFound();
  return <OrderDetail order={order} />;
}
