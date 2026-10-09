"""Small sliding-window rate limiter on Django's cache (a database cache here; see CACHES in settings)."""

import time

from django.core.cache import cache

LOGIN_FAILURES = (10, 15 * 60)   # 10 failed logins per 15 minutes
REGISTER_ATTEMPTS = (10, 60 * 60)  # 10 registration attempts per hour


def client_ip(request):
    """Vercel overwrites X-Forwarded-For with the real client address, so its first entry can be trusted there."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _key(scope, request):
    return f"ratelimit:{scope}:{client_ip(request)}"


def _recent(key, window):
    cutoff = time.time() - window
    return [stamp for stamp in cache.get(key, []) if stamp > cutoff]


def is_limited(scope, request, rule):
    limit, window = rule
    return len(_recent(_key(scope, request), window)) >= limit


def record(scope, request, rule):
    _, window = rule
    key = _key(scope, request)
    stamps = _recent(key, window)
    stamps.append(time.time())
    cache.set(key, stamps, window)


def reset(scope, request):
    cache.delete(_key(scope, request))
