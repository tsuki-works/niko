/**
 * HTTP client for the FastAPI restaurants endpoints.
 *
 * Server-only — never imported on the client. The dashboard fetches
 * the calling tenant's restaurant doc once per page render, server-
 * side, and passes it down to Client Components as a prop. Live
 * updates to restaurant config aren't a Phase 2 concern (changes are
 * rare and mostly admin-driven), so no `onSnapshot` here.
 *
 * Endpoints:
 *   GET   /restaurants/me   ← LIVE (app/main.py)
 *   PATCH /restaurants/me   ← LIVE (app/main.py)
 */
import 'server-only';

import { apiFetch } from '@/lib/api/http';
import {
  RestaurantSchema,
  type HoursStructured,
  type Restaurant,
} from '@/lib/schemas/restaurant';

export async function getMyRestaurant(): Promise<Restaurant> {
  const res = await apiFetch('/restaurants/me');
  if (!res.ok) {
    throw new Error(
      `GET /restaurants/me failed: ${res.status} ${res.statusText}`,
    );
  }
  const body = (await res.json()) as unknown;
  const parsed = RestaurantSchema.safeParse(body);
  if (!parsed.success) {
    console.error(
      '[lib/api/restaurant] /restaurants/me payload failed validation',
      parsed.error.flatten(),
    );
    throw new Error('restaurant payload failed schema validation');
  }
  return parsed.data;
}

export type RestaurantUpdate = Partial<{
  name: string;
  display_phone: string;
  address: string;
  hours_structured: HoursStructured;
  fallback_phone: string | null;
  offers_delivery: boolean;
}>;

export async function updateRestaurant(
  update: RestaurantUpdate,
): Promise<Restaurant> {
  const res = await apiFetch('/restaurants/me', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(update),
  });
  if (!res.ok) {
    throw new Error(
      `PATCH /restaurants/me failed: ${res.status} ${res.statusText}`,
    );
  }
  const body = (await res.json()) as unknown;
  const parsed = RestaurantSchema.safeParse(body);
  if (!parsed.success) {
    console.error(
      '[lib/api/restaurant] PATCH response failed validation',
      parsed.error.flatten(),
    );
    throw new Error('updated restaurant payload failed schema validation');
  }
  return parsed.data;
}
