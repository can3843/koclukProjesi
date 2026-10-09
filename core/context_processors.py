from django.conf import settings


def assets(request):
    """Cache-busting version for the stylesheet and script links."""
    return {"asset_v": settings.ASSET_VERSION}
