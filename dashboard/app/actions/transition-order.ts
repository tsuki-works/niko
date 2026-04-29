'use server';

import { revalidatePath } from 'next/cache';
import { z } from 'zod';

import {
  markPreparingApi,
  markReadyApi,
  markCompletedApi,
} from '@/lib/api/orders';

const InputSchema = z.object({
  call_sid: z.string().min(1),
});

export type TransitionActionResult =
  | { success: true }
  | { success: false; error: string };

/**
 * Server Actions for the kitchen workflow transitions, mirroring the
 * existing cancelOrder action shape.
 *
 * Each action validates input, calls the corresponding FastAPI endpoint
 * via the API client, revalidates the orders feed + the order's detail
 * page on success, and returns a typed discriminated union.
 *
 * Race note: the backend is the single writer for these transitions
 * (no AI-side races post-call). The dashboard relies on Firestore
 * onSnapshot to reflect the new state in addition to revalidation.
 */

async function runTransition(
  input: unknown,
  apiCall: (callSid: string) => Promise<{ success: boolean; error?: string }>,
): Promise<TransitionActionResult> {
  const parsed = InputSchema.safeParse(input);
  if (!parsed.success) {
    return { success: false, error: 'Invalid input' };
  }

  const result = await apiCall(parsed.data.call_sid);
  if (!result.success) {
    return { success: false, error: result.error ?? 'Unknown error' };
  }

  revalidatePath('/');
  revalidatePath(`/orders/${parsed.data.call_sid}`);
  return { success: true };
}

export async function markPreparingAction(
  input: unknown,
): Promise<TransitionActionResult> {
  return runTransition(input, markPreparingApi);
}

export async function markReadyAction(
  input: unknown,
): Promise<TransitionActionResult> {
  return runTransition(input, markReadyApi);
}

export async function markCompletedAction(
  input: unknown,
): Promise<TransitionActionResult> {
  return runTransition(input, markCompletedApi);
}
