'use server';

import { revalidatePath } from 'next/cache';
import { z } from 'zod';

import { cancelOrderApi } from '@/lib/api/orders';

const InputSchema = z.object({
  call_sid: z.string().min(1),
});

export type CancelActionResult =
  | { success: true }
  | { success: false; error: string };

/**
 * Server Action for cancelling a confirmed order.
 *
 * Today this delegates to FastAPI's (not-yet-implemented) cancel endpoint
 * via `cancelOrderApi`. While the endpoint is stubbed, the action returns
 * a typed error so the UI can show a toast.
 *
 * Race note: when the real endpoint lands, FastAPI is the single writer
 * for the `confirmed → cancelled` transition. For Phase 1 that's fine
 * because the call is already over; when staff-initiated cancels meet
 * agent writes, the backend should serialize the transition.
 */
export async function cancelOrder(input: unknown): Promise<CancelActionResult> {
  const parsed = InputSchema.safeParse(input);
  if (!parsed.success) {
    return { success: false, error: 'Invalid input' };
  }

  const result = await cancelOrderApi(parsed.data.call_sid);
  if (!result.success) {
    return { success: false, error: result.error };
  }

  revalidatePath('/');
  revalidatePath(`/orders/${parsed.data.call_sid}`);
  return { success: true };
}
