# Backfill Activity.kind from message text for rows created before kind was set per-action.

from django.db import migrations


def _infer_kind(message: str) -> str:
    if not message:
        return "other"
    m = message
    if m.startswith("Archived item (auto") or "(auto, stock depleted)" in m:
        return "item_auto_archive"
    if m.startswith("Unarchived item:"):
        return "item_unarchive"
    if m.startswith("Archived item:"):
        return "item_archive"
    if m.startswith("Permanently deleted item:"):
        return "item_hard_delete"
    if m.startswith("Item deleted:"):
        return "item_delete"
    if m.startswith("Adjusted quantity for"):
        return "item_adjust"
    if m.startswith("New item created:"):
        return "item_create"
    if m.startswith("Item updated:"):
        return "item_update"
    if m.startswith("Order #") and "delivered" in m.lower():
        return "order_stock"
    if "Order #" in m and "updated stock" in m.lower():
        return "order_stock"
    return "other"


def backfill_kinds(apps, schema_editor):
    Activity = apps.get_model("inventory", "Activity")
    batch = []
    for act in Activity.objects.filter(kind="other").iterator(chunk_size=500):
        new_kind = _infer_kind(act.message)
        if new_kind != "other":
            act.kind = new_kind
            batch.append(act)
        if len(batch) >= 500:
            Activity.objects.bulk_update(batch, ["kind"])
            batch.clear()
    if batch:
        Activity.objects.bulk_update(batch, ["kind"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0036_activity_kind"),
    ]

    operations = [
        migrations.RunPython(backfill_kinds, noop_reverse),
    ]
