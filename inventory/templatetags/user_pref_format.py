from django import template
from django.contrib.humanize.templatetags.humanize import intcomma
from django.template.defaultfilters import date as django_date_filter

from inventory.models import UserPreference

register = template.Library()

_SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£"}


@register.filter
def ww_currency_symbol(code):
    return _SYMBOLS.get(str(code or "").upper(), "€")


def _pref(context):
    return context.get("user_pref")


@register.simple_tag(takes_context=True)
def ww_date(context, value):
    if value in (None, ""):
        return ""
    pref = _pref(context)
    if not pref:
        fmt = "d M Y"
    else:
        style = getattr(pref, "date_format_style", None) or UserPreference.DATE_DMY
        fmt = {
            UserPreference.DATE_DMY: "d M Y",
            UserPreference.DATE_MDY: "M j, Y",
            UserPreference.DATE_ISO: "Y-m-d",
        }.get(style, "d M Y")
    return django_date_filter(value, fmt)


@register.simple_tag(takes_context=True)
def ww_datetime(context, value):
    if value in (None, ""):
        return ""
    pref = _pref(context)
    if not pref:
        dfmt, tfmt = "d M Y", "H:i"
    else:
        style = getattr(pref, "date_format_style", None) or UserPreference.DATE_DMY
        dfmt = {
            UserPreference.DATE_DMY: "d M Y",
            UserPreference.DATE_MDY: "M j, Y",
            UserPreference.DATE_ISO: "Y-m-d",
        }.get(style, "d M Y")
        cf = getattr(pref, "clock_format", None) or UserPreference.CLOCK_24
        tfmt = "H:i" if cf == UserPreference.CLOCK_24 else "g:i A"
    return django_date_filter(value, f"{dfmt}, {tfmt}")


@register.simple_tag(takes_context=True)
def ww_money(context, amount):
    pref = _pref(context)
    code = getattr(pref, "default_currency", None) if pref else None
    sym = _SYMBOLS.get(str(code or "EUR").upper(), "€")
    try:
        val = float(amount)
    except (TypeError, ValueError):
        return f"{sym}{amount}"
    whole, frac = f"{val:.2f}".split(".")
    return f"{sym}{intcomma(whole)}.{frac}"
