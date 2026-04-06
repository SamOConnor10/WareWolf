from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone as django_timezone
from django.utils import translation


def _allowed_languages():
    return {code for code, _ in getattr(settings, "LANGUAGES", (("en", "English"),))}


def _normalize_lang(raw_code: str, allowed: set) -> str:
    raw = (raw_code or "").strip().replace("_", "-").lower()
    if not raw:
        base = getattr(settings, "LANGUAGE_CODE", "en")
        return base if base in allowed else ("en" if "en" in allowed else sorted(allowed)[0])
    aliases = {"en-us": "en"}
    raw = aliases.get(raw, raw)
    if raw in allowed:
        return raw
    primary = raw.split("-")[0]
    if primary in allowed:
        return primary
    return "en" if "en" in allowed else sorted(allowed)[0]


def _cached_pref(user):
    cache_key = f"ctx_user_pref:v6:{user.pk}"
    pref = cache.get(cache_key)
    if pref is None:
        from .models import UserPreference

        pref, _ = UserPreference.objects.get_or_create(user=user)
        cache.set(cache_key, pref, 120)
    return pref


class UserPreferenceActivationMiddleware:
    """Apply timezone and UI language from UserPreference for authenticated users."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            pref = _cached_pref(request.user)
            tzname = (pref.timezone_name or "UTC").strip() or "UTC"
            try:
                django_timezone.activate(ZoneInfo(tzname))
            except (ZoneInfoNotFoundError, ValueError, TypeError):
                django_timezone.activate(ZoneInfo("UTC"))
            allowed = _allowed_languages()
            lang = _normalize_lang(getattr(pref, "language_code", None) or settings.LANGUAGE_CODE, allowed)
            translation.activate(lang)
            request.LANGUAGE_CODE = lang
        else:
            django_timezone.deactivate()

        response = self.get_response(request)

        if request.user.is_authenticated:
            translation.deactivate()
            django_timezone.deactivate()

        return response
