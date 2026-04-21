import { Badge } from '@/components/ui/badge';
import type { OrderStatus } from '@/lib/schemas/order';
import { statusStyle } from '@/lib/status-styles';
import { cn } from '@/lib/utils';

export function StatusBadge({
  status,
  className,
}: {
  status: OrderStatus;
  className?: string;
}) {
  const style = statusStyle(status);
  return (
    <Badge variant="outline" className={cn(style.className, className)}>
      {style.label}
    </Badge>
  );
}
