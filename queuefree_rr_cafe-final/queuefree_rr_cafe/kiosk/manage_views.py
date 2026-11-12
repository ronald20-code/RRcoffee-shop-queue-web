"""Admin-only menu management: categories, products, prices and photos."""

from decimal import Decimal, InvalidOperation
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Max, ProtectedError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from .forms import CategoryForm, ProductForm
from .models import Category, Product


def manager_required(view):
    """Logged-in superusers (the admin account) only."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return login_required(wrapper)


@manager_required
def menu_manager(request):
    categories = Category.objects.prefetch_related("products")
    return render(
        request,
        "kiosk/manage_menu.html",
        {"categories": categories, "category_form": CategoryForm()},
    )


# ------------------------------------------------------------------ products
def _product_form(request, product, initial=None):
    form = ProductForm(
        request.POST or None, request.FILES or None, instance=product, initial=initial
    )
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        messages.success(request, f"“{saved.name}” saved.")
        return redirect("kiosk:manage_menu")
    return render(
        request,
        "kiosk/manage_product_form.html",
        {
            "form": form,
            "product": product,
            "max_mb": settings.MAX_PRODUCT_IMAGE_MB,
            # which categories are drinks (size / hot-iced options apply only to those)
            "drink_flags": {c.id: c.is_drink for c in Category.objects.all()},
        },
    )


@manager_required
def product_create(request):
    if not Category.objects.exists():
        messages.error(request, "Add a category first.")
        return redirect("kiosk:manage_menu")
    initial = {}
    cat_id = request.GET.get("category", "")
    if cat_id.isdigit() and Category.objects.filter(pk=cat_id).exists():
        initial["category"] = int(cat_id)  # "+ Add product" inside a category preselects it
    return _product_form(request, None, initial)


@manager_required
def product_edit(request, pk):
    return _product_form(request, get_object_or_404(Product, pk=pk))


@manager_required
@require_POST
def product_delete(request, pk):
    product = get_object_or_404(Product, pk=pk)
    name = product.name
    try:
        product.delete()  # also removes the uploaded photo file
        messages.success(request, f"“{name}” deleted.")
    except ProtectedError:
        # Products on past orders can't be removed without breaking order history.
        product.is_available = False
        product.save(update_fields=["is_available"])
        messages.warning(
            request,
            f"“{name}” is on past orders, so it was hidden from the kiosk instead of deleted.",
        )
    return redirect("kiosk:manage_menu")


@manager_required
@require_POST
def product_quick(request, pk):
    """Inline edits from the list: price and/or availability."""
    product = get_object_or_404(Product, pk=pk)

    if "price" in request.POST:
        try:
            price = Decimal(request.POST["price"].strip())
        except (InvalidOperation, ValueError):
            return JsonResponse({"error": "Enter a valid price."}, status=400)
        if not price.is_finite() or price <= 0 or price >= Decimal("100000"):
            return JsonResponse({"error": "Price must be between ₱1 and ₱99,999."}, status=400)
        if price != price.to_integral_value():
            return JsonResponse({"error": "Use whole pesos."}, status=400)
        product.price = price.quantize(Decimal("0.01"))

    if "is_available" in request.POST:
        product.is_available = request.POST["is_available"] == "1"

    product.save()
    return JsonResponse(
        {"ok": True, "price": float(product.price), "is_available": product.is_available}
    )


@manager_required
@require_POST
def product_remove_photo(request, pk):
    product = get_object_or_404(Product, pk=pk)
    if product.image:
        product.image = ""
        product.save()  # deletes the old file too
        messages.success(request, f"Photo removed from “{product.name}”.")
    return redirect("kiosk:manage_menu")


# ---------------------------------------------------------------- categories
def _unique_slug(name):
    base = slugify(name) or "category"
    slug, n = base, 2
    while Category.objects.filter(slug=slug).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


@manager_required
@require_POST
def category_create(request):
    form = CategoryForm(request.POST)
    if form.is_valid():
        cat = form.save(commit=False)
        cat.slug = _unique_slug(cat.name)
        cat.sort_order = (Category.objects.aggregate(m=Max("sort_order"))["m"] or 0) + 1
        cat.save()
        messages.success(request, f"Category “{cat.name}” added.")
    else:
        messages.error(request, "; ".join(e for errs in form.errors.values() for e in errs))
    return redirect("kiosk:manage_menu")


@manager_required
def category_edit(request, pk):
    category = get_object_or_404(Category, pk=pk)
    form = CategoryForm(request.POST or None, instance=category)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Category “{category.name}” updated.")
        return redirect("kiosk:manage_menu")
    return render(request, "kiosk/manage_category_form.html", {"form": form, "category": category})


@manager_required
@require_POST
def category_delete(request, pk):
    category = get_object_or_404(Category, pk=pk)
    if category.products.exists():
        messages.error(
            request,
            f"“{category.name}” still has products. Move or delete them first.",
        )
    else:
        category.delete()
        messages.success(request, f"Category “{category.name}” deleted.")
    return redirect("kiosk:manage_menu")


@manager_required
@require_POST
def category_move(request, pk, direction):
    """Move a category up or down in the customer menu order."""
    cats = list(Category.objects.order_by("sort_order", "name"))
    idx = next((i for i, c in enumerate(cats) if c.pk == pk), None)
    if idx is None:
        return redirect("kiosk:manage_menu")
    swap = idx - 1 if direction == "up" else idx + 1
    if 0 <= swap < len(cats):
        cats[idx], cats[swap] = cats[swap], cats[idx]
        for order, c in enumerate(cats, start=1):  # renumber so ties can't occur
            if c.sort_order != order:
                c.sort_order = order
                c.save(update_fields=["sort_order"])
    return redirect("kiosk:manage_menu")
