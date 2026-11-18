from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

admin.site.site_header = "Shadebreak"
admin.site.site_title = "Shadebreak admin"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("i18n/", include("django.conf.urls.i18n")),
    path(
        "manifest.webmanifest",
        TemplateView.as_view(template_name="manifest.webmanifest", content_type="application/manifest+json"),
        name="manifest",
    ),
    path("", include("messaging.urls")),
    path("", include("crews.urls")),
]
