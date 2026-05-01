'use server';

import { revalidatePath } from 'next/cache';

import {
  createMenuCategory,
  createMenuItem,
  deleteMenuItem,
  updateMenuItem,
  type CreateMenuItem,
  type UpdateMenuItem,
} from '@/lib/api/menu';

export type ActionResult =
  | { success: true }
  | { success: false; error: string };

function wrap<T>(work: () => Promise<T>): Promise<ActionResult> {
  return work()
    .then(() => ({ success: true as const }))
    .catch((err) => ({
      success: false as const,
      error: err instanceof Error ? err.message : 'Unknown error',
    }));
}

export async function createMenuItemAction(
  payload: CreateMenuItem,
): Promise<ActionResult> {
  const result = await wrap(() => createMenuItem(payload));
  revalidatePath('/menu');
  return result;
}

export async function updateMenuItemAction(args: {
  category: string;
  name: string;
  patch: UpdateMenuItem;
}): Promise<ActionResult> {
  const result = await wrap(() => updateMenuItem(args));
  revalidatePath('/menu');
  return result;
}

export async function deleteMenuItemAction(args: {
  category: string;
  name: string;
}): Promise<ActionResult> {
  const result = await wrap(() => deleteMenuItem(args));
  revalidatePath('/menu');
  return result;
}

export async function createCategoryAction(payload: {
  key: string;
}): Promise<ActionResult> {
  const result = await wrap(() => createMenuCategory(payload));
  revalidatePath('/menu');
  return result;
}
