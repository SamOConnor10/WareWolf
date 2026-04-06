"""
Keep auth groups consistent with manager approval and avoid "active but no permissions" (403 on most pages).

Dashboard is @login_required only; list views use @permission_required(..., raise_exception=True).
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.db.models.signals import post_save
from django.dispatch import receiver

from inventory.models import ManagerRequest

User = get_user_model()


def _ensure_role_permissions():
    """If default groups are missing or empty, populate permissions (idempotent)."""
    for name in ("Admin", "Manager", "Staff"):
        g = Group.objects.filter(name=name).first()
        if g is None or not g.permissions.exists():
            call_command("setup_roles")
            return


@receiver(post_save, sender=User)
def sync_inventory_groups_after_user_save(
    sender, instance, created, raw=False, update_fields=None, **kwargs
):
    # Fixture loads use raw=True; do not mutate groups during loaddata.
    if raw or not instance.is_active or instance.is_superuser:
        return

    # Skip redundant work when only last_login changed and user already has roles.
    if update_fields is not None and set(update_fields) <= {"last_login"} and instance.groups.exists():
        return

    try:
        mr = ManagerRequest.objects.get(user=instance)
    except ManagerRequest.DoesNotExist:
        mr = None

    if mr and mr.status == "APPROVED":
        _ensure_role_permissions()
        manager_group, _ = Group.objects.get_or_create(name="Manager")
        if not instance.groups.filter(pk=manager_group.pk).exists():
            instance.groups.add(manager_group)

    if instance.groups.exists():
        return

    _ensure_role_permissions()
    staff_group, _ = Group.objects.get_or_create(name="Staff")
    instance.groups.add(staff_group)
