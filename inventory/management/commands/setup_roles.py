from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from inventory.models import Item, Order, Supplier, Client, Category, Location

class Command(BaseCommand):
    help = "Create default roles and assign permissions"

    def handle(self, *args, **options):
        admin_group, _ = Group.objects.get_or_create(name="Admin")
        manager_group, _ = Group.objects.get_or_create(name="Manager")
        staff_group, _ = Group.objects.get_or_create(name="Staff")

        # IMPORTANT: reset permissions so removed perms don't linger in DB
        admin_group.permissions.clear()
        manager_group.permissions.clear()
        staff_group.permissions.clear()

        models = [Item, Order, Supplier, Client, Category, Location]

        def perms_for_model(model):
            ct = ContentType.objects.get_for_model(model)
            return Permission.objects.filter(content_type=ct)

        # Admin: everything
        for m in models:
            admin_group.permissions.add(*perms_for_model(m))

        # Manager: everything
        for m in models:
            manager_group.permissions.add(*perms_for_model(m))

        # Staff: view-only
        for m in models:
            ct = ContentType.objects.get_for_model(m)
            staff_group.permissions.add(*Permission.objects.filter(
                content_type=ct,
                codename__startswith="view_"
            ))

        self.stdout.write(self.style.SUCCESS("Roles created/updated successfully."))
