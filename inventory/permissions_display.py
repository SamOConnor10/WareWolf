"""Human-readable grouping of Django permission strings for profile / UI."""

from collections import defaultdict
from itertools import groupby

VERB_ORDER = ("view", "add", "change", "delete")

VERB_LABEL = {
    "view": "View",
    "add": "Add",
    "change": "Edit",
    "delete": "Delete",
}

VERB_BADGE_CLASS = {
    "view": "bg-secondary-subtle text-secondary border",
    "add": "bg-success-subtle text-success border",
    "change": "bg-primary-subtle text-primary border",
    "delete": "bg-danger-subtle text-danger border",
}

_INVENTORY_MODEL_LABELS = {
    "item": "Stock Items",
    "category": "Categories",
    "location": "Locations",
    "order": "Orders",
    "orderline": "Order Lines",
    "supplier": "Suppliers",
    "client": "Customers",
    "stockhistory": "Stock History",
    "managerrequest": "Manager Requests",
    "notification": "Notifications",
    "activity": "Activity Records",
    "demandanomaly": "Demand Anomalies",
    "userpreference": "User Preferences",
    "userprofile": "User Profiles",
    "recommendation": "Recommendations",
}

# First column in the profile permission matrix (logical grouping).
_INVENTORY_RESOURCE_AREA = {
    "item": "Core Inventory",
    "category": "Core Inventory",
    "location": "Core Inventory",
    "order": "Core Inventory",
    "orderline": "Core Inventory",
    "supplier": "Contacts",
    "client": "Contacts",
    "demandanomaly": "Forecasts & Anomalies",
    "recommendation": "Forecasts & Anomalies",
    "stockhistory": "Forecasts & Anomalies",
    "managerrequest": "Access & Onboarding",
    "notification": "Notifications",
    "userpreference": "Personal Account",
    "userprofile": "Personal Account",
    "activity": "Audit Trail",
}

_AREA_SORT_ORDER = {
    "Core Inventory": 0,
    "Contacts": 1,
    "Forecasts & Anomalies": 2,
    "Access & Onboarding": 3,
    "Notifications": 4,
    "Personal Account": 5,
    "Audit Trail": 6,
    "Authentication": 20,
    "Administration": 21,
    "Inventory & Operations": 40,
    "Other Inventory": 41,
}


def _app_display(app_label: str) -> str:
    if app_label == "inventory":
        return "Inventory & Operations"
    if app_label == "auth":
        return "Authentication"
    if app_label == "admin":
        return "Administration"
    return app_label.replace("_", " ").title()


def _model_label(app_label: str, model_slug: str) -> str:
    if app_label == "inventory":
        if model_slug in _INVENTORY_MODEL_LABELS:
            return _INVENTORY_MODEL_LABELS[model_slug]
    return model_slug.replace("_", " ").title()


def _area_display(app_label: str, model_slug: str) -> str:
    if app_label == "inventory":
        return _INVENTORY_RESOURCE_AREA.get(model_slug, "Other Inventory")
    return _app_display(app_label)


def summarize_permissions(perm_strings: list[str]) -> dict:
    """
    Group standard add_/change_/delete_/view_ permissions by app + model.
    Returns:
      rows: sorted list of dicts (area_display, model_label, verbs, app)
      other_permissions: codenames that did not match the standard pattern
    """
    groups: dict[tuple[str, str], set[str]] = defaultdict(set)
    other: list[str] = []

    for p in perm_strings:
        if "." not in p:
            other.append(p)
            continue
        app, codename = p.split(".", 1)
        matched = False
        for v in VERB_ORDER:
            prefix = f"{v}_"
            if codename.startswith(prefix):
                model_slug = codename[len(prefix):]
                groups[(app, model_slug)].add(v)
                matched = True
                break
        if not matched:
            other.append(p)

    rows = []
    for (app, model_slug), verbs in groups.items():
        verb_list = sorted(verbs, key=lambda x: VERB_ORDER.index(x))
        area = _area_display(app, model_slug)
        verb_dicts = [
            {
                "code": v,
                "label": VERB_LABEL[v],
                "badge_class": VERB_BADGE_CLASS[v],
            }
            for v in verb_list
        ]
        view_only_row = len(verb_list) == 1 and verb_list[0] == "view"
        rows.append(
            {
                "app": app,
                "area_display": area,
                "app_display": _app_display(app),
                "model_label": _model_label(app, model_slug),
                "verbs": verb_dicts,
                "view_only_row": view_only_row,
            }
        )

    def sort_key(r: dict) -> tuple:
        area_rank = _AREA_SORT_ORDER.get(r["area_display"], 99)
        return (area_rank, r["area_display"].lower(), r["model_label"].lower())

    rows.sort(key=sort_key)

    area_groups = []
    for area, iterator in groupby(rows, key=lambda r: r["area_display"]):
        sub = list(iterator)
        area_groups.append(
            {
                "area_display": area,
                "rows": sub,
                "rowspan": len(sub),
            }
        )

    return {
        "rows": rows,
        "area_groups": area_groups,
        "other_permissions": sorted(other),
        "resource_count": len(rows),
        "other_count": len(other),
    }


def build_role_capability_sections(user) -> list[dict]:
    """
    Summarise what Manager vs Staff can do in the app, including flows gated by
    group membership (not only Django model permissions).
    """
    if getattr(user, "is_superuser", False):
        return [
            {
                "title": "Superuser",
                "intro": None,
                "items": [
                    "Full access across WareWolf and Django admin (where your account is allowed to sign in).",
                ],
            }
        ]

    names = set(user.groups.values_list("name", flat=True))
    manager_like = bool(names & {"Manager", "Admin"})
    staff_member = "Staff" in names

    sections: list[dict] = []

    if manager_like:
        sections.append(
            {
                "title": "What Managers and Admins Can Do in WareWolf",
                "intro": (
                    "Along with the permission matrix below, your role can use manager-only "
                    "workflows that are enforced by group membership:"
                ),
                "items": [
                    "Full create, edit, archive, delete, and quantity adjustments for stock, categories, locations, orders, suppliers, and customers.",
                    "Stock: item detail, images, barcodes, low-stock and expiry context, demand forecast view, and quick-adjust flows from the list.",
                    "Orders: create, edit, delete, duplicate, mark delivered, receiving/shipping locations, and recommendation shortcuts when placing orders.",
                    "Locations: list and hierarchy (tree) views, capacity fields, and CSV export; contacts: full supplier and customer records with exports.",
                    "Dashboard and global search across items, orders, and suppliers; open and act on alerts and notification-style messages you are allowed to see.",
                    "Demand anomalies: open the list, queue scans, mark reviewed, dismiss or restore items, and use bulk actions.",
                    "Review pending requests when staff apply for Manager access (approve or decline).",
                    "Permanently remove a stock item (hard delete), including linked order lines and stock history, after confirmation.",
                    "Exports and operational CSV downloads where the app exposes them (stock, locations, orders, contacts, and your own activity log).",
                ],
            }
        )

    if staff_member and not manager_like:
        sections.append(
            {
                "title": "What Staff Can Do in WareWolf",
                "intro": (
                    "Your permissions are view-first on core inventory data. You will be blocked "
                    "from changing operational records or using manager-only tools."
                ),
                "items": [
                    "View dashboards, stock items, orders, locations, suppliers, and customers (lists and read-only detail where the app allows).",
                    "Use global search to find records, then open them in view mode without changing data.",
                    "Use your profile: personal details, profile photo, security (password), activity log, CSV export of your own activity, and preferences.",
                    "Dismiss or clear your own in-app notifications where the UI offers it.",
                    "From profile, submit a Manager access request if your organisation uses that workflow.",
                    "You cannot add, edit, delete, or archive inventory records, adjust quantities, run anomaly scans or bulk anomaly tools, approve Manager access for others, or permanently delete stock.",
                ],
            }
        )

    if not sections:
        sections.append(
            {
                "title": "Role Assignment",
                "intro": None,
                "items": [
                    "No Staff or Manager group is on this account. Contact an administrator if you expect access to WareWolf.",
                ],
            }
        )

    return sections
