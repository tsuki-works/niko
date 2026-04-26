"""Per-restaurant configuration: identity, menu, prompt overrides.

PR A of Sprint 2.1 (#79). Until #4 (the parent sprint) closes, the only
consumer is the demo restaurant ``niko-pizza-kitchen``. The Twilio
inbound-routing path lands in PR B; see ``app/storage/restaurants.py``
for how restaurants are loaded and the fallback semantics.
"""

from app.restaurants.models import Restaurant

__all__ = ["Restaurant"]
