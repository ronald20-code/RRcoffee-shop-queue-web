import os
import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone


class Category(models.Model):
    """Menu groups shown on the customer kiosk (Coffee-Based, Pastries, Fries, ...)."""

    name = models.CharField(max_length=60)
    slug = models.SlugField(unique=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_drink = models.BooleanField(
        default=True,
        help_text="Drinks offer size and hot/iced options. Snacks do not.",
    )

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


def product_image_path(instance, filename):
    """Random file name: no collisions, and the original name is never trusted."""
    ext = os.path.splitext(filename)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png"):
        ext = ".jpg"
    return f"products/{uuid.uuid4().hex}{ext}"


class Product(models.Model):
    SERVING = [("hot", "Hot"), ("iced", "Iced")]

    category = models.ForeignKey(
        Category, related_name="products", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=200, blank=True)
    price = models.DecimalField(max_digits=7, decimal_places=2)
    is_available = models.BooleanField(default=True)
    serving = models.CharField(
        max_length=5,
        choices=SERVING,
        default="hot",
        help_text="Only used for drinks.",
    )
    image = models.ImageField(upload_to=product_image_path, blank=True)

    class Meta:
        ordering = ["category__sort_order", "name"]

    def __str__(self):
        return self.name

    @property
    def image_url(self):
        return self.image.url if self.image else ""

    def save(self, *args, **kwargs):
        old_name = None
        if self.pk:
            old_name = (
                Product.objects.filter(pk=self.pk).values_list("image", flat=True).first()
            )
        super().save(*args, **kwargs)
        # A replaced or removed photo must not stay behind on disk.
        if old_name and old_name != (self.image.name or ""):
            self.image.storage.delete(old_name)


@receiver(post_delete, sender=Product)
def delete_product_image(sender, instance, **kwargs):
    if instance.image:
        instance.image.storage.delete(instance.image.name)


class Order(models.Model):
    STATUS_CHOICES = [
        ("pending_payment", "Pending payment"),
        ("received", "Received"),
        ("preparing", "Preparing"),
        ("ready", "Ready for pickup"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]
    PAYMENT_METHODS = [
        ("gcash", "GCash"),
        ("maya", "Maya"),
        ("card", "Credit / Debit card"),
        ("cash", "Pay at counter"),
    ]
    PAYMENT_STATUS = [
        ("unpaid", "Unpaid"),
        ("paid", "Paid"),
        ("failed", "Failed"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="orders",
    )
    queue_number = models.PositiveIntegerField(editable=False)
    customer_name = models.CharField(max_length=80, blank=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="pending_payment"
    )
    payment_method = models.CharField(
        max_length=10, choices=PAYMENT_METHODS, blank=True
    )
    payment_status = models.CharField(
        max_length=10, choices=PAYMENT_STATUS, default="unpaid"
    )
    payment_reference = models.CharField(max_length=40, blank=True)
    total = models.DecimalField(max_digits=9, decimal_places=2, default=Decimal("0"))
    notes = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"#{self.queue_number:03d} ({self.get_status_display()})"

    @property
    def label(self):
        return f"{self.queue_number:03d}"

    def save(self, *args, **kwargs):
        if not self.queue_number:
            self.queue_number = self.next_queue_number()
        super().save(*args, **kwargs)

    @classmethod
    def next_queue_number(cls):
        """Queue numbers restart at 1 every day (1..999)."""
        today = timezone.localdate()
        last = (
            cls.objects.filter(created_at__date=today)
            .order_by("-queue_number")
            .first()
        )
        n = (last.queue_number + 1) if last else 1
        return n if n <= 999 else 1

    def recalc_total(self):
        self.total = sum((i.line_total for i in self.items.all()), Decimal("0"))
        self.save(update_fields=["total", "updated_at"])


class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name="items", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    name = models.CharField(max_length=80)  # snapshot of product name
    unit_price = models.DecimalField(max_digits=7, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)
    # Blank for snacks, which have no size or temperature.
    size = models.CharField(max_length=10, blank=True, default="")
    temperature = models.CharField(max_length=10, blank=True, default="")
    note = models.CharField(max_length=120, blank=True)

    def __str__(self):
        return f"{self.quantity}x {self.name}"

    @property
    def line_total(self):
        return self.unit_price * self.quantity

    @property
    def options_label(self):
        """e.g. 'Large · Iced', or '' for a snack."""
        return " · ".join(x for x in (self.size, self.temperature) if x)
