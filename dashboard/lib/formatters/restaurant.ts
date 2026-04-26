/**
 * Tiny display-name helpers for restaurants.
 *
 * Until the dashboard fetches the full ``restaurants/{rid}`` doc
 * server-side (a Phase 2.4 polish task), we humanize the rid for the
 * header / login banner. ``"niko-pizza-kitchen"`` → ``"Niko Pizza
 * Kitchen"``.
 */
export function humanizeRestaurantId(rid: string): string {
  if (!rid) return '';
  return rid
    .split('-')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}
