from django.contrib import admin
from django.urls import path

from . import admin_views

app_name = "platform_ops"
urlpatterns = [
    path("language/", admin_views.language, name="language"),
    path("", admin.site.admin_view(admin_views.dashboard), name="dashboard"),
    path(
        "coverage/",
        admin.site.admin_view(admin_views.collection_coverage),
        name="collection_coverage",
    ),
    path(
        "controls/",
        admin.site.admin_view(admin_views.collection_controls),
        name="collection_controls",
    ),
    path(
        "directory/", admin.site.admin_view(admin_views.market_directory), name="market_directory"
    ),
    path("quality/", admin.site.admin_view(admin_views.data_quality), name="data_quality"),
    path("raw/", admin.site.admin_view(admin_views.raw_payloads), name="raw_payloads"),
    path(
        "raw/confirm/", admin.site.admin_view(admin_views.confirm_deletion), name="confirm_deletion"
    ),
    path(
        "raw/<uuid:market_id>/<uuid:observation_id>/",
        admin.site.admin_view(admin_views.raw_observation),
        name="raw_observation",
    ),
]
