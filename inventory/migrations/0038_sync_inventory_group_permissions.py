# Assign full inventory.* permissions to Admin/Manager; Staff keeps view-only on core models.

from django.db import migrations


# ContentType.model values (lowercase) for the six Staff-facing resources
_STAFF_CORE_MODELS = frozenset(
    {"item", "order", "supplier", "client", "category", "location"}
)


def sync_inventory_group_permissions(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    inv_ct_ids = list(
        ContentType.objects.filter(app_label="inventory").values_list("pk", flat=True)
    )
    if not inv_ct_ids:
        return

    all_inv_pks = list(
        Permission.objects.filter(content_type_id__in=inv_ct_ids).values_list(
            "pk", flat=True
        )
    )

    staff_ct_ids = list(
        ContentType.objects.filter(
            app_label="inventory",
            model__in=_STAFF_CORE_MODELS,
        ).values_list("pk", flat=True)
    )
    staff_view_pks = list(
        Permission.objects.filter(
            content_type_id__in=staff_ct_ids,
            codename__startswith="view_",
        ).values_list("pk", flat=True)
    )

    for name in ("Admin", "Manager"):
        g = Group.objects.filter(name=name).first()
        if g and all_inv_pks:
            g.permissions.set(all_inv_pks)

    staff_g = Group.objects.filter(name="Staff").first()
    if staff_g and staff_view_pks:
        staff_g.permissions.set(staff_view_pks)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0037_backfill_activity_kind"),
    ]

    operations = [
        migrations.RunPython(sync_inventory_group_permissions, noop_reverse),
    ]
