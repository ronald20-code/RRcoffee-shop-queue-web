import io
import json
import os
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import Category, Order, OrderItem, Product
from .payments import luhn_ok

User = get_user_model()

def make_image(fmt="PNG", size=(40, 30), color=(200, 120, 60), exif_orientation=None):
    buf = io.BytesIO()
    img = Image.new("RGB", size, color)
    kwargs = {}
    if exif_orientation:
        exif = Image.Exif()
        exif[0x0112] = exif_orientation
        kwargs["exif"] = exif
    img.save(buf, format=fmt, **kwargs)
    return buf.getvalue()


def upload(name, data, ctype="image/png"):
    return SimpleUploadedFile(name, data, content_type=ctype)


def product_fields(category, **extra):
    data = {
        "name": "Test Product",
        "category": category.pk,
        "description": "Tasty.",
        "price": "100",
        "serving": "hot",
        "is_available": "on",
    }
    data.update(extra)
    return data


class KioskFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_menu", verbosity=0)

    def setUp(self):
        # every test gets its own empty media folder, removed afterwards
        self.media = tempfile.mkdtemp(prefix="qf_media_")
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        self.client.login(username="customer", password="customer12345")

    def _as(self, username, password):
        self.client.logout()
        self.assertTrue(self.client.login(username=username, password=password))

    def _order(self, lines=None):
        p = Product.objects.get(name="Café Latte")
        lines = lines or [{"id": p.id, "qty": 2, "size": "Large", "note": "extra hot"}]
        return self.client.post(
            reverse("kiosk:place_order"),
            data=json.dumps({"items": lines, "name": "Ana"}),
            content_type="application/json",
        )

    def _menu_names(self):
        return [x["name"] for x in self.client.get(reverse("kiosk:menu")).context["products_json"]]

    # ------------------------------------------------------------ auth
    def test_login_page_and_redirects(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("login")).status_code, 200)
        r = self.client.get(reverse("kiosk:menu"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login/", r["Location"])

    def test_register(self):
        self.client.logout()
        r = self.client.post(reverse("register"), {"username": "newbie", "password1": "Sup3rSecret!x", "password2": "Sup3rSecret!x"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(User.objects.filter(username="newbie").exists())

    def test_each_role_lands_on_its_own_page_after_login(self):
        for user, pw, expected in (
            ("customer", "customer12345", "/"),
            ("kitchen", "kitchen12345", "/kitchen/"),
            ("admin", "admin12345", "/manage/menu/"),
        ):
            self.client.logout()
            r = self.client.post(reverse("login"), {"username": user, "password": pw})
            self.assertEqual(r.status_code, 302)
            self.assertEqual(r["Location"], reverse("kiosk:home"))
            self.assertEqual(self.client.get(reverse("kiosk:home"))["Location"], expected, user)

    def test_seed_does_not_overwrite_changed_passwords(self):
        u = User.objects.get(username="kitchen")
        u.set_password("my-own-password-1"); u.save()
        call_command("seed_menu", verbosity=0)
        self.assertTrue(User.objects.get(username="kitchen").check_password("my-own-password-1"))
        call_command("seed_menu", "--reset-users", verbosity=0)
        self.assertTrue(User.objects.get(username="kitchen").check_password("kitchen12345"))

    # ------------------------------------------------------------ menu & categories
    def test_snack_categories_exist_with_expected_products(self):
        cats = {c.name: c for c in Category.objects.all()}
        for name in ("Coffee-Based", "Non-Coffee", "Pastries", "Cakes", "Fries", "Nachos"):
            self.assertIn(name, cats)
        for snack in ("Pastries", "Cakes", "Fries", "Nachos"):
            self.assertFalse(cats[snack].is_drink)
        names = lambda cat: " ".join(cats[cat].products.values_list("name", flat=True))
        for word in ("Croissant", "Donut", "Muffin", "Cookie"):
            self.assertIn(word, names("Pastries"))
        for word in ("Cheesecake", "Chocolate Cake", "Cupcake", "Cake Slice"):
            self.assertIn(word, names("Cakes"))
        for word in ("French Fries", "Cheese Fries", "BBQ Fries"):
            self.assertIn(word, names("Fries"))
        for word in ("Classic Nachos", "Cheese Nachos", "Loaded Nachos"):
            self.assertIn(word, names("Nachos"))

    def test_customer_menu_shows_all_categories_and_no_3d(self):
        r = self.client.get(reverse("kiosk:menu"))
        self.assertEqual(r.status_code, 200)
        for name in ("Coffee-Based", "Non-Coffee", "Pastries", "Cakes", "Fries", "Nachos"):
            self.assertContains(r, name)
        self.assertContains(r, "Loaded Nachos")
        self.assertNotContains(r, "three.min.js")
        self.assertNotContains(r, "cup3d")
        self.assertEqual(len(r.context["products_json"]), Product.objects.count())

    def test_empty_category_is_hidden_from_customers(self):
        Category.objects.create(name="Sandwiches", slug="sandwiches", sort_order=9, is_drink=False)
        self.assertNotContains(self.client.get(reverse("kiosk:menu")), "Sandwiches")

    # ------------------------------------------------------------ ordering
    def test_server_side_pricing_for_drinks(self):
        r = self._order()
        self.assertEqual(r.status_code, 200)
        order = Order.objects.get()
        self.assertEqual(float(order.total), 310.0)  # (135 + 20 Large) x 2
        item = order.items.get()
        self.assertEqual((item.size, item.temperature), ("Large", "Hot"))

    def test_drink_temperature_comes_from_product_not_client(self):
        iced = Product.objects.get(name="Iced Latte")
        self._order([{"id": iced.id, "qty": 1, "size": "Regular", "temp": "Hot"}])
        self.assertEqual(OrderItem.objects.get().temperature, "Iced")

    def test_snacks_have_no_size_or_temperature_and_no_upcharge(self):
        nachos = Product.objects.get(name="Cheese Nachos")
        r = self._order([{"id": nachos.id, "qty": 2, "size": "Large"}])  # size must be ignored
        self.assertEqual(r.status_code, 200)
        item = OrderItem.objects.get()
        self.assertEqual((item.size, item.temperature, item.options_label), ("", "", ""))
        self.assertEqual(float(Order.objects.get().total), float(nachos.price) * 2)

    def test_empty_cart_rejected(self):
        r = self.client.post(reverse("kiosk:place_order"), data=json.dumps({"items": []}), content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def test_cannot_order_hidden_product(self):
        p = Product.objects.get(name="Mocha")
        p.is_available = False; p.save()
        self.assertEqual(self._order([{"id": p.id, "qty": 1}]).status_code, 400)
        self.assertEqual(Order.objects.count(), 0)

    # ------------------------------------------------------------ payments
    def test_wallet_payment_success(self):
        self._order()
        order = Order.objects.get()
        r = self.client.post(reverse("kiosk:pay", args=[order.pk]), {"method": "gcash", "mobile": "09171234567", "pin": "1234"})
        self.assertEqual(r.status_code, 302)
        order.refresh_from_db()
        self.assertEqual((order.payment_status, order.status), ("paid", "received"))
        self.assertTrue(order.payment_reference.startswith("GC-"))

    def test_bad_card_fails_and_order_stays_unpaid(self):
        self._order()
        order = Order.objects.get()
        r = self.client.post(reverse("kiosk:pay", args=[order.pk]), {"method": "card", "number": "1234 5678 9012 3456", "expiry": "12/30", "cvc": "123"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "not valid")
        order.refresh_from_db()
        self.assertEqual(order.status, "pending_payment")

    def test_good_card(self):
        self.assertTrue(luhn_ok("4242 4242 4242 4242"))
        self._order()
        order = Order.objects.get()
        self.client.post(reverse("kiosk:pay", args=[order.pk]), {"method": "card", "number": "4242 4242 4242 4242", "expiry": "12/30", "cvc": "123"})
        order.refresh_from_db()
        self.assertEqual(order.payment_status, "paid")

    def test_cash_goes_to_kitchen_unpaid(self):
        self._order()
        order = Order.objects.get()
        self.client.post(reverse("kiosk:pay", args=[order.pk]), {"method": "cash"})
        order.refresh_from_db()
        self.assertEqual((order.status, order.payment_status), ("received", "unpaid"))

    # ------------------------------------------------------------ kitchen: orders only
    def test_kitchen_is_staff_only(self):
        self.assertEqual(self.client.get(reverse("kiosk:kitchen")).status_code, 302)
        self.assertEqual(self.client.get(reverse("kiosk:kitchen_api")).status_code, 302)

    def test_kitchen_page_has_no_menu_section(self):
        for user, pw in (("kitchen", "kitchen12345"), ("admin", "admin12345")):
            self._as(user, pw)
            r = self.client.get(reverse("kiosk:kitchen"))
            self.assertEqual(r.status_code, 200)
            for text in ("Menu manager", "Customer view", ">Menu<", "My orders", "manage/menu",
                         'href="/"', "Coffee-Based", "Pastries", "Cakes", "Nachos", "Café Latte"):
                self.assertNotContains(r, text, msg_prefix=f"{user}: ")
            self.assertContains(r, "Customer orders")

    def test_kitchen_staff_are_kept_away_from_customer_screens(self):
        self._as("kitchen", "kitchen12345")
        self.assertEqual(self.client.get(reverse("kiosk:menu"))["Location"], reverse("kiosk:kitchen"))
        self.assertEqual(self.client.get(reverse("kiosk:my_orders"))["Location"], reverse("kiosk:kitchen"))
        self.assertEqual(self.client.get(reverse("kiosk:manage_menu")).status_code, 403)

    def test_customers_still_see_menu_and_my_orders(self):
        r = self.client.get(reverse("kiosk:menu"))
        self.assertContains(r, "My orders")
        self.assertNotContains(r, "Kitchen orders")
        self.assertNotContains(r, "Menu manager")

    def test_kitchen_flow_and_customer_status(self):
        self._order()
        order = Order.objects.get()
        self.client.post(reverse("kiosk:pay", args=[order.pk]), {"method": "cash"})

        self._as("kitchen", "kitchen12345")
        data = self.client.get(reverse("kiosk:kitchen_api")).json()
        self.assertEqual(len(data["orders"]), 1)
        o = data["orders"][0]
        self.assertEqual(o["items"][0]["name"], "Café Latte")
        self.assertEqual(o["items"][0]["opts"], "Large · Hot")
        self.assertEqual(set(o), {"id", "label", "name", "status", "paid", "method", "total", "notes", "age", "items"})  # orders only

        for status in ("preparing", "ready"):
            self.client.post(reverse("kiosk:kitchen_update", args=[order.pk]), {"status": status})
            self.assertEqual(self.client.get(reverse("kiosk:order_status_api", args=[order.pk])).json()["status"], status)

        board = self.client.get(reverse("kiosk:board_api")).json()
        self.assertEqual(board["ready"], [order.label])

        self.client.post(reverse("kiosk:kitchen_update", args=[order.pk]), {"status": "completed"})
        order.refresh_from_db()
        self.assertEqual((order.status, order.payment_status), ("completed", "paid"))
        self.assertEqual(self.client.get(reverse("kiosk:kitchen_api")).json()["orders"], [])

    def test_customer_cannot_see_others_orders(self):
        self._order()
        order = Order.objects.get()
        User.objects.create_user("other", password="otherpass123")
        self._as("other", "otherpass123")
        self.assertEqual(self.client.get(reverse("kiosk:order_status_api", args=[order.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("kiosk:pay", args=[order.pk])).status_code, 404)

    def test_queue_numbers_increment(self):
        self._order(); self._order()
        self.assertEqual(list(Order.objects.values_list("queue_number", flat=True)), [1, 2])

    def test_status_page_has_printable_ticket_and_next_order_button(self):
        self._order()
        order = Order.objects.get()
        self.client.post(reverse("kiosk:pay", args=[order.pk]), {"method": "cash"})
        r = self.client.get(reverse("kiosk:order_status", args=[order.pk]))
        self.assertContains(r, 'class="print-ticket"')
        self.assertContains(r, f'<div class="pt-number">{order.label}</div>', html=True)
        self.assertContains(r, "Print queue number")
        self.assertContains(r, "Next order")

    def test_snack_order_pages_render_without_blank_options(self):
        nachos = Product.objects.get(name="Loaded Nachos")
        self._order([{"id": nachos.id, "qty": 1}])
        order = Order.objects.get()
        r = self.client.get(reverse("kiosk:pay", args=[order.pk]))
        self.assertContains(r, "Loaded Nachos")
        self.assertNotContains(r, " ·  ·")
        self.client.post(reverse("kiosk:pay", args=[order.pk]), {"method": "cash"})
        self.assertEqual(self.client.get(reverse("kiosk:order_status", args=[order.pk])).status_code, 200)

    def test_public_board_page(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("kiosk:board")).status_code, 200)

    # ------------------------------------------------------------ admin: permissions
    def test_menu_manager_permissions(self):
        url = reverse("kiosk:manage_menu")
        self.assertEqual(self.client.get(url).status_code, 403)  # customer
        self._as("kitchen", "kitchen12345")
        self.assertEqual(self.client.get(url).status_code, 403)  # staff but not admin
        self._as("admin", "admin12345")
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        for name in ("Menu manager", "Café Latte", "Pastries", "Cakes", "Fries", "Nachos"):
            self.assertContains(r, name)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_customer_and_kitchen_cannot_upload_or_change_things(self):
        cat = Category.objects.get(slug="pastries")
        for user, pw in (("customer", "customer12345"), ("kitchen", "kitchen12345")):
            self._as(user, pw)
            r = self.client.post(reverse("kiosk:product_create"), product_fields(cat, image=upload("a.png", make_image())))
            self.assertEqual(r.status_code, 403)
            p = Product.objects.get(name="Americano")
            self.assertEqual(self.client.post(reverse("kiosk:product_quick", args=[p.pk]), {"price": "1"}).status_code, 403)
        self.assertFalse(Product.objects.filter(name="Test Product").exists())

    # ------------------------------------------------------------ admin: products
    def test_add_snack_product_with_png_photo(self):
        self._as("admin", "admin12345")
        cat = Category.objects.get(slug="pastries")
        r = self.client.post(reverse("kiosk:product_create"), product_fields(cat, name="Almond Croissant", price="115", image=upload("my photo.PNG", make_image("PNG"))))
        self.assertEqual(r.status_code, 302)
        p = Product.objects.get(name="Almond Croissant")
        self.assertEqual(float(p.price), 115.0)
        self.assertTrue(p.image.name.startswith("products/") and p.image.name.endswith(".png"))
        self.assertNotIn("my photo", p.image.name)  # original file name is never trusted
        self.assertTrue(os.path.exists(p.image.path))
        with Image.open(p.image.path) as im:
            self.assertEqual(im.format, "PNG")

    def test_jpg_and_jpeg_uploads_are_accepted(self):
        self._as("admin", "admin12345")
        cat = Category.objects.get(slug="cakes")
        for i, ext in enumerate((".jpg", ".jpeg", ".JPG")):
            r = self.client.post(reverse("kiosk:product_create"), product_fields(cat, name=f"Cake {i}", image=upload(f"cake{ext}", make_image("JPEG"), "image/jpeg")))
            self.assertEqual(r.status_code, 302, ext)
            p = Product.objects.get(name=f"Cake {i}")
            with Image.open(p.image.path) as im:
                self.assertEqual(im.format, "JPEG")

    def test_uploaded_photo_shows_on_customer_menu(self):
        self._as("admin", "admin12345")
        cat = Category.objects.get(slug="fries")
        self.client.post(reverse("kiosk:product_create"), product_fields(cat, name="Truffle Fries", image=upload("t.png", make_image())))
        p = Product.objects.get(name="Truffle Fries")
        self._as("customer", "customer12345")
        r = self.client.get(reverse("kiosk:menu"))
        self.assertContains(r, f'src="{p.image.url}"')
        entry = next(x for x in r.context["products_json"] if x["name"] == "Truffle Fries")
        self.assertEqual(entry["image"], p.image.url)

    def test_products_without_photo_show_placeholder_not_3d(self):
        r = self.client.get(reverse("kiosk:menu"))
        self.assertContains(r, "Photo coming soon")
        self.assertNotContains(r, "<canvas")

    def test_invalid_uploads_are_rejected(self):
        self._as("admin", "admin12345")
        cat = Category.objects.get(slug="pastries")
        gif = io.BytesIO(); Image.new("RGB", (10, 10)).save(gif, format="GIF")
        bmp = io.BytesIO(); Image.new("RGB", (10, 10)).save(bmp, format="BMP")
        webp_as_jpg = io.BytesIO(); Image.new("RGB", (10, 10)).save(webp_as_jpg, format="WEBP")
        cases = {
            "text renamed .png": upload("evil.png", b"this is not an image at all"),
            "script renamed .jpg": upload("x.jpg", b"<script>alert(1)</script>", "image/jpeg"),
            "gif": upload("a.gif", gif.getvalue(), "image/gif"),
            "bmp": upload("a.bmp", bmp.getvalue(), "image/bmp"),
            "webp disguised as .jpg": upload("a.jpg", webp_as_jpg.getvalue(), "image/jpeg"),
            "pdf": upload("a.pdf", b"%PDF-1.4", "application/pdf"),
        }
        for label, f in cases.items():
            r = self.client.post(reverse("kiosk:product_create"), product_fields(cat, name="Bad Upload", image=f))
            self.assertEqual(r.status_code, 200, label)  # form re-shown with an error
            self.assertTrue(r.context["form"].errors.get("image"), label)
        self.assertFalse(Product.objects.filter(name="Bad Upload").exists())
        products_dir = os.path.join(self.media, "products")
        self.assertEqual(os.listdir(products_dir) if os.path.isdir(products_dir) else [], [])  # nothing saved

    def test_oversized_upload_is_rejected(self):
        self._as("admin", "admin12345")
        cat = Category.objects.get(slug="pastries")
        noise = Image.frombytes("RGB", (1800, 1800), os.urandom(1800 * 1800 * 3))
        buf = io.BytesIO(); noise.save(buf, format="PNG")
        self.assertGreater(len(buf.getvalue()), 5 * 1024 * 1024)
        r = self.client.post(reverse("kiosk:product_create"), product_fields(cat, name="Huge", image=upload("huge.png", buf.getvalue())))
        self.assertEqual(r.status_code, 200)
        self.assertIn("too large", " ".join(r.context["form"].errors["image"]))
        self.assertFalse(Product.objects.filter(name="Huge").exists())

    def test_large_photos_are_resized_and_phone_rotation_is_applied(self):
        self._as("admin", "admin12345")
        cat = Category.objects.get(slug="cakes")
        self.client.post(reverse("kiosk:product_create"), product_fields(cat, name="Big", image=upload("big.jpg", make_image("JPEG", (3000, 2000)), "image/jpeg")))
        with Image.open(Product.objects.get(name="Big").image.path) as im:
            self.assertEqual(max(im.size), 1200)
        # EXIF orientation 6 = rotated 90°: a 100x50 file should end up 50x100
        self.client.post(reverse("kiosk:product_create"), product_fields(cat, name="Rot", image=upload("r.jpg", make_image("JPEG", (100, 50), exif_orientation=6), "image/jpeg")))
        with Image.open(Product.objects.get(name="Rot").image.path) as im:
            self.assertEqual(im.size, (50, 100))
            self.assertFalse(im.getexif())  # metadata stripped

    def test_replace_photo_deletes_the_old_file(self):
        self._as("admin", "admin12345")
        p = Product.objects.get(name="Butter Croissant")
        url = reverse("kiosk:product_edit", args=[p.pk])
        fields = product_fields(p.category, name=p.name, price="85")
        self.client.post(url, {**fields, "image": upload("one.png", make_image("PNG", color=(1, 2, 3)))})
        p.refresh_from_db(); first = p.image.path
        self.assertTrue(os.path.exists(first))
        self.client.post(url, {**fields, "image": upload("two.jpg", make_image("JPEG"), "image/jpeg")})
        p.refresh_from_db()
        self.assertNotEqual(p.image.path, first)
        self.assertFalse(os.path.exists(first))  # old photo cleaned up
        self.assertTrue(os.path.exists(p.image.path))

    def test_editing_without_new_photo_keeps_the_photo(self):
        self._as("admin", "admin12345")
        p = Product.objects.get(name="Glazed Donut")
        url = reverse("kiosk:product_edit", args=[p.pk])
        fields = product_fields(p.category, name=p.name, price="60")
        self.client.post(url, {**fields, "image": upload("d.png", make_image())})
        p.refresh_from_db(); kept = p.image.name
        self.client.post(url, {**fields, "price": "65"})
        p.refresh_from_db()
        self.assertEqual((p.image.name, float(p.price)), (kept, 65.0))
        self.assertTrue(os.path.exists(p.image.path))

    def test_remove_photo_with_checkbox(self):
        self._as("admin", "admin12345")
        p = Product.objects.get(name="Chocolate Donut")
        url = reverse("kiosk:product_edit", args=[p.pk])
        fields = product_fields(p.category, name=p.name, price="70")
        self.client.post(url, {**fields, "image": upload("d.png", make_image())})
        p.refresh_from_db(); path = p.image.path
        self.assertTrue(os.path.exists(path))
        self.client.post(url, {**fields, "remove_image": "on"})
        p.refresh_from_db()
        self.assertEqual(p.image.name, "")
        self.assertFalse(os.path.exists(path))

    def test_remove_photo_button_endpoint(self):
        self._as("admin", "admin12345")
        p = Product.objects.get(name="Blueberry Muffin")
        self.client.post(reverse("kiosk:product_edit", args=[p.pk]), {**product_fields(p.category, name=p.name, price="90"), "image": upload("m.png", make_image())})
        p.refresh_from_db(); path = p.image.path
        self.client.post(reverse("kiosk:product_remove_photo", args=[p.pk]))
        p.refresh_from_db()
        self.assertEqual(p.image.name, "")
        self.assertFalse(os.path.exists(path))

    def test_deleting_a_product_deletes_its_photo(self):
        self._as("admin", "admin12345")
        cat = Category.objects.get(slug="nachos")
        self.client.post(reverse("kiosk:product_create"), product_fields(cat, name="Temp Nachos", image=upload("n.png", make_image())))
        p = Product.objects.get(name="Temp Nachos"); path = p.image.path
        self.client.post(reverse("kiosk:product_delete", args=[p.pk]))
        self.assertFalse(Product.objects.filter(pk=p.pk).exists())
        self.assertFalse(os.path.exists(path))

    def test_product_form_validation(self):
        self._as("admin", "admin12345")
        cat = Category.objects.get(slug="coffee")
        url = reverse("kiosk:product_create")
        for bad in (
            {"name": "Café Latte", "price": "100"},
            {"name": "Free Coffee", "price": "0"},
            {"name": "Odd Coffee", "price": "99.50"},
        ):
            r = self.client.post(url, product_fields(cat, **bad))
            self.assertEqual(r.status_code, 200, bad)
        self.assertFalse(Product.objects.filter(name__in=["Free Coffee", "Odd Coffee"]).exists())

    def test_edit_form_prefills_and_saves(self):
        self._as("admin", "admin12345")
        p = Product.objects.get(name="Mocha")
        r = self.client.get(reverse("kiosk:product_edit", args=[p.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'value="150"')
        self.assertNotContains(r, "<canvas")
        r = self.client.post(reverse("kiosk:product_edit", args=[p.pk]), product_fields(p.category, name="Mocha", description="Better.", price="170"))
        self.assertEqual(r.status_code, 302)
        p.refresh_from_db()
        self.assertEqual((float(p.price), p.description), (170.0, "Better."))

    def test_add_product_link_preselects_category(self):
        self._as("admin", "admin12345")
        cat = Category.objects.get(slug="nachos")
        r = self.client.get(reverse("kiosk:product_create") + f"?category={cat.pk}")
        self.assertEqual(r.context["form"]["category"].value(), cat.pk)

    def test_quick_price_and_availability(self):
        self._as("admin", "admin12345")
        p = Product.objects.get(name="Americano")
        url = reverse("kiosk:product_quick", args=[p.pk])
        self.assertEqual(self.client.post(url, {"price": "125"}).status_code, 200)
        p.refresh_from_db(); self.assertEqual(float(p.price), 125.0)
        for bad in ("abc", "-5", "0", "12.5", "NaN", "Infinity", "999999"):
            self.assertEqual(self.client.post(url, {"price": bad}).status_code, 400, bad)
        p.refresh_from_db(); self.assertEqual(float(p.price), 125.0)
        self.client.post(url, {"is_available": "0"})
        self._as("customer", "customer12345")
        self.assertNotIn("Americano", self._menu_names())

    def test_delete_unused_product_but_hide_one_with_orders(self):
        self._order()
        self._as("admin", "admin12345")
        latte = Product.objects.get(name="Café Latte")
        self.client.post(reverse("kiosk:product_delete", args=[latte.pk]))
        latte.refresh_from_db()
        self.assertFalse(latte.is_available)
        unused = Product.objects.get(name="Blue Lemonade")
        self.client.post(reverse("kiosk:product_delete", args=[unused.pk]))
        self.assertFalse(Product.objects.filter(pk=unused.pk).exists())

    # ------------------------------------------------------------ admin: categories
    def test_add_rename_and_delete_category(self):
        self._as("admin", "admin12345")
        self.client.post(reverse("kiosk:category_create"), {"name": "Sandwiches"})  # is_drink unticked = snack
        self.client.post(reverse("kiosk:category_create"), {"name": "Smoothies", "is_drink": "on"})
        sand = Category.objects.get(name="Sandwiches"); smooth = Category.objects.get(name="Smoothies")
        self.assertEqual((sand.slug, sand.is_drink, smooth.is_drink), ("sandwiches", False, True))
        self.assertGreater(smooth.sort_order, sand.sort_order)

        self.client.post(reverse("kiosk:category_create"), {"name": "sandwiches"})  # duplicate name refused
        self.assertEqual(Category.objects.filter(name__iexact="sandwiches").count(), 1)

        self.client.post(reverse("kiosk:category_edit", args=[sand.pk]), {"name": "Sandwiches & Wraps"})
        sand.refresh_from_db(); self.assertEqual(sand.name, "Sandwiches & Wraps")

        pastries = Category.objects.get(slug="pastries")
        self.client.post(reverse("kiosk:category_delete", args=[pastries.pk]))
        self.assertTrue(Category.objects.filter(pk=pastries.pk).exists())  # still has products
        self.client.post(reverse("kiosk:category_delete", args=[sand.pk]))
        self.assertFalse(Category.objects.filter(pk=sand.pk).exists())

    def test_new_category_and_product_appear_for_customers(self):
        self._as("admin", "admin12345")
        self.client.post(reverse("kiosk:category_create"), {"name": "Sandwiches"})
        cat = Category.objects.get(name="Sandwiches")
        self.client.post(reverse("kiosk:product_create"), product_fields(cat, name="Club Sandwich", price="180"))
        self._as("customer", "customer12345")
        r = self.client.get(reverse("kiosk:menu"))
        self.assertContains(r, "Sandwiches")
        self.assertContains(r, "Club Sandwich")

    def test_move_category_changes_customer_order(self):
        self._as("admin", "admin12345")
        cakes = Category.objects.get(slug="cakes")
        self.client.post(reverse("kiosk:category_move", args=[cakes.pk, "up"]))
        order = list(Category.objects.values_list("slug", flat=True))
        self.assertLess(order.index("cakes"), order.index("pastries"))
        self._as("customer", "customer12345")
        slugs = [s["category"].slug for s in self.client.get(reverse("kiosk:menu")).context["sections"]]
        self.assertLess(slugs.index("cakes"), slugs.index("pastries"))

    # ------------------------------------------------------------ admin <-> customer sync
    def test_menu_version_changes_when_admin_edits_anything(self):
        version = lambda: self.client.get(reverse("kiosk:menu_version")).json()["version"]
        v0 = version()
        self.assertEqual(version(), v0)  # stable when nothing changed

        self._as("admin", "admin12345")
        p = Product.objects.get(name="Cheese Fries")
        self.client.post(reverse("kiosk:product_quick", args=[p.pk]), {"price": "130"})
        self._as("customer", "customer12345"); v1 = version()
        self.assertNotEqual(v1, v0)
        self.assertContains(self.client.get(reverse("kiosk:menu")), "₱130")

        self._as("admin", "admin12345")
        self.client.post(reverse("kiosk:product_edit", args=[p.pk]), {**product_fields(p.category, name=p.name, price="130"), "image": upload("f.png", make_image())})
        self._as("customer", "customer12345"); v2 = version()
        self.assertNotEqual(v2, v1)  # new photo -> version changes

        self._as("admin", "admin12345")
        self.client.post(reverse("kiosk:category_edit", args=[p.category_id]), {"name": "Fries & Sides"})
        self._as("customer", "customer12345"); v3 = version()
        self.assertNotEqual(v3, v2)  # category rename -> version changes
        self.assertContains(self.client.get(reverse("kiosk:menu")), "Fries &amp; Sides")

    def test_customer_menu_shows_admin_changes_immediately(self):
        self._as("admin", "admin12345")
        p = Product.objects.get(name="Classic Nachos")
        self.client.post(reverse("kiosk:product_edit", args=[p.pk]), product_fields(p.category, name="Super Nachos", description="Now bigger.", price="150"))
        self._as("customer", "customer12345")
        r = self.client.get(reverse("kiosk:menu"))
        self.assertContains(r, "Super Nachos")
        self.assertContains(r, "Now bigger.")
        self.assertNotContains(r, "Classic Nachos")
