/**
 * Restaurant schema mirrored from `app/restaurants/models.py::Restaurant`.
 *
 * `twilio_phone` is allowed to be an empty string — the explicit
 * "awaiting Twilio number" state, used between tenant creation and
 * number provisioning. Render the awaiting-number pill / copy in the
 * dashboard whenever it's empty, never in any other case.
 *
 * `menu` stays `Record<string, unknown>` — the backend prompt builder
 * currently only renders `pizzas`/`sides`/`drinks` keys, but the doc
 * shape is intentionally free-form during the multi-tenancy migration.
 * The dashboard doesn't read menu contents from this fetch path
 * (menu CRUD lives elsewhere in Sprint 2.4).
 */
import { z } from 'zod';

export const RestaurantSchema = z.object({
  id: z.string(),
  name: z.string(),
  display_phone: z.string(),
  twilio_phone: z.string(),
  address: z.string(),
  hours: z.string(),
  menu: z.record(z.string(), z.unknown()).default({}),
  prompt_overrides: z.record(z.string(), z.string()).default({}),
  forwarding_mode: z.enum(['always', 'busy', 'noanswer']).default('always'),
});

export type Restaurant = z.infer<typeof RestaurantSchema>;

export function isAwaitingNumber(r: Pick<Restaurant, 'twilio_phone'>): boolean {
  return r.twilio_phone.trim() === '';
}
