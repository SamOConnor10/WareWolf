"""
Remove stock item images created by seed_entity_demo_images only.

Those files are always saved as item_<pk>.jpg under upload_to items/.
Other filenames (manual uploads) are left unchanged.
"""
import re

from django.core.management.base import BaseCommand
from django.db.models import Q

from inventory.models import Item

SEEDED_ITEM_IMAGE = re.compile(r"^item_\d+\.jpe?g$", re.IGNORECASE)


class Command(BaseCommand):
    help = "Delete Item images that match seed_entity_demo_images naming (item_<pk>.jpg)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List matches only; do not delete files or clear fields.",
        )

    def handle(self, *args, **options):
        dry = options["dry_run"]
        qs = Item.objects.exclude(Q(image__isnull=True) | Q(image=""))
        cleared = 0
        for item in qs.iterator():
            base = item.image.name.rsplit("/", 1)[-1]
            if not SEEDED_ITEM_IMAGE.match(base):
                continue
            if dry:
                pass
            else:
                item.image.delete(save=False)
                item.image = None
                item.save(update_fields=["image"])
            cleared += 1
        msg = f"{'Would clear' if dry else 'Cleared'} {cleared} stock item image(s) (seed name item_<pk>.jpg only)."
        self.stdout.write(self.style.WARNING(msg) if dry else self.style.SUCCESS(msg))
