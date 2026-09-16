from datetime import datetime
from typing import Literal
from uuid import UUID

from ninja import Schema
from pydantic import ConfigDict, Field

from quanthecy.accounts.models import User
from quanthecy.organizations.models import Organization, OrganizationMembership


class InputSchema(Schema):
    model_config = ConfigDict(extra="forbid")


class Credentials(InputSchema):
    email: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class CsrfToken(Schema):
    csrf_token: str


class UserOut(Schema):
    id: UUID
    email: str
    email_verified_at: datetime | None

    @classmethod
    def from_user(cls, user: User) -> "UserOut":
        return cls(id=user.id, email=user.email, email_verified_at=user.email_verified_at)


class OrganizationInput(InputSchema):
    name: str = Field(min_length=1, max_length=120)


class OrganizationOut(Schema):
    id: UUID
    name: str
    slug: str
    kind: str
    role: str

    @classmethod
    def from_organization(cls, organization: Organization, role: str) -> "OrganizationOut":
        return cls(
            id=organization.id,
            name=organization.name,
            slug=organization.slug,
            kind=organization.kind,
            role=role,
        )


class MembershipOut(Schema):
    id: UUID
    user_id: UUID
    email: str
    role: str

    @classmethod
    def from_membership(cls, membership: OrganizationMembership) -> "MembershipOut":
        return cls(
            id=membership.id,
            user_id=membership.user_id,
            email=membership.user.email,
            role=membership.role,
        )


class RoleInput(InputSchema):
    role: Literal["OWNER", "ADMIN", "MEMBER", "VIEWER"]


class Message(Schema):
    detail: str
