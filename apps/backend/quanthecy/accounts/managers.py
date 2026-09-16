from typing import TYPE_CHECKING, Any

from django.contrib.auth.base_user import BaseUserManager
from django.core.validators import validate_email


class UserManager(BaseUserManager["User"]):
    use_in_migrations = True

    @classmethod
    def normalize_email(cls, email: str | None) -> str:
        return super().normalize_email(email).strip().lower()

    def get_by_natural_key(self, username: str | None) -> "User":
        return self.get(email__iexact=self.normalize_email(username))

    def create_user(self, email: str, password: str | None = None, **extra_fields: Any) -> "User":
        email = self.normalize_email(email)
        if not email:
            raise ValueError("Email is required")
        validate_email(email)
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(
        self, email: str, password: str | None = None, **extra_fields: Any
    ) -> "User":
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        if any(
            extra_fields[field] is not True for field in ("is_staff", "is_superuser", "is_active")
        ):
            raise ValueError("Superuser must be active with is_staff=True and is_superuser=True")
        if not password:
            raise ValueError("Superuser requires a password")
        return self.create_user(email, password, **extra_fields)


if TYPE_CHECKING:
    from .models import User
