from django.contrib import admin
from django.urls import path
from quanthecy.api.api import api
from quanthecy.operations.views import health, ready

urlpatterns = [
    path("health", health),
    path("ready", ready),
    path("admin/", admin.site.urls),
    path("api/v1/", api.urls),
]
