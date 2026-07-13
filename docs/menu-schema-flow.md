# Menu Schema Flow — Onboarding to Runtime

End-to-end example using **Mario's Pizza** (two items: Margherita $12.99, Garlic Bread $4.99).

---

## Step 1 — Skill scrapes the site and writes the JSON file

`restaurants/marios-pizza.json`
```json
{
  "_category_order": ["pizzas", "sides"],
  "pizzas": [
    { "name": "Margherita", "description": "Tomato, mozzarella, basil.", "price": 12.99 }
  ],
  "sides": [
    { "name": "Garlic Bread", "price": 4.99 }
  ]
}
```

---

## Step 2 — `provision_restaurant.py` loads the file and writes to Firestore

The script reads the JSON above and writes a `restaurants/marios-pizza` Firestore doc. The `menu` field is stored as-is — a raw dict.

---

## Step 3 — `app/restaurants/models.py` reads it back

When a call comes in, `app/storage/restaurants.py` fetches the Firestore doc and deserializes it via Pydantic:

```python
Restaurant(
    id="marios-pizza",
    name="Mario's Pizza",
    display_phone="+14161234567",
    twilio_phone="+16471234567",
    menu={
        "_category_order": ["pizzas", "sides"],
        "pizzas": [{"name": "Margherita", "description": "Tomato, mozzarella, basil.", "price": 12.99}],
        "sides":  [{"name": "Garlic Bread", "price": 4.99}]
    },
    ...
)
```

`menu` is still `dict[str, Any]` here — Pydantic does not validate the contents.

---

## Step 4 — `app/llm/prompts.py` renders it for the AI

`_format_menu()` iterates the categories (respecting `_category_order`) and produces:

```
Menu:

Pizzas:
- Margherita — Tomato, mozzarella, basil. $12.99

Sides:
- Garlic Bread — $4.99
```

This is injected into the system prompt the AI reads on every call.

---

## Step 5 — `dashboard/lib/schemas/menu.ts` parses it for display

`parseMenu()` runs the raw dict through Zod:

```ts
{
  categories: [
    { key: "pizzas", items: [{ name: "Margherita", description: "Tomato, mozzarella, basil.", price: 12.99, available: true }] },
    { key: "sides",  items: [{ name: "Garlic Bread", price: 4.99, available: true }] }
  ],
  itemCount: 2
}
```

`humanizeCategoryKey("pizzas")` → `"Pizzas"` for display labels.

---

## Summary — how each layer sees the menu

| Layer | Sees menu as | Validates? |
|---|---|---|
| JSON file | Raw JSON on disk | No |
| Firestore | Raw dict | No |
| `app/restaurants/models.py` | `dict[str, Any]` on `Restaurant` | No — intentionally loose |
| `app/llm/prompts.py` | Formatted text string for the AI | No |
| `dashboard/lib/schemas/menu.ts` | Typed `ParsedMenu` with `Category[]` and `MenuItem[]` | Yes — Zod, at read time |

The only hard validation gate is `menu.ts` on the dashboard. Everything upstream trusts the convention.
