/**
 * HTTP client for the FastAPI menu CRUD endpoints.
 *
 * Server-only. All four mutations return the full updated Restaurant doc
 * so callers can revalidate their local state without an extra GET.
 *
 * Endpoints (Sprint 2.4 backend, commit 5b6ab8e):
 *   POST   /restaurants/me/menu/items
 *   PATCH  /restaurants/me/menu/items/:category/:name
 *   DELETE /restaurants/me/menu/items/:category/:name
 *   POST   /restaurants/me/menu/categories
 */
import 'server-only';

import { apiFetch } from '@/lib/api/http';
import { RestaurantSchema, type Restaurant } from '@/lib/schemas/restaurant';

export type CreateMenuItem = {
  category: string;
  name: string;
  description?: string;
  available?: boolean;
  price?: number;
  sizes?: Record<string, number>;
};

export type UpdateMenuItem = {
  new_name?: string;
  new_category?: string;
  description?: string;
  price?: number;
  sizes?: Record<string, number>;
  available?: boolean;
};

async function parseRestaurant(res: Response, what: string): Promise<Restaurant> {
  if (!res.ok) {
    throw new Error(`${what} failed: ${res.status} ${res.statusText}`);
  }
  const body = (await res.json()) as unknown;
  const parsed = RestaurantSchema.safeParse(body);
  if (!parsed.success) {
    console.error(`[lib/api/menu] ${what} response failed validation`);
    throw new Error(`${what} response failed schema validation`);
  }
  return parsed.data;
}

export async function createMenuItem(
  payload: CreateMenuItem,
): Promise<Restaurant> {
  const res = await apiFetch('/restaurants/me/menu/items', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return parseRestaurant(res, 'POST /menu/items');
}

export async function updateMenuItem(args: {
  category: string;
  name: string;
  patch: UpdateMenuItem;
}): Promise<Restaurant> {
  const url = `/restaurants/me/menu/items/${encodeURIComponent(args.category)}/${encodeURIComponent(args.name)}`;
  const res = await apiFetch(url, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(args.patch),
  });
  return parseRestaurant(res, 'PATCH /menu/items');
}

export async function deleteMenuItem(args: {
  category: string;
  name: string;
}): Promise<Restaurant> {
  const url = `/restaurants/me/menu/items/${encodeURIComponent(args.category)}/${encodeURIComponent(args.name)}`;
  const res = await apiFetch(url, { method: 'DELETE' });
  return parseRestaurant(res, 'DELETE /menu/items');
}

export async function createMenuCategory(payload: {
  key: string;
}): Promise<Restaurant> {
  const res = await apiFetch('/restaurants/me/menu/categories', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return parseRestaurant(res, 'POST /menu/categories');
}
