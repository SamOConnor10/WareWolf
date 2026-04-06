"""Post-login redirect from saved user landing preference."""

from django.urls import NoReverseMatch, reverse

_VALID_LANDINGS = frozenset(
    {
        "dashboard",
        "item_list",
        "location_list",
        "order_list",
        "contacts_list",
        "alerts_list",
        "anomaly_list",
        "settings",
    }
)


def get_post_login_redirect_url(user):
    from .models import UserPreference

    if not user.is_authenticated:
        return reverse("dashboard")
    pref = UserPreference.objects.filter(user=user).only("default_landing").first()
    name = (pref.default_landing if pref else None) or UserPreference.LANDING_DASHBOARD
    if name not in _VALID_LANDINGS:
        name = UserPreference.LANDING_DASHBOARD
    try:
        return reverse(name)
    except NoReverseMatch:
        return reverse("dashboard")
