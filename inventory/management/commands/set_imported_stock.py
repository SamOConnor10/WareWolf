import random
from django.core.management.base import BaseCommand
from inventory.models import Item, Category

class Command(BaseCommand):
    help = "Set realistic on-hand stock levels for imported dataset items."

    def add_arguments(self, parser):
        parser.add_argument("--category", type=str, default="Imported Dataset")
        parser.add_argument("--out", type=float, default=0.20, help="Fraction out of stock (default 0.20)")
        parser.add_argument("--low", type=float, default=0.30, help="Fraction low stock (default 0.30)")

    def handle(self, *args, **opts):
        cat_name = opts["category"]
        out_frac = float(opts["out"])
        low_frac = float(opts["low"])

        try:
            cat = Category.objects.get(name=cat_name)
        except Category.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Category '{cat_name}' not found"))
            return

        items = list(Item.objects.filter(category=cat))
        if not items:
            self.stdout.write(self.style.ERROR("No items found to update"))
            return

        random.shuffle(items)
        n = len(items)
        n_out = int(n * out_frac)
        n_low = int(n * low_frac)

        for i, item in enumerate(items):
            rl = max(item.reorder_level, 1)

            if i < n_out:
                item.quantity = 0
            elif i < n_out + n_low:
                # low stock: between 1 and reorder_level
                item.quantity = random.randint(1, rl)
            else:
                # in stock: between reorder_level+1 and 3*reorder_level
                item.quantity = random.randint(rl + 1, rl * 3)

            item.save(update_fields=["quantity"])

        self.stdout.write(self.style.SUCCESS(
            f"Updated {n} items: out={n_out}, low={n_low}, in_stock={n - n_out - n_low}"
        ))