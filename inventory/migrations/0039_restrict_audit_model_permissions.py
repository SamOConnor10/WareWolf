# Activity + StockHistory: view-only on Manager/Admin (append-only / system-managed in WareWolf).

from django.db import migrations

_READONLY_MODELS = frozenset({"activity", "stockhistory"})


def _filtered_inventory_perm_pks(Permission, CT):
    inv_ct_ids = list(
        CT.objects.filter(app_label="inventory").values_list("pk", flat=True)
    )
    if not inv_ct_ids:
        return []
    pks = []
    for p in (
        Permission.objects.filter(content_type_id__in=inv_ct_ids)
        .select_related("content_type")
        .order_by("id")
    ):
        mod = p.content_type.model
        if mod in _READONLY_MODELS:
            if p.codename.startswith("view_"):
                pks.append(p.pk)
        else:
            pks.append(p.pk)
    return pks


def apply_restrictions(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    pks = _filtered_inventory_perm_pks(Permission, ContentType)
    if not pks:
        return

    for name in ("Admin", "Manager"):
        g = Group.objects.filter(name=name).first()
        if g:
            g.permissions.set(pks)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0038_sync_inventory_group_permissions"),
    ]

    operations = [
        migrations.RunPython(apply_restrictions, noop_reverse),
    ]
