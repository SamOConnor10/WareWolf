"""Create additional top-level warehouse locations with Dublin addresses (for maps and demos)."""
from decimal import Decimal

from django.core.management.base import BaseCommand

from inventory.models import Location

# Extra real-world style Dublin/Ireland sites (not necessarily operating warehouses)
EXTRA_WAREHOUSES = [
    {
        "name": "Southside Logistics Hub",
        "code": "SSH",
        "description": "Regional distribution — south Dublin corridor.",
        "address": "Cork Street Business Park, Dublin 8, Ireland",
        "latitude": Decimal("53.3372"),
        "longitude": Decimal("-6.2754"),
    },
    {
        "name": "Liffey Valley DC",
        "code": "LVD",
        "description": "West Dublin fulfilment and cross-dock.",
        "address": "Fonthill Road, Clondalkin, Dublin 22, Ireland",
        "latitude": Decimal("53.3551"),
        "longitude": Decimal("-6.3912"),
    },
    {
        "name": "Swords Trade Park DC",
        "code": "STP",
        "description": "North County Dublin inbound hub.",
        "address": "Airport Business Park, Swords, Co. Dublin, Ireland",
        "latitude": Decimal("53.4593"),
        "longitude": Decimal("-6.2188"),
    },
]


class Command(BaseCommand):
    help = "Add a few extra warehouse-type locations with Dublin-area addresses and coordinates."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be created without saving.",
        )

    def handle(self, *args, **options):
        dry = options["dry_run"]
        created = 0
        for w in EXTRA_WAREHOUSES:
            exists = Location.objects.filter(name=w["name"], parent__isnull=True).exists()
            if exists:
                self.stdout.write(f"Skip (exists): {w['name']}")
                continue
            self.stdout.write(f"Create: {w['name']} ({w['code']})")
            if dry:
                created += 1
                continue
            Location.objects.create(
                name=w["name"],
                code=w["code"],
                description=w["description"],
                address=w["address"],
                latitude=w["latitude"],
                longitude=w["longitude"],
                location_type="warehouse",
                structural=True,
                is_active=True,
                parent=None,
            )
            created += 1
        if dry:
            self.stdout.write(self.style.WARNING(f"Dry run: would create {created} warehouse location(s)."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Created {created} new warehouse location(s)."))
