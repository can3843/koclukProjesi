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


@register.filter
def duration_short(minutes):
    """Minutes to a short form: 150 -> "2 sa 30 dk", 45 -> "45 dk"."""
    minutes = int(minutes or 0)
    hours, rest = divmod(minutes, 60)
    if hours and rest:
        return f"{hours} sa {rest} dk"
    return f"{hours} sa" if hours else f"{rest} dk"


@register.filter
def seconds_short(seconds):
    """Seconds to whole minutes in short form: 4500 -> "1 sa 15 dk"."""
    return duration_short(int(seconds or 0) // 60)
