"""
Download placeholder images for entities missing photos (demo / FYP use).

Uses LoremFlickr (https://loremflickr.com) with keyword tags loosely matched to the
entity so pictures look vaguely relevant. Requires outbound HTTPS. Be polite: use
--delay between requests.

Does not overwrite existing images unless --force.
"""
from __future__ import annotations

import time
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils.text import slugify
from PIL import Image

from inventory.models import Client, Item, Location, Supplier


def _no_image_q():
    return Q(image__isnull=True) | Q(image="")


def _fetch_image_bytes(url: str, timeout: int = 45) -> bytes:
    req = Request(
        url,
        headers={
            "User-Agent": "WareWolfImageSeed/1.0 (university inventory demo; contact: local)",
            "Accept": "image/*",
        },
    )
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _normalize_jpeg(data: bytes) -> bytes:
    bio = BytesIO(data)
    im = Image.open(bio)
    im.load()
    if im.mode in ("RGBA", "P"):
        im = im.convert("RGB")
    elif im.mode != "RGB":
        im = im.convert("RGB")
    out = BytesIO()
    im.save(out, format="JPEG", quality=88, optimize=True)
    return out.getvalue()


def _item_tags(item: Item) -> str:
    parts = [item.name or ""]
    if item.category_id:
        parts.append(item.category.full_path)
    blob = " ".join(parts).lower()
    if any(k in blob for k in ("chair", "desk", "table", "furniture", "shelf")):
        return "furniture,office"
    if any(k in blob for k in ("cable", "router", "switch", "access point", "ap-", "wifi", "keyboard", "mouse")):
        return "computer,technology"
    if any(k in blob for k in ("monitor", "display", "screen", "laptop")):
        return "laptop,technology"
    if any(k in blob for k in ("gift", "seasonal", "ribbon", "toy")):
        return "gift,retail"
    if any(k in blob for k in ("kitchen", "knife", "pot", "pan", "plate")):
        return "kitchen,home"
    if any(k in blob for k in ("tool", "drill", "hammer", "tape")):
        return "tools,workshop"
    return "product,retail"


class Command(BaseCommand):
    help = "Bulk-download demo images for items, locations, suppliers, and clients without images."

    def add_arguments(self, parser):
        parser.add_argument(
            "--only",
            choices=("items", "locations", "suppliers", "clients", "all"),
            default="all",
            help="Which model type to fill",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Replace images even when one is already set",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Max entities per type (0 = no limit)",
        )
        parser.add_argument(
            "--delay",
            type=float,
            default=1.25,
            help="Seconds to wait between HTTP requests (default 1.25)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print URLs only; do not download or save",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Print one line per row (default: compact progress every 10 rows)",
        )

    def handle(self, *args, **options):
        only = options["only"]
        force = options["force"]
        limit = options["limit"]
        delay = max(0.0, options["delay"])
        dry = options["dry_run"]
        verbose = options["verbose"] or getattr(self, "verbosity", 1) >= 2

        stats = {"ok": 0, "skip": 0, "fail": 0}

        def cap_qs(qs):
            if limit and limit > 0:
                return list(qs[:limit])
            return list(qs)

        def process_batch(singular: str, plural: str, rows: list, get_url) -> None:
            """get_url(obj) -> url string"""
            n = len(rows)
            if n == 0:
                self.stdout.write(f"{plural}: nothing to do (all have images or no rows).")
                return
            tail = ""
            if delay and not dry:
                tail += f" (~{n * delay:.0f}s with delay={delay})"
            if not verbose:
                tail += " (use --verbose for each pk)"
            self.stdout.write(f"{plural}: {n} to {'queue' if dry else 'download'}{tail}")
            for i, obj in enumerate(rows, 1):
                url = get_url(obj)
                img = getattr(obj, "image")
                if not force and img and getattr(img, "name", ""):
                    stats["skip"] += 1
                    continue
                if dry:
                    stats["ok"] += 1
                    if verbose:
                        self.stdout.write(f"  [dry-run] {singular} pk={obj.pk} -> {url}")
                else:
                    try:
                        raw = _fetch_image_bytes(url)
                        jpeg = _normalize_jpeg(raw)
                        name = f"{slugify(singular)}_{obj.pk}.jpg"
                        obj.image.save(name, ContentFile(jpeg), save=True)
                        stats["ok"] += 1
                        if verbose:
                            self.stdout.write(self.style.SUCCESS(f"  {singular} pk={obj.pk} saved"))
                    except (HTTPError, URLError, OSError, ValueError) as e:
                        self.stdout.write(self.style.ERROR(f"  {singular} pk={obj.pk} FAILED: {e}"))
                        stats["fail"] += 1
                    if delay:
                        time.sleep(delay)
                if not verbose and not dry and (i % 10 == 0 or i == n):
                    self.stdout.write(f"  ... {i}/{n} {plural.lower()}")
                if not verbose and dry and (i % 10 == 0 or i == n):
                    self.stdout.write(f"  ... dry-run {i}/{n} {plural.lower()}")

        if only in ("items", "all"):
            qs = Item.objects.select_related("category").order_by("pk")
            if not force:
                qs = qs.filter(_no_image_q())
            rows = cap_qs(qs)

            def item_url(item):
                tags = _item_tags(item)
                lock = (item.pk % 9000) + 1
                return f"https://loremflickr.com/400/400/{tags}?lock={lock}"

            process_batch("item", "Items", rows, item_url)

        if only in ("locations", "all"):
            qs = Location.objects.filter(is_active=True).order_by("pk")
            if not force:
                qs = qs.filter(_no_image_q())
            rows = cap_qs(qs)

            def loc_url(loc):
                tags = "warehouse,logistics" if loc.location_type == "warehouse" else "warehouse,shelves"
                lock = (loc.pk % 9000) + 1000
                return f"https://loremflickr.com/400/400/{tags}?lock={lock}"

            process_batch("location", "Locations", rows, loc_url)

        if only in ("suppliers", "all"):
            qs = Supplier.objects.filter(is_active=True).order_by("pk")
            if not force:
                qs = qs.filter(_no_image_q())
            rows = cap_qs(qs)

            def sup_url(sup):
                lock = (sup.pk % 9000) + 3000
                return f"https://loremflickr.com/400/400/company,office?lock={lock}"

            process_batch("supplier", "Suppliers", rows, sup_url)

        if only in ("clients", "all"):
            qs = Client.objects.filter(is_active=True).order_by("pk")
            if not force:
                qs = qs.filter(_no_image_q())
            rows = cap_qs(qs)

            def cli_url(cli):
                lock = (cli.pk % 9000) + 6000
                return f"https://loremflickr.com/400/400/shop,store?lock={lock}"

            process_batch("client", "Clients", rows, cli_url)

        self.stdout.write(
            self.style.NOTICE(f"Done. saved/queued={stats['ok']} skipped={stats['skip']} failed={stats['fail']}")
        )
