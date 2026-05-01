'use server';

import { revalidatePath } from 'next/cache';

import {
  updateRestaurant,
  type RestaurantUpdate,
} from '@/lib/api/restaurant';

export type UpdateRestaurantResult =
  | { success: true }
  | { success: false; error: string };

export async function updateRestaurantAction(
  patch: RestaurantUpdate,
): Promise<UpdateRestaurantResult> {
  try {
    await updateRestaurant(patch);
  } catch (err) {
    return {
      success: false,
      error: err instanceof Error ? err.message : 'Unknown error',
    };
  }
  revalidatePath('/settings');
  return { success: true };
}
