from unittest.mock import patch
from uuid import uuid4

import pytest
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse
from django.utils import translation
from quanthecy.accounts.models import User
from quanthecy.operations.forms import RawWindowForm

pytestmark = pytest.mark.django_db


def test_language_switch_requires_csrf_and_preserves_filtered_page():
    client = Client(enforce_csrf_checks=True)
    login = client.get(reverse("admin:login"))
    assert login.headers["Content-Language"] == "zh-hans"
    assert "登录管理控制台" in login.content.decode()
    endpoint = reverse("platform_ops:language")
    assert client.get(endpoint).status_code == 405
    assert client.post(endpoint, {"language": "en"}).status_code == 403
    token = client.cookies["csrftoken"].value
    destination = "/admin/accounts/user/?q=research%40example.com&is_active__exact=1"
    switched = client.post(
        endpoint,
        {"language": "en", "next": destination, "csrfmiddlewaretoken": token},
    )
    assert switched.status_code == 302 and switched.url == destination
    cookie = switched.cookies["quanthecy_admin_language"]
    assert cookie.value == "en" and cookie["httponly"] and cookie["samesite"] == "Lax"
    login = client.get(reverse("admin:login"))
    assert login.headers["Content-Language"] == "en"
    assert b"Sign in to console" in login.content
    assert (
        client.post(endpoint, {"language": "invalid", "csrfmiddlewaretoken": token}).status_code
        == 400
    )
    client.post(endpoint, {"language": "zh-hans", "csrfmiddlewaretoken": token})
    assert client.get(reverse("admin:login")).headers["Content-Language"] == "zh-hans"


@pytest.mark.parametrize(
    "destination",
    ["https://example.com/admin/", "//example.com/admin/", "/api/v1/markets", "/admin\\evil"],
)
def test_language_redirect_stays_inside_console(destination):
    response = Client().post(
        reverse("platform_ops:language"), {"language": "en", "next": destination}
    )
    assert response.status_code == 302 and response.url == "/admin/"


def test_console_language_does_not_leak_to_public_api():
    client = Client()
    client.cookies["quanthecy_admin_language"] = "zh-hans"
    with translation.override("en-us"):
        assert client.get(reverse("admin:login")).headers["Content-Language"] == "zh-hans"
        assert translation.get_language() == "en-us"
        response = client.get("/api/v1/me")
        assert response.status_code == 401
        assert "Content-Language" not in response.headers
        assert translation.get_language() == "en-us"


def test_overview_and_navigation_respect_operator_permissions():
    viewer = User.objects.create_user("viewer@example.com", is_staff=True)
    viewer.user_permissions.add(
        Permission.objects.get(content_type__app_label="operations", codename="view_raw_payloads")
    )
    client = Client()
    client.force_login(viewer)
    with patch("quanthecy.markets.collection.collection_status") as collection:
        response = client.get(reverse("admin:index"))
        collection.assert_not_called()
    html = response.content.decode()
    assert response.status_code == 200
    assert reverse("platform_ops:raw_payloads") in html
    assert reverse("admin:accounts_user_changelist") not in html
    assert reverse("admin:operations_platformauditlog_changelist") not in html
    assert "已采集市场" not in html and "有效用户" not in html
    with patch("quanthecy.operations.admin_views.repository") as repo:
        repo.return_value.observations.return_value = []
        response = client.get(reverse("platform_ops:raw_payloads"))
    assert "预览当前范围清理" not in response.content.decode()


@pytest.mark.parametrize("language,heading", [("en", "Overview"), ("zh-hans", "运行总览")])
def test_console_pages_render_with_real_data_in_both_languages(language, heading):
    operator = User.objects.create_superuser("operator@example.com", "test-password")
    client = Client()
    client.force_login(operator)
    client.cookies["quanthecy_admin_language"] = language
    collection = {
        "sources": [
            {"platform": "polymarket", "state": "recent", "fresh_markets": 2, "total_markets": 3}
        ]
    }
    with patch("quanthecy.markets.collection.collection_status", return_value=collection):
        overview = client.get(reverse("admin:index"))
    assert overview.status_code == 200
    assert f"<h1>{heading}</h1>" in overview.content.decode()
    assert b"2 / 3" in overview.content
    with (
        patch("quanthecy.operations.admin_views.collection_status", return_value=collection),
        patch("quanthecy.operations.admin_views.dependency_status", return_value={"redis": True}),
        patch("quanthecy.operations.admin_views.repository") as repo,
    ):
        repo.return_value.collector_batches.return_value = []
        repo.return_value.observations.return_value = []
        repo.return_value.observation.return_value = {
            "raw_payload": '{"title": "<script>alert(1)</script>"}',
            "envelope": "{}",
        }
        for route in [
            "platform_ops:dashboard",
            "platform_ops:raw_payloads",
            "admin:accounts_user_changelist",
            "admin:operations_rawpayloaddeletion_changelist",
            "admin:operations_platformauditlog_changelist",
        ]:
            response = client.get(reverse(route))
            assert response.status_code == 200
            assert response.headers["Content-Language"] == language
        detail = client.get(reverse("platform_ops:raw_observation", args=[uuid4(), uuid4()]))
        assert b"&lt;script&gt;" in detail.content and b"<script>alert" not in detail.content


def test_view_only_user_table_does_not_offer_account_changes():
    viewer = User.objects.create_user("viewer@example.com", is_staff=True)
    viewer.user_permissions.add(
        Permission.objects.get(content_type__app_label="accounts", codename="view_user")
    )
    client = Client()
    client.force_login(viewer)
    response = client.get(reverse("admin:accounts_user_changelist"))
    assert response.status_code == 200
    assert reverse("admin:accounts_user_status", args=[viewer.pk]) not in response.content.decode()


def test_raw_date_picker_preserves_utc_range_from_pagination_links():
    data = {
        "platform": "polymarket",
        "start": "2026-09-16T20:00:00.123456+08:00",
        "end": "2026-09-16T13:00:00+00:00",
    }
    form = RawWindowForm(data)
    assert form.is_valid()
    assert 'type="datetime-local"' in str(form["start"])
    assert 'value="2026-09-16T12:00:00.123456"' in str(form["start"])
    submitted = RawWindowForm(
        {**data, "start": "2026-09-16T12:00:00.123456", "end": "2026-09-16T13:00:00"}
    )
    assert submitted.is_valid() and submitted.window() == form.window()
