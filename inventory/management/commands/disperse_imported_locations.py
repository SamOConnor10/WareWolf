"""
Reassign items from "Imported Location" (or another source) into warehouse-style
locations using name/description keywords, then optionally balance quantities so
location charts look less lopsided.

Safe to run multiple times (no-op once the source location has no items).

Usage:
  python manage.py disperse_imported_locations
  python manage.py disperse_imported_locations --dry-run
  python manage.py disperse_imported_locations --no-balance
  python manage.py disperse_imported_locations --source-location "Imported Location"
"""

import hashlib
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from inventory.models import Item, Location


# (location_name, lowercase keyword substrings) — first match wins; specific before broad.
LOCATION_KEYWORD_RULES = [
    ("A-Aisle", (
        "computer", "laptop", "monitor", "keyboard", "mouse", "router", "switch",
        "access point", "cable", "hdmi", "usb", "charger", "adapter", "server",
        "network", "ethernet", "docking", "webcam", "headset", "speaker",
    )),
    ("B-Aisle", (
        "printer", "toner", "ink", "scanner", "projector", "ups", "battery",
        "power strip", "extension", "surge",
    )),
    ("Main Warehouse", (
        "desk", "chair", "furniture", "cabinet", "shelf", "rack", "pallet", "bulk",
        "crate", "office furniture", "filing",
    )),
    ("Seasonal bay", (
        "christmas", "xmas", "easter", "halloween", "seasonal", "bauble", "wreath",
        "stocking", "cracker", "party", "balloon",
    )),
    ("Homeware picks", (
        "kitchen", "dining", "mug", "plate", "bowl", "cushion", "frame", "vase",
        "candle", "lamp", "mirror", "clock", "towel", "bath", "garden",
    )),
    ("Gift & novelties", (
        "gift", "hamper", "toy", "game", "novelty", "jewellery", "jewelry", "watch",
    )),
    ("Stationery corner", (
        "pen ", "pencil", "notebook", "paper", "envelope", "stapler", "folder",
    )),
]

# When no rule matches, rotate across these (created if missing).
FALLBACK_ROTATION = (
    "Main Warehouse",
    "A-Aisle",
    "B-Aisle",
    "Pick zone C",
    "Bulk storage",
)


def _norm(text):
    return (text or "").lower()


def classify_location(name: str, description: str, sku: str) -> str:
    blob = _norm(f"{name} {description}")
    for loc_name, keywords in LOCATION_KEYWORD_RULES:
        for kw in keywords:
            if kw in blob:
                return loc_name
    digest = hashlib.md5((sku or "").encode("utf-8")).hexdigest()
    h = int(digest[:8], 16) % len(FALLBACK_ROTATION)
    return FALLBACK_ROTATION[h]


def first_or_create_location(name: str) -> Location:
    """Use the oldest row if duplicate names exist (get_or_create is unsafe then)."""
    found = Location.objects.filter(name=name).order_by("pk").first()
    if found:
        return found
    return Location.objects.create(name=name, code="", description="")


class Command(BaseCommand):
    help = (
        "Move items out of 'Imported Location' into keyword-based locations; "
        "optionally rebalance stock totals across locations for nicer charts."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-location",
            type=str,
            default="Imported Location",
            help='Location name to read items from (default: "Imported Location")',
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
            help="Balance until no location holds more than this fraction of moved stock (default 0.34)",
        )
        parser.add_argument(
            "--max-moves",
            type=int,
            default=800,
            help="Safety cap on balance iterations (default 800)",
        )

    def handle(self, *args, **opts):
        source_name = opts["source_location"]
        dry = opts["dry_run"]
        do_balance = not opts["no_balance"]
        max_share = float(opts["max_share"])
        max_moves = int(opts["max_moves"])

        source_candidates = list(Location.objects.filter(name=source_name).order_by("pk"))
        if not source_candidates:
            self.stdout.write(self.style.ERROR(f'Location "{source_name}" does not exist.'))
            return
        if len(source_candidates) > 1:
            self.stdout.write(
                self.style.WARNING(
                    f'Multiple rows named "{source_name}" ({len(source_candidates)}); '
                    "moving items from all of them."
                )
            )

        items = list(
            Item.objects.filter(location__name=source_name).select_related("location")
        )
        if not items:
            self.stdout.write(self.style.WARNING(f'No items in “{source_name}”. Nothing to do.'))
            return

        target_names = {r[0] for r in LOCATION_KEYWORD_RULES} | set(FALLBACK_ROTATION)
        name_to_location = {}
        for nm in sorted(target_names):
            name_to_location[nm] = first_or_create_location(nm)

        buckets = defaultdict(list)
        for it in items:
            label = classify_location(it.name, it.description or "", it.sku)
            buckets[label].append(it)

        self.stdout.write(self.style.NOTICE("Phase 1 — keyword / fallback assignment:"))
        for label in sorted(buckets.keys(), key=lambda k: -len(buckets[k])):
            self.stdout.write(f"  {label}: {len(buckets[label])} items")

        if do_balance and len(buckets) > 1:
            self.stdout.write(self.style.NOTICE("Phase 2 — balance by quantity (in memory):"))
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
                victim = min(pool, key=lambda x: (x.quantity, x.pk))
                pool.remove(victim)
                cat_items[best].append(victim)
                moves += 1

            self.stdout.write(f"  Balance moves: {moves}")
            buckets = cat_items

        to_update = []
        for loc_name, lst in buckets.items():
            loc = name_to_location.get(loc_name)
            if loc is None:
                loc = first_or_create_location(loc_name)
                name_to_location[loc_name] = loc
            for it in lst:
                if it.location_id != loc.id:
                    it.location = loc
                    to_update.append(it)

        if dry:
            self.stdout.write(self.style.WARNING(f"DRY RUN — would update {len(to_update)} items."))
            return

        with transaction.atomic():
            if to_update:
                Item.objects.bulk_update(to_update, ["location"], batch_size=500)

        self.stdout.write(
            self.style.SUCCESS(
                f"Updated {len(to_update)} items out of “{source_name}”. "
                f"Locations touched: {len(buckets)}."
            )
        )
