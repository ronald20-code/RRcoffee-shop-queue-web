from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from kiosk.models import Category, Product

# (name, description, price, serving)   serving: hot / iced
COFFEE = [
    ("Espresso", "Double shot, bold and smooth.", 90, "hot"),
    ("Americano", "Espresso with hot water.", 110, "hot"),
    ("Cappuccino", "Espresso, steamed milk, thick foam.", 130, "hot"),
    ("Café Latte", "Espresso with silky steamed milk.", 135, "hot"),
    ("Caramel Macchiato", "Vanilla, milk, espresso, caramel drizzle.", 155, "hot"),
    ("Mocha", "Espresso, chocolate, steamed milk.", 150, "hot"),
    ("Iced Latte", "Espresso over cold milk and ice.", 140, "iced"),
    ("Spanish Latte", "Sweet condensed-milk latte, served iced.", 160, "iced"),
    ("Iced Americano", "Espresso over ice and cold water.", 115, "iced"),
]

NON_COFFEE = [
    ("Matcha Latte", "Ceremonial matcha with steamed milk.", 150, "hot"),
    ("Iced Matcha", "Matcha whisked over milk and ice.", 155, "iced"),
    ("Hot Chocolate", "Rich cocoa topped with whipped cream.", 125, "hot"),
    ("Strawberry Milk", "Fresh strawberry swirled into cold milk.", 130, "iced"),
    ("Chai Latte", "Spiced black tea with steamed milk.", 135, "hot"),
    ("Lemon Iced Tea", "Black tea, lemon and a touch of honey.", 100, "iced"),
    ("Ube Latte", "Purple yam milk, naturally sweet.", 145, "iced"),
    ("Blue Lemonade", "Sparkling citrus cooler.", 105, "iced"),
]

# Snacks: (name, description, price)
PASTRIES = [
    ("Butter Croissant", "Flaky, golden and baked fresh.", 85),
    ("Chocolate Croissant", "Buttery croissant with a dark chocolate centre.", 105),
    ("Glazed Donut", "Classic ring donut with sweet glaze.", 60),
    ("Chocolate Donut", "Soft donut dipped in chocolate.", 70),
    ("Blueberry Muffin", "Moist muffin packed with blueberries.", 90),
    ("Chocolate Chip Cookie", "Chewy cookie with chocolate chunks.", 55),
]

CAKES = [
    ("New York Cheesecake", "Creamy baked cheesecake on a biscuit base.", 165),
    ("Chocolate Cake", "Rich, moist chocolate layer cake.", 150),
    ("Red Velvet Cupcake", "Cream cheese frosting on red velvet sponge.", 95),
    ("Vanilla Cupcake", "Light vanilla sponge with buttercream.", 85),
    ("Strawberry Cake Slice", "Fluffy sponge with fresh strawberry cream.", 155),
]

FRIES = [
    ("French Fries", "Crispy golden fries, lightly salted.", 95),
    ("Cheese Fries", "Fries smothered in warm cheese sauce.", 125),
    ("Sour Cream Fries", "Fries dusted with sour cream seasoning.", 110),
    ("BBQ Fries", "Fries tossed in smoky barbecue seasoning.", 110),
]

NACHOS = [
    ("Classic Nachos", "Crunchy tortilla chips with salsa.", 120),
    ("Cheese Nachos", "Tortilla chips with melted cheese sauce.", 140),
    ("Loaded Nachos", "Chips, cheese, beef, beans, jalapeños and salsa.", 195),
]

# slug, display name, sort order, is_drink
CATEGORIES = [
    ("coffee", "Coffee-Based", 1, True),
    ("non-coffee", "Non-Coffee", 2, True),
    ("pastries", "Pastries", 3, False),
    ("cakes", "Cakes", 4, False),
    ("fries", "Fries", 5, False),
    ("nachos", "Nachos", 6, False),
]


class Command(BaseCommand):
    help = (
        "Create menu categories and products, plus demo staff / customer accounts. "
        "Safe to run again: it only adds what is missing."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset-users",
            action="store_true",
            help="Also reset the demo accounts' passwords to the defaults.",
        )

    def handle(self, *args, **options):
        cats = {}
        for slug, name, order, is_drink in CATEGORIES:
            cats[slug], _ = Category.objects.get_or_create(
                slug=slug,
                defaults={"name": name, "sort_order": order, "is_drink": is_drink},
            )

        created = 0

        def add(cat, name, desc, price, serving="hot"):
            nonlocal created
            _, was_new = Product.objects.get_or_create(
                name=name,
                defaults=dict(
                    category=cat,
                    description=desc,
                    price=Decimal(price),
                    serving=serving,
                ),
            )
            created += was_new

        for name, desc, price, serving in COFFEE:
            add(cats["coffee"], name, desc, price, serving)
        for name, desc, price, serving in NON_COFFEE:
            add(cats["non-coffee"], name, desc, price, serving)
        for slug, rows in (
            ("pastries", PASTRIES),
            ("cakes", CAKES),
            ("fries", FRIES),
            ("nachos", NACHOS),
        ):
            for name, desc, price in rows:
                add(cats[slug], name, desc, price)

        self.stdout.write(self.style.SUCCESS(f"Menu ready ({created} new products)."))

        User = get_user_model()
        demo = [
            ("admin", "admin12345", True, True),
            ("kitchen", "kitchen12345", True, False),
            ("customer", "customer12345", False, False),
        ]
        for username, pw, staff, superuser in demo:
            u, was_new = User.objects.get_or_create(username=username)
            if was_new or options["reset_users"]:
                u.set_password(pw)
                u.is_active = True
                u.is_staff = staff
                u.is_superuser = superuser
                u.save()
                verb = "Created" if was_new else "Reset"
                self.stdout.write(f"{verb} demo user '{username}' / '{pw}'")
        self.stdout.write(
            self.style.WARNING(
                "Demo accounts are for development only. Use --reset-users to restore "
                "their default passwords. Change them before real deployment."
            )
        )
