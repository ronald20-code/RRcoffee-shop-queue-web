import hashlib
import json
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.forms import UserCreationForm
from django.db import transaction
from django.db.models import Prefetch
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Category, Order, OrderItem, Product
from .payments import get_gateway

# Size prices apply to drink categories only.
SIZE_UPCHARGE = {"Small": Decimal("-10"), "Regular": Decimal("0"), "Large": Decimal("20")}

staff_required = user_passes_test(lambda u: u.is_authenticated and u.is_staff, login_url="login")


def is_kitchen_only(user):
    """Kitchen staff: staff accounts that are not the admin."""
    return user.is_staff and not user.is_superuser


# --------------------------------------------------------------------- auth
def register(request):
    if request.user.is_authenticated:
        return redirect("kiosk:home")
    form = UserCreationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Welcome to QueueFree RR Cafe!")
        return redirect("kiosk:menu")
    return render(request, "kiosk/register.html", {"form": form})


@login_required
def home(request):
    """Send each role to its own page after login."""
    if request.user.is_superuser:
        return redirect("kiosk:manage_menu")
    if request.user.is_staff:
        return redirect("kiosk:kitchen")
    return redirect("kiosk:menu")


# --------------------------------------------------------------------- menu data
def _product_payload(p):
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "price": float(p.price),
        "category": p.category.slug,
        "is_drink": p.category.is_drink,
        "serving": p.serving,
        "image": p.image_url,
    }


def menu_sections():
    """Categories (in menu order) with their available products. Empty ones are skipped.

    The customer menu, the version check and the admin all read the same
    database rows, so a change made by the admin shows up for customers
    without any extra syncing step.
    """
    categories = Category.objects.prefetch_related(
        Prefetch(
            "products",
            queryset=Product.objects.filter(is_available=True)
            .select_related("category")
            .order_by("name"),
            to_attr="available_products",
        )
    )
    return [
        {"category": c, "products": c.available_products}
        for c in categories
        if c.available_products
    ]


def _menu_version(sections):
    data = [
        [
            s["category"].id,
            s["category"].name,
            s["category"].is_drink,
            [_product_payload(p) for p in s["products"]],
        ]
        for s in sections
    ]
    return hashlib.md5(json.dumps(data, sort_keys=True).encode()).hexdigest()[:12]


# --------------------------------------------------------------------- kiosk
@login_required
def menu(request):
    if is_kitchen_only(request.user):
        return redirect("kiosk:kitchen")  # the kitchen never sees the menu
    sections = menu_sections()
    products_json = [_product_payload(p) for s in sections for p in s["products"]]
    return render(
        request,
        "kiosk/menu.html",
        {
            "sections": sections,
            "products_json": products_json,
            "menu_version": _menu_version(sections),
            "size_upcharge": {k: float(v) for k, v in SIZE_UPCHARGE.items()},
        },
    )


@login_required
def menu_version(request):
    """Polled by the customer menu: if this changes, the admin edited the menu."""
    return JsonResponse({"version": _menu_version(menu_sections())})


@login_required
@require_POST
def place_order(request):
    """Create an order from the cart (JSON) and send the customer to payment."""
    try:
        data = json.loads(request.body)
        cart = data.get("items", [])
    except (ValueError, AttributeError):
        return JsonResponse({"error": "Invalid cart."}, status=400)
    if not cart or not isinstance(cart, list):
        return JsonResponse({"error": "Your cart is empty."}, status=400)

    with transaction.atomic():
        order = Order.objects.create(
            user=request.user,
            customer_name=(data.get("name") or request.user.get_username())[:80],
            notes=(data.get("notes") or "")[:200],
        )
        for line in cart:
            if not isinstance(line, dict):
                transaction.set_rollback(True)
                return JsonResponse({"error": "Invalid cart."}, status=400)
            product = (
                Product.objects.select_related("category")
                .filter(pk=line.get("id"), is_available=True)
                .first()
            )
            if not product:
                transaction.set_rollback(True)
                return JsonResponse(
                    {"error": "An item is no longer on the menu. Please refresh and check your order."},
                    status=400,
                )
            try:
                qty = max(1, min(20, int(line.get("qty", 1))))
            except (TypeError, ValueError):
                qty = 1

            # Price, size and temperature are all decided on the server.
            if product.category.is_drink:
                size = line.get("size", "Regular")
                if size not in SIZE_UPCHARGE:
                    size = "Regular"
                unit_price = product.price + SIZE_UPCHARGE[size]
                temperature = product.get_serving_display()
            else:
                size, temperature, unit_price = "", "", product.price

            OrderItem.objects.create(
                order=order,
                product=product,
                name=product.name,
                unit_price=unit_price,
                quantity=qty,
                size=size,
                temperature=temperature,
                note=(line.get("note") or "")[:120],
            )
        order.recalc_total()
    return JsonResponse({"redirect": f"/pay/{order.pk}/"})


# ------------------------------------------------------------------- payment
@login_required
def pay(request, pk):
    order = get_object_or_404(Order, pk=pk, user=request.user)
    if order.payment_status == "paid" or order.status != "pending_payment":
        return redirect("kiosk:order_status", pk=order.pk)

    error = ""
    if request.method == "POST":
        method = request.POST.get("method", "")
        if method == "cash":
            order.payment_method = "cash"
            order.status = "received"
            order.save()
            return redirect("kiosk:order_status", pk=order.pk)

        result = get_gateway().charge(method, order.total, request.POST)
        if result.success:
            order.payment_method = method
            order.payment_status = "paid"
            order.payment_reference = result.reference
            order.status = "received"
            order.save()
            return redirect("kiosk:order_status", pk=order.pk)
        error = result.message
        order.payment_method = method
        order.payment_status = "failed"
        order.save(update_fields=["payment_method", "payment_status", "updated_at"])

    return render(request, "kiosk/pay.html", {"order": order, "error": error})


@login_required
def order_status(request, pk):
    order = get_object_or_404(Order, pk=pk)
    if order.user_id != request.user.id and not request.user.is_staff:
        return redirect("kiosk:menu")
    return render(request, "kiosk/order_status.html", {"order": order})


@login_required
def order_status_api(request, pk):
    order = get_object_or_404(Order, pk=pk)
    if order.user_id != request.user.id and not request.user.is_staff:
        return JsonResponse({"error": "forbidden"}, status=403)
    ahead = Order.objects.filter(
        status__in=["received", "preparing"], created_at__lt=order.created_at
    ).count()
    return JsonResponse(
        {"status": order.status, "label": order.get_status_display(), "ahead": ahead}
    )


@login_required
def my_orders(request):
    if is_kitchen_only(request.user):
        return redirect("kiosk:kitchen")
    orders = request.user.orders.prefetch_related("items")[:30]
    return render(request, "kiosk/my_orders.html", {"orders": orders})


# ------------------------------------------------------------------- kitchen
@staff_required
def kitchen(request):
    return render(request, "kiosk/kitchen.html")


def _order_json(o):
    """Orders only: no categories, no menu data."""
    return {
        "id": o.id,
        "label": o.label,
        "name": o.customer_name,
        "status": o.status,
        "paid": o.payment_status == "paid",
        "method": o.get_payment_method_display() if o.payment_method else "",
        "total": float(o.total),
        "notes": o.notes,
        "age": int((timezone.now() - o.created_at).total_seconds() // 60),
        "items": [
            {"qty": i.quantity, "name": i.name, "opts": i.options_label, "note": i.note}
            for i in o.items.all()
        ],
    }


@staff_required
def kitchen_api(request):
    active = (
        Order.objects.filter(status__in=["received", "preparing", "ready"])
        .prefetch_related("items")
        .order_by("created_at")
    )
    return JsonResponse({"orders": [_order_json(o) for o in active]})


@staff_required
@require_POST
def kitchen_update(request, pk):
    order = get_object_or_404(Order, pk=pk)
    new_status = request.POST.get("status")
    allowed = {"received", "preparing", "ready", "completed", "cancelled"}
    if new_status not in allowed:
        return JsonResponse({"error": "bad status"}, status=400)
    order.status = new_status
    if new_status == "completed" and order.payment_method == "cash":
        order.payment_status = "paid"  # cash collected at the counter
    order.save()
    return JsonResponse({"ok": True})


def board_api(request):
    """Public 'now serving' board data (queue numbers only, no personal info)."""
    preparing = Order.objects.filter(status__in=["received", "preparing"]).order_by("created_at")
    ready = Order.objects.filter(status="ready").order_by("updated_at")
    return JsonResponse(
        {
            "preparing": [o.label for o in preparing],
            "ready": [o.label for o in ready],
        }
    )


def board(request):
    return render(request, "kiosk/board.html")
