from django.conf import settings

from .version import build_info, version_string


def shadebreak(request):
    return {
        "build": build_info(),
        "version_string": version_string(),
        "crew": getattr(request, "crew", None),
        "allow_signup": settings.SHADEBREAK_ALLOW_SIGNUP,
    }
