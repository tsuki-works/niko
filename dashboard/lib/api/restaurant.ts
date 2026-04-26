/**
 * HTTP client for the FastAPI restaurants endpoints.
 *
 * Server-only — never imported on the client. The dashboard fetches
 * the calling tenant's restaurant doc once per page render, server-
 * side, and passes it down to Client Components as a prop. Live
 * updates to restaurant config aren't a Phase 2 concern (changes are
 * rare and mostly admin-driven), so no `onSnapshot` here.
 *
 * Endpoint:
 *   GET /restaurants/me   ← LIVE (app/main.py)
 */
import 'server-only';

import { apiFetch } from '@/lib/api/http';
import { RestaurantSchema, type Restaurant } from '@/lib/schemas/restaurant';

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
