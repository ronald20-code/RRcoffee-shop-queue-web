# QueueFree RR Cafe

Web-based self-ordering kiosk for a coffee shop and snack bar, built with **Python + Django**.
Customers log in, browse drinks and snacks with real product photos, pay digitally and track their queue number. Baristas see orders appear instantly on a **kitchen display** that shows orders only. The admin manages the whole menu, prices and photos from one page.

## Run it in VS Code

```bash
# open this folder in VS Code, then open the terminal (Ctrl+`)
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # macOS / Linux

pip install -r requirements.txt   # Django + Pillow (needed for photo uploads)

python manage.py migrate
python manage.py seed_menu        # menu, snack categories, demo accounts
python manage.py runserver
```

Open http://127.0.0.1:8000/ (internet needed for Google Fonts).
In VS Code select the `.venv` interpreter (Ctrl+Shift+P → *Python: Select Interpreter*).

### Upgrading an existing copy

Copy the new files over your folder, then run:

```bash
pip install -r requirements.txt
python manage.py migrate          # keeps your drinks, prices and orders
python manage.py seed_menu        # adds the new snack categories (existing items and passwords are untouched)
```

`seed_menu` only adds what is missing. It never overwrites a password unless you run `python manage.py seed_menu --reset-users`.

## Accounts (created by `seed_menu`)

| Role     | Username   | Password        | Lands on                       |
|----------|------------|-----------------|--------------------------------|
| Admin    | `admin`    | `admin12345`    | Menu manager (`/manage/menu/`) |
| Kitchen  | `kitchen`  | `kitchen12345`  | Customer orders (`/kitchen/`)  |
| Customer | `customer` | `customer12345` | Menu (`/`)                     |

Anyone can also register a customer account at `/register/`. Change or delete the demo accounts before real use (`/admin/` → Users, or `python manage.py changepassword kitchen`).

## The three views

**Customer** (`/`): tabs for Coffee-Based, Non-Coffee, Pastries, Cakes, Fries and Nachos. Each item shows its uploaded photo (or "Photo coming soon" until one is uploaded). Drinks let the customer pick a size and show Hot/Iced; snacks have no size options. Cart, payment (GCash / Maya / card / pay at counter), queue number with live progress, printable queue ticket.

**Admin** (`/manage/menu/`, admin account only):
- Add, edit and delete products; edit prices inline (auto-saves); hide or show a product on the kiosk.
- **Photos:** choose a JPG, JPEG or PNG (up to 5 MB) from your device. A live preview card shows exactly how it will look to customers *before* you save. Replace a photo by choosing a new one, remove it with the "Remove current photo" tick box, or delete the product (the file is removed from disk too).
- Categories: add, rename, reorder (↑ ↓) and delete (only when empty). Tick **Drinks** on a category if customers should choose size and hot/iced; leave it unticked for snacks.

**Kitchen** (`/kitchen/`, staff accounts): orders only. New / Preparing / Ready columns, order details, status buttons, sound alert for new orders, late-order highlight. There is no menu, category or product link anywhere on this screen, and kitchen accounts are redirected away from the customer menu.

## Admin and customer stay in sync

Both read the same database, so a change saved by the admin (product, price, photo, category, availability) is what customers get. An open customer menu checks for changes every 10 seconds and refreshes itself (the cart is kept). Prices are always recalculated on the server when an order is placed.

## Where things live

| File | What |
|---|---|
| `kiosk/models.py` | Category, Product (with `image`), Order, OrderItem |
| `kiosk/forms.py` | Product form incl. photo validation, resizing, EXIF clean-up |
| `kiosk/manage_views.py` | Admin: products, photos, categories |
| `kiosk/views.py` | Customer menu, ordering, payment, kitchen API |
| `kiosk/templates/kiosk/` | `menu.html` (customer), `manage_*.html` (admin), `kitchen.html` |
| `kiosk/static/kiosk/style.css` | All styling |
| `kiosk/management/commands/seed_menu.py` | Starting categories, products and demo accounts |
| `media/products/` | Uploaded photos (created automatically; back this folder up) |

Photos are stored with random file names, scaled down to at most 1200 px, and have their metadata (such as GPS location) stripped.

## Digital payments: important

`kiosk/payments.py` is a **sandbox**: GCash, Maya and card payments are simulated and no real money moves. Test card `4242 4242 4242 4242`, any future expiry, any CVC; wallets accept any number like `09171234567` and a 4-digit PIN. For real payments, implement `charge()` for a provider such as PayMongo, Xendit or Maya Checkout.

## Tests

```bash
python manage.py test kiosk
```

## Before going to production

Set `DEBUG = False`, a real `SECRET_KEY` and `ALLOWED_HOSTS`, use HTTPS, switch SQLite to PostgreSQL, run `collectstatic`, replace the sandbox payment gateway, and serve the `media/` folder with your web server (Django only serves uploaded photos itself while `DEBUG = True`).
