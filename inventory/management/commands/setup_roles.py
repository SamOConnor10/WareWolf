from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

# Staff: view-only on these operational models (matches menu / view decorators).
_STAFF_CORE_MODELS = ("item", "order", "supplier", "client", "category", "location")

# Manager/Admin: these models are append-only or system-written in WareWolf — grant view_* only.
_MANAGER_READONLY_MODELS = frozenset({"activity", "stockhistory"})


class Command(BaseCommand):
    help = (
        "Create default roles and assign permissions "
        "(Admin/Manager: full inventory except view-only audit/history models; Staff: core view-only)."
    )

    def handle(self, *args, **options):
        admin_group, _ = Group.objects.get_or_create(name="Admin")
        manager_group, _ = Group.objects.get_or_create(name="Manager")
        staff_group, _ = Group.objects.get_or_create(name="Staff")

        inv_ct_ids = list(
            ContentType.objects.filter(app_label="inventory").values_list("pk", flat=True)
        )
        if not inv_ct_ids:
            self.stdout.write(self.style.WARNING("No inventory content types found; skipping."))
            return

        all_inv_perms = []
        for p in (
            Permission.objects.filter(content_type_id__in=inv_ct_ids)
            .select_related("content_type")
            .order_by("id")
        ):
            mod = p.content_type.model
            if mod in _MANAGER_READONLY_MODELS:
                if p.codename.startswith("view_"):
                    all_inv_perms.append(p)
            else:
                all_inv_perms.append(p)

        staff_ct_ids = list(
            ContentType.objects.filter(
                app_label="inventory",
                model__in=_STAFF_CORE_MODELS,
            ).values_list("pk", flat=True)
        )
        staff_view_perms = list(
            Permission.objects.filter(
                content_type_id__in=staff_ct_ids,
                codename__startswith="view_",
            )
        )

        admin_group.permissions.set(all_inv_perms)
        manager_group.permissions.set(all_inv_perms)
        staff_group.permissions.set(staff_view_perms)

        self.stdout.write(
            self.style.SUCCESS(
                f"Roles updated: Admin/Manager each have {len(all_inv_perms)} inventory "
                f"permissions; Staff has {len(staff_view_perms)} view-only permissions."
            )
        )
