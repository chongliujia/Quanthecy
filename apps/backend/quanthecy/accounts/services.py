from django.contrib.auth.password_validation import validate_password
from django.db import transaction

from quanthecy.organizations.models import Organization
from quanthecy.organizations.services import create_organization

from .models import User


@transaction.atomic
def register_user(*, email: str, password: str) -> User:
    candidate = User(email=User.objects.normalize_email(email))
    validate_password(password, user=candidate)
    user = User.objects.create_user(email=email, password=password)
    create_organization(owner=user, name="Personal Workspace", kind=Organization.Kind.PERSONAL)
    return user
