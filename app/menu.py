"""Hardcoded demo menu used by the Phase 1 POC voice agent.

Phase 2 moves restaurants + menus into Firestore; this module goes away
then. Keep it flat and easy to read — the LLM prompt formats it directly.
"""

MENU = {
    "restaurant": "Niko's Pizza Kitchen",
    "phone": "+1-647-905-8093",
    "address": "123 Main Street (demo)",
    "hours": "Monday-Sunday, 11am to 10pm",
    "pizzas": [
        {
            "name": "Margherita",
            "description": "Tomato, fresh mozzarella, basil",
            "sizes": {"small": 12.99, "medium": 16.99, "large": 20.99},
        },
        {
            "name": "Pepperoni",
            "description": "Tomato, mozzarella, pepperoni",
            "sizes": {"small": 13.99, "medium": 17.99, "large": 21.99},
        },
        {
            "name": "Hawaiian",
            "description": "Tomato, mozzarella, ham, pineapple",
            "sizes": {"small": 14.99, "medium": 18.99, "large": 22.99},
        },
        {
            "name": "Veggie Supreme",
            "description": "Tomato, mozzarella, bell peppers, onions, mushrooms, olives",
            "sizes": {"small": 14.99, "medium": 18.99, "large": 22.99},
        },
        {
            "name": "Meat Lovers",
            "description": "Tomato, mozzarella, pepperoni, sausage, bacon, ham",
            "sizes": {"small": 15.99, "medium": 19.99, "large": 23.99},
        },
    ],
    "sides": [
        {"name": "Garlic Knots", "price": 5.99},
        {"name": "Caesar Salad", "price": 8.99},
        {"name": "Buffalo Wings (6 pc)", "price": 9.99},
    ],
    "drinks": [
        {"name": "Coke", "price": 2.99},
        {"name": "Diet Coke", "price": 2.99},
        {"name": "Sprite", "price": 2.99},
        {"name": "Bottled Water", "price": 1.99},
    ],
}
