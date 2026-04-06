"""
Reassign items from "Imported Dataset" (or another source category) into
sensible product categories using name/description keywords, then optionally
balance totals so dashboard charts look less lopsided.

Safe to run multiple times (idempotent for already-dispersed items if source is empty).

Usage:
  python manage.py disperse_imported_categories
  python manage.py disperse_imported_categories --dry-run
  python manage.py disperse_imported_categories --no-balance
  python manage.py disperse_imported_categories --source-category "Imported Dataset"
"""

import hashlib
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from inventory.models import Category, Item


# (display_name, lowercase keyword substrings) — first match wins; put specific before broad.
CATEGORY_KEYWORD_RULES = [
    ("Seasonal & gifts", (
        "christmas", "xmas", "snowman", "snow ", "santa", "reindeer", "bauble", "cracker",
        "easter", "halloween", "pumpkin", "heart", "love ", "wedding", "bridal", "valentine",
        "tree skirt", "stocking", "advent", "nativity", "gingerbread",
    )),
    ("Kitchen & dining", (
        "cake", "bread", "lunch", "kitchen", "dining", "napkin", "plate", "mug", "cup ", "cups",
        "spoon", "knife", "fork", "coaster", "cookie", "jam jar", "teapot", "saucer", "bowl",
        "bottle", "salt", "pepper", "egg", "toast", "cafetiere", "french press", "kettle",
        "lunchbox", "lunch box", "food cover", "cake slice", "cakestand", "cake stand",
    )),
    ("Candles & lighting", (
        "candle", "lantern", "tea light", "tealight", "night light", "nightlight", "lamp shade",
        "lampshade", "chandelier", "string light", "fairy light",
    )),
    ("Home décor", (
        "frame", "photo frame", "picture frame", "wall clock", "clock ", "mirror", "vase",
        "cushion", "throw", "doormat", "sign ", "metal sign", "wooden sign", "plaque",
        "hook", "hanger", "shelf", "bunting", "garland", "wreath", "ornament",
    )),
    ("Party & entertaining", (
        "party", "balloon", "wine glass", "champagne", "prosecco", "platter", "serving",
        "cocktail", "picnic", "bbq", "barbecue",
    )),
    ("Crafts & textiles", (
        "ribbon", "lace", "felt", "wool", "yarn", "fabric", "patchwork", "sewing", "button",
        "craft", "feltcraft", "knitting", "crochet",
    )),
    ("Bags & storage", (
        " bag", "bags", "tote", "hamper", "basket", "storage tin", "storage box", "jumbo bag",
        "laundry", "trinket box", "gift box", "wrap", "wrapping", "tissue paper",
    )),
    ("Bathroom & wellness", (
        "bath", "soap", "towel", "sponge", "shower", "toilet", "loofah", "cotton wool",
    )),
    ("Toys & novelty", (
        "toy", "doll", "puzzle", "game ", "novelty", "spinning top", "yo-yo", "yoyo",
    )),
    ("Stationery & office", (
        "pen ", "pencil", "notebook", "notepad", "journal", "calendar", "diary", "envelope",
        "stamp", "paper clip", "stapler", "ruler", "eraser", "marker",
    )),
    ("Garden & outdoor", (
        "garden", "watering", "plant pot", "flower pot", "compost", "bird house", "birdhouse",
    )),
    ("Electronics & accessories", (
        "alarm clock", "radio", "usb", "cable", "charger", "battery", "headphone", "speaker",
        "adapter", "extension lead", "led light", "led ", "torch", "flashlight",
    )),
    ("Jewellery & accessories", (
        "necklace", "bracelet", "earring", "ring ", "jewellery", "jewelry", "brooch", "charm",
        "watch ", "hair clip", "hairband", "scrunchie",
    )),
    ("Table linens", (
        "tablecloth", "table cloth", "runner", "placemat", "place mat", "doily", "napkin ring",
    )),
]

# When no rule matches, spread across these using a stable hash of SKU.
FALLBACK_ROTATION = (
    "Homeware general",
    "Giftware",
    "Kitchen & dining",
    "Seasonal & gifts",
    "Home décor",
)


def _norm(text):
    return (text or "").lower()


def classify_item(name: str, description: str, sku: str) -> str:
    blob = _norm(f"{name} {description}")
    for cat_name, keywords in CATEGORY_KEYWORD_RULES:
        for kw in keywords:
            if kw in blob:
                return cat_name
    digest = hashlib.md5((sku or "").encode("utf-8")).hexdigest()
    h = int(digest[:8], 16) % len(FALLBACK_ROTATION)
    return FALLBACK_ROTATION[h]


class Command(BaseCommand):
    help = (
        "Move items out of 'Imported Dataset' into keyword-based categories; "
        "optionally rebalance stock totals across categories for nicer charts."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-category",
            type=str,
            default="Imported Dataset",
            help='Category name to read items from (default: "Imported Dataset")',
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print plan only; do not save changes",
        )
        parser.add_argument(
            "--no-balance",
            action="store_true",
            help="Skip quantity-balancing pass (keyword assignment only)",
        )
        parser.add_argument(
            "--max-share",
            type=float,
            default=0.34,
            help="Balance until no category holds more than this fraction of moved stock (default 0.34)",
        )
        parser.add_argument(
            "--max-moves",
            type=int,
            default=800,
            help="Safety cap on balance iterations (default 800)",
        )

    def handle(self, *args, **opts):
        source_name = opts["source_category"]
        dry = opts["dry_run"]
        do_balance = not opts["no_balance"]
        max_share = float(opts["max_share"])
        max_moves = int(opts["max_moves"])

        try:
            source_cat = Category.objects.get(name=source_name)
        except Category.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'Category "{source_name}" does not exist.'))
            return

        items = list(
            Item.objects.filter(category=source_cat).select_related("category")
        )
        if not items:
            self.stdout.write(self.style.WARNING(f"No items in “{source_name}”. Nothing to do."))
            return

        # --- Phase 1: keyword (and fallback) assignment ---
        target_names = {r[0] for r in CATEGORY_KEYWORD_RULES} | set(FALLBACK_ROTATION)
        name_to_category = {}
        for nm in sorted(target_names):
            name_to_category[nm], _ = Category.objects.get_or_create(name=nm)

        buckets = defaultdict(list)
        for it in items:
            label = classify_item(it.name, it.description or "", it.sku)
            buckets[label].append(it)

        self.stdout.write(self.style.NOTICE("Phase 1 — keyword / fallback assignment:"))
        for label in sorted(buckets.keys(), key=lambda k: -len(buckets[k])):
            self.stdout.write(f"  {label}: {len(buckets[label])} items")

        # --- Phase 2: balance by on-hand quantity across buckets ---
        if do_balance and len(buckets) > 1:
            self.stdout.write(self.style.NOTICE("Phase 2 — balance by quantity (in memory):"))
            # work with lists we can mutate
            cat_items = {c: list(v) for c, v in buckets.items()}
            moves = 0

            def totals():
                return {c: sum(x.quantity for x in lst) for c, lst in cat_items.items()}

            while moves < max_moves:
                t = totals()
                total_qty = sum(t.values())
                if total_qty <= 0:
                    break
                shares = {c: t[c] / total_qty for c in t}
                worst = max(shares, key=shares.get)
                if shares[worst] <= max_share:
                    break
                best = min(shares, key=shares.get)
                if worst == best:
                    break
                pool = cat_items[worst]
                if len(pool) <= 1:
                    break
                # Move a whole item: prefer lower-qty lines from the dominant bucket
                victim = min(pool, key=lambda x: (x.quantity, x.pk))
                pool.remove(victim)
                cat_items[best].append(victim)
                moves += 1

            self.stdout.write(f"  Balance moves: {moves}")
            buckets = cat_items

        # --- Apply ---
        to_update = []
        for cat_name, lst in buckets.items():
            cat = name_to_category.get(cat_name)
            if cat is None:
                cat, _ = Category.objects.get_or_create(name=cat_name)
                name_to_category[cat_name] = cat
            for it in lst:
                if it.category_id != cat.id:
                    it.category = cat
                    to_update.append(it)

        if dry:
            self.stdout.write(self.style.WARNING(f"DRY RUN — would update {len(to_update)} items."))
            return

        with transaction.atomic():
            if to_update:
                Item.objects.bulk_update(to_update, ["category"], batch_size=500)

        self.stdout.write(
            self.style.SUCCESS(
                f"Updated {len(to_update)} items out of “{source_name}”. "
                f"Categories touched: {len(buckets)}."
            )
        )
