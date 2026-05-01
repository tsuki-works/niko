import { z } from 'zod';

export const OrderSummarySchema = z.object({
  today_count: z.number().int().nonnegative(),
  seven_day_count: z.number().int().nonnegative(),
  average_order_value_7d: z.number().nonnegative(),
  completion_rate_7d: z.number().min(0).max(1),
});

export type OrderSummary = z.infer<typeof OrderSummarySchema>;
