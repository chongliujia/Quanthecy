import json
from unittest.mock import patch

import pytest
from django.test import Client
from quanthecy.accounts.models import User
from quanthecy.accounts.services import register_user
from quanthecy.organizations.models import OrganizationMembership
from quanthecy.organizations.services import create_organization

pytestmark = pytest.mark.django_db


def csrf_header(client):
    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 200
    return {"HTTP_X_CSRFTOKEN": response.json()["csrf_token"]}


def test_anonymous_auth_endpoints_require_csrf():
    client = Client(enforce_csrf_checks=True)
    for endpoint in ("register", "login"):
        response = client.post(
            f"/api/v1/auth/{endpoint}",
            {"email": "alice@example.com", "password": "Research-password-123!"},
            content_type="application/json",
        )
        assert response.status_code == 403
    assert not User.objects.exists()


def test_registration_login_logout_and_csrf_rotation():
    client = Client(enforce_csrf_checks=True)
    headers = csrf_header(client)
    credentials = {"email": "Alice@example.com", "password": "Research-password-123!"}
    response = client.post(
        "/api/v1/auth/register", credentials, content_type="application/json", **headers
    )
    assert response.status_code == 201, response.content
    assert set(response.json()) == {"id", "email", "email_verified_at"}
    assert client.get("/api/v1/me").json()["email"] == "alice@example.com"
    assert client.get("/api/v1/organizations").json()[0]["role"] == "OWNER"
    assert client.post("/api/v1/auth/logout", content_type="application/json").status_code == 403
    assert (
        client.post("/api/v1/auth/logout", content_type="application/json", **headers).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/auth/logout", content_type="application/json", **csrf_header(client)
        ).status_code
        == 200
    )
    assert client.get("/api/v1/me").status_code == 401
    assert (
        client.post(
            "/api/v1/auth/login",
            credentials,
            content_type="application/json",
            **csrf_header(client),
        ).status_code
        == 200
    )


def test_duplicate_registration_and_invalid_password():
    client = Client(enforce_csrf_checks=True)
    register_user(email="alice@example.com", password="Research-password-123!")
    response = client.post(
        "/api/v1/auth/register",
        {"email": "ALICE@example.com", "password": "Research-password-123!"},
        content_type="application/json",
        **csrf_header(client),
    )
    assert response.status_code == 409
    response = client.post(
        "/api/v1/auth/register",
        {"email": "new@example.com", "password": "123"},
        content_type="application/json",
        **csrf_header(client),
    )
    assert response.status_code == 422


def test_bad_password_and_inactive_account_cannot_login():
    client = Client(enforce_csrf_checks=True)
    User.objects.create_user("alice@example.com", "Research-password-123!", is_active=False)
    for email, password in [
        ("unknown@example.com", "bad"),
        ("alice@example.com", "Research-password-123!"),
    ]:
        response = client.post(
            "/api/v1/auth/login",
            {"email": email, "password": password},
            content_type="application/json",
            **csrf_header(client),
        )
        assert response.status_code == 401


def test_untrusted_origin_rejected_even_with_csrf_token():
    client = Client(enforce_csrf_checks=True)
    response = client.post(
        "/api/v1/auth/register",
        {"email": "alice@example.com", "password": "Research-password-123!"},
        content_type="application/json",
        HTTP_ORIGIN="https://untrusted.example",
        **csrf_header(client),
    )
    assert response.status_code == 403
    assert not User.objects.exists()


def test_organization_endpoints_enforce_tenant_and_role():
    owner = User.objects.create_user("owner@example.com")
    viewer = User.objects.create_user("viewer@example.com")
    org = create_organization(owner=owner, name="Private research")
    own_org = create_organization(owner=viewer, name="Viewer personal")
    client = Client(enforce_csrf_checks=True)
    client.force_login(viewer)
    assert client.get(f"/api/v1/organizations/{org.id}").status_code == 404
    assert client.get(f"/api/v1/organizations/{org.id}/members").status_code == 404
    assert [item["id"] for item in client.get("/api/v1/organizations").json()] == [str(own_org.id)]
    OrganizationMembership.objects.create(user=viewer, organization=org, role="VIEWER")
    assert client.get(f"/api/v1/organizations/{org.id}").status_code == 200
    assert (
        client.patch(
            f"/api/v1/organizations/{org.id}",
            {"name": "Changed"},
            content_type="application/json",
            **csrf_header(client),
        ).status_code
        == 403
    )
    client.force_login(owner)
    assert (
        client.patch(
            f"/api/v1/organizations/{org.id}",
            {"name": "Changed"},
            content_type="application/json",
            **csrf_header(client),
        ).status_code
        == 200
    )
    assert client.get("/api/v1/organizations?limit=0").status_code == 422


def test_cross_tenant_membership_mutation_and_last_owner_protection():
    user = User.objects.create_user("owner@example.com")
    first = create_organization(owner=user, name="First")
    second = create_organization(owner=user, name="Second")
    membership = OrganizationMembership.objects.get(organization=second)
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    assert (
        client.delete(
            f"/api/v1/organizations/{first.id}/members/{membership.id}", **csrf_header(client)
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/v1/organizations/{second.id}/members/{membership.id}", **csrf_header(client)
        ).status_code
        == 422
    )


def test_openapi_and_admin_support_custom_user(client):
    schema = client.get("/api/v1/openapi.json")
    assert schema.status_code == 200
    assert "/api/v1/auth/register" in schema.json()["paths"]
    user = User.objects.create_superuser("admin@example.com", "Admin-password-123!")
    client.force_login(user)
    for path in [
        "/admin/",
        "/admin/accounts/user/",
        "/admin/accounts/user/add/",
        f"/admin/accounts/user/{user.id}/change/",
        "/admin/organizations/organization/",
    ]:
        response = client.get(path)
        assert response.status_code == 200, path


def test_health_and_readiness_are_separate(client):
    with patch(
        "quanthecy.operations.views.dependency_status",
        return_value={"postgres": False, "redis": True, "clickhouse": True},
    ):
        assert client.get("/health").status_code == 200
        response = client.get("/ready")
        assert response.status_code == 503
        assert not json.loads(response.content)["dependencies"]["postgres"]
