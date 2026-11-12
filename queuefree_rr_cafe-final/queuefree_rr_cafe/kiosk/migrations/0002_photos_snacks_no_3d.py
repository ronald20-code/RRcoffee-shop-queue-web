"""
Adds product photos and snack support, and removes the old 3D-model fields.

Existing data is preserved: the old hot/iced choice (stored in ``cup_style``)
is copied into the new ``serving`` field before the 3D columns are dropped, and
existing orders keep their size / temperature text.
"""

from django.db import migrations, models

import kiosk.models


def copy_serving(apps, schema_editor):
    Product = apps.get_model("kiosk", "Product")
    Product.objects.filter(cup_style="glass").update(serving="iced")
    Product.objects.exclude(cup_style="glass").update(serving="hot")


class Migration(migrations.Migration):

    dependencies = [
        ("kiosk", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="category",
            name="is_drink",
            field=models.BooleanField(
                default=True,
                help_text="Drinks offer size and hot/iced options. Snacks do not.",
            ),
        ),
        migrations.AddField(
            model_name="product",
            name="serving",
            field=models.CharField(
                choices=[("hot", "Hot"), ("iced", "Iced")],
                default="hot",
                help_text="Only used for drinks.",
                max_length=5,
            ),
        ),
        migrations.AddField(
            model_name="product",
            name="image",
            field=models.ImageField(
                blank=True, upload_to=kiosk.models.product_image_path
            ),
        ),
        migrations.RunPython(copy_serving, migrations.RunPython.noop),
        migrations.RemoveField(model_name="product", name="cup_style"),
        migrations.RemoveField(model_name="product", name="liquid_color"),
        migrations.RemoveField(model_name="product", name="layer_color"),
        migrations.RemoveField(model_name="product", name="topping_color"),
        migrations.RemoveField(model_name="product", name="has_ice"),
        migrations.RemoveField(model_name="product", name="has_straw"),
        migrations.AlterField(
            model_name="orderitem",
            name="size",
            field=models.CharField(blank=True, default="", max_length=10),
        ),
        migrations.AlterField(
            model_name="orderitem",
            name="temperature",
            field=models.CharField(blank=True, default="", max_length=10),
        ),
    ]
