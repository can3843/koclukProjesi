from django import template

register = template.Library()


@register.filter
def duration_tr(minutes):
    """Minutes to words: 270 -> "4 saat 30 dakika"."""
    minutes = int(minutes or 0)
    hours, rest = divmod(minutes, 60)
    parts = []
    if hours:
        parts.append(f"{hours} saat")
    if rest or not hours:
        parts.append(f"{rest} dakika")
    return " ".join(parts)


@register.filter
def hours_of(minutes):
    """Whole hours (rounded) of a minute count."""
    return round((minutes or 0) / 60)


@register.filter
def percent(ratio):
    return round((ratio or 0) * 100)
