import io

from django import forms
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import UploadedFile
from PIL import Image, ImageOps

from .models import Category, Product

ALLOWED_EXT = (".jpg", ".jpeg", ".png")
MAX_SIDE = 1200  # photos are scaled down to this many pixels on the longest side


class ProductForm(forms.ModelForm):
    """Add / edit a product, including its photo."""

    remove_image = forms.BooleanField(required=False, label="Remove current photo")

    class Meta:
        model = Product
        fields = [
            "name", "category", "description", "price", "serving",
            "image", "is_available",
        ]
        labels = {
            "name": "Product name",
            "description": "Short description",
            "price": "Price (₱, whole pesos)",
            "serving": "Served",
            "image": "Product photo",
            "is_available": "Available on the kiosk",
        }
        widgets = {
            "price": forms.NumberInput(attrs={"step": "1", "min": "1", "inputmode": "numeric"}),
            "description": forms.TextInput(attrs={"maxlength": 200}),
            "name": forms.TextInput(attrs={"maxlength": 80}),
            "image": forms.FileInput(
                attrs={"accept": ".jpg,.jpeg,.png,image/jpeg,image/png"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.initial["price"] = int(self.instance.price)  # show 150, not 150.00
        self.fields["category"].empty_label = None
        self.fields["serving"].required = False
        self.fields["image"].required = False

    # ---- fields
    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        dupes = Product.objects.filter(name__iexact=name)
        if self.instance.pk:
            dupes = dupes.exclude(pk=self.instance.pk)
        if dupes.exists():
            raise forms.ValidationError("A product with this name already exists.")
        return name

    def clean_price(self):
        price = self.cleaned_data["price"]
        if price <= 0:
            raise forms.ValidationError("Price must be more than ₱0.")
        if price != price.to_integral_value():
            raise forms.ValidationError("Use whole pesos (no centavos).")
        return price

    def clean_serving(self):
        return self.cleaned_data.get("serving") or "hot"

    def clean_image(self):
        f = self.cleaned_data.get("image")
        # No new upload: Django hands back the current image (or nothing).
        if not isinstance(f, UploadedFile):
            return f

        name = (f.name or "").lower()
        if not name.endswith(ALLOWED_EXT):
            raise forms.ValidationError("Please upload a JPG, JPEG or PNG image.")
        max_mb = getattr(settings, "MAX_PRODUCT_IMAGE_MB", 5)
        if f.size > max_mb * 1024 * 1024:
            raise forms.ValidationError(f"The photo is too large. Maximum size is {max_mb} MB.")

        try:
            f.seek(0)
            img = Image.open(f)
            fmt = img.format
            if fmt not in ("JPEG", "PNG"):
                raise forms.ValidationError("Please upload a JPG, JPEG or PNG image.")
            img.load()
        except forms.ValidationError:
            raise
        except Exception:
            raise forms.ValidationError("That file is not a valid image.")

        # Normalise: respect phone-camera rotation, drop metadata (GPS etc.), shrink huge photos.
        img = ImageOps.exif_transpose(img)
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        out = io.BytesIO()
        if fmt == "PNG":
            img.save(out, format="PNG", optimize=True)
            ext = ".png"
        else:
            img.convert("RGB").save(out, format="JPEG", quality=88, optimize=True)
            ext = ".jpg"
        return ContentFile(out.getvalue(), name=f"photo{ext}")

    # ---- save
    def save(self, commit=True):
        product = super().save(commit=False)
        uploaded = isinstance(self.cleaned_data.get("image"), ContentFile)
        if self.cleaned_data.get("remove_image") and not uploaded:
            product.image = ""
        if commit:
            product.save()
        return product


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name", "is_drink"]
        labels = {
            "name": "Category name",
            "is_drink": "This category is drinks (customers choose size and hot/iced)",
        }

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        dupes = Category.objects.filter(name__iexact=name)
        if self.instance.pk:
            dupes = dupes.exclude(pk=self.instance.pk)
        if dupes.exists():
            raise forms.ValidationError("A category with this name already exists.")
        return name
