"""Add dummy Dublin addresses and coordinates to warehouse locations."""
from django.core.management.base import BaseCommand
from inventory.models import Location

# Real Dublin addresses (Ireland) with lat/lng
DUBLIN_ADDRESSES = [
    {
        "address": "Grand Canal Dock, Dublin 2, Ireland",
        "latitude": 53.3438,
        "longitude": -6.2366,
    },
    {
        "address": "Smithfield, Dublin 7, Ireland",
        "latitude": 53.3486,
        "longitude": -6.2775,
    },
    {
        "address": "Liberty Lane, Dublin 8, Ireland",
        "latitude": 53.3409,
        "longitude": -6.2945,
    },
    {
        "address": "Parkgate Street, Dublin 8, Ireland",
        "latitude": 53.3478,
        "longitude": -6.2942,
    },
    {
        "address": "Ballymount, Dublin 24, Ireland",
        "latitude": 53.3198,
        "longitude": -6.3695,
    },
]


class Command(BaseCommand):
    help = "Add dummy Dublin addresses and coordinates to warehouse locations"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be updated without saving",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        warehouses = Location.objects.filter(location_type="warehouse", is_active=True).order_by("id")
        if not warehouses.exists():
            self.stdout.write("No active warehouse locations found.")
            return

        updated = 0
        for i, loc in enumerate(warehouses):
            addr = DUBLIN_ADDRESSES[i % len(DUBLIN_ADDRESSES)]
            self.stdout.write(f"  {loc.name} -> {addr['address']}")
            if not dry_run:
                loc.address = addr["address"]
                loc.latitude = addr["latitude"]
                loc.longitude = addr["longitude"]
                loc.save()
                updated += 1

        if dry_run:
            self.stdout.write(self.style.WARNING(f"Dry run: would update {warehouses.count()} location(s)."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Updated {updated} warehouse location(s) with Dublin addresses."))
