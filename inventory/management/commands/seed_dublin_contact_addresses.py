"""Assign Dublin/Ireland addresses and coordinates to suppliers and customers for maps."""
from decimal import Decimal

from django.core.management.base import BaseCommand

from inventory.models import Client, Supplier

# Real Dublin-area addresses with approximate lat/lng for demo maps
DUBLIN_CONTACT_POINTS = [
    {"address": "Grand Canal Dock, Hanover Quay, Dublin 2, Ireland", "latitude": Decimal("53.3438"), "longitude": Decimal("-6.2366")},
    {"address": "Smithfield Square, Dublin 7, Ireland", "latitude": Decimal("53.3486"), "longitude": Decimal("-6.2775")},
    {"address": "Heuston Station, Dublin 8, Ireland", "latitude": Decimal("53.3464"), "longitude": Decimal("-6.2931")},
    {"address": "Parkgate Street, Dublin 8, Ireland", "latitude": Decimal("53.3478"), "longitude": Decimal("-6.2942")},
    {"address": "Liberty Lane, Dublin 8, Ireland", "latitude": Decimal("53.3409"), "longitude": Decimal("-6.2945")},
    {"address": "Ballymount Road, Dublin 24, Ireland", "latitude": Decimal("53.3198"), "longitude": Decimal("-6.3695")},
    {"address": "East Wall Road, Dublin 3, Ireland", "latitude": Decimal("53.3581"), "longitude": Decimal("-6.2278")},
    {"address": "Sandyford Business District, Dublin 18, Ireland", "latitude": Decimal("53.2756"), "longitude": Decimal("-6.2188")},
    {"address": "Blanchardstown Centre, Dublin 15, Ireland", "latitude": Decimal("53.3927"), "longitude": Decimal("-6.3756")},
    {"address": "Tallaght, Dublin 24, Ireland", "latitude": Decimal("53.2859"), "longitude": Decimal("-6.3734")},
    {"address": "Dun Laoghaire Harbour, Co. Dublin, Ireland", "latitude": Decimal("53.2939"), "longitude": Decimal("-6.1358")},
    {"address": "IFSC, North Wall Quay, Dublin 1, Ireland", "latitude": Decimal("53.3480"), "longitude": Decimal("-6.2482")},
    {"address": "Phoenix Park Visitor Centre, Dublin 8, Ireland", "latitude": Decimal("53.3559"), "longitude": Decimal("-6.3293")},
    {"address": "Clontarf Road, Dublin 3, Ireland", "latitude": Decimal("53.3649"), "longitude": Decimal("-6.2185")},
    {"address": "Cherrywood, Dublin 18, Ireland", "latitude": Decimal("53.2456"), "longitude": Decimal("-6.1489")},
]


class Command(BaseCommand):
    help = "Seed Dublin/Ireland addresses and lat/lng on suppliers and customers (for contact maps)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite existing address and coordinates on every active supplier and client.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print planned updates without saving.",
        )

    def handle(self, *args, **options):
        force = options["force"]
        dry_run = options["dry_run"]
        n = len(DUBLIN_CONTACT_POINTS)
        updated_s = 0
        updated_c = 0

        suppliers = list(Supplier.objects.filter(is_active=True).order_by("id"))
        for i, obj in enumerate(suppliers):
            pt = DUBLIN_CONTACT_POINTS[i % n]
            if not force and obj.latitude is not None and obj.longitude is not None and (obj.address or "").strip():
                continue
            self.stdout.write(f"Supplier {obj.id} {obj.name}: {pt['address']}")
            if not dry_run:
                obj.address = pt["address"]
                obj.latitude = pt["latitude"]
                obj.longitude = pt["longitude"]
                obj.save(update_fields=["address", "latitude", "longitude"])
            updated_s += 1

        clients = list(Client.objects.filter(is_active=True).order_by("id"))
        for i, obj in enumerate(clients):
            pt = DUBLIN_CONTACT_POINTS[(i + 3) % n]
            if not force and obj.latitude is not None and obj.longitude is not None and (obj.address or "").strip():
                continue
            self.stdout.write(f"Client {obj.id} {obj.name}: {pt['address']}")
            if not dry_run:
                obj.address = pt["address"]
                obj.latitude = pt["latitude"]
                obj.longitude = pt["longitude"]
                obj.save(update_fields=["address", "latitude", "longitude"])
            updated_c += 1

        if dry_run:
            self.stdout.write(self.style.WARNING(f"Dry run: would touch {updated_s} supplier(s), {updated_c} client(s)."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Updated {updated_s} supplier(s) and {updated_c} client(s)."))
