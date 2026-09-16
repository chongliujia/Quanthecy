from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm
from django.http import HttpRequest

from .models import AuthIdentity, User


class AccountCreationForm(AdminUserCreationForm):
    class Meta:
        model = User
        fields = ("email",)

    def clean_email(self) -> str:
        email = User.objects.normalize_email(self.cleaned_data["email"])
        return email


class AccountChangeForm(UserChangeForm):
    class Meta:
        model = User
        fields = ("email", "is_staff", "is_superuser", "groups", "user_permissions")


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    add_form = AccountCreationForm
    form = AccountChangeForm
    list_display = ("email", "is_active", "is_staff", "date_joined")
    ordering = ("email",)
    search_fields = ("email",)
    readonly_fields = ("id", "email", "email_verified_at", "is_active", "date_joined", "last_login")
    fieldsets = (
        (None, {"fields": ("id", "email", "password", "email_verified_at")}),
        (
            "Platform permissions",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("Dates", {"fields": ("date_joined", "last_login")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),)

    def get_readonly_fields(self, request: HttpRequest, obj: User | None = None) -> tuple[str, ...]:
        return self.readonly_fields if obj else ()

    def has_delete_permission(self, request: HttpRequest, obj: User | None = None) -> bool:
        return False


@admin.register(AuthIdentity)
class AuthIdentityAdmin(admin.ModelAdmin):
    list_display = ("provider", "subject", "user", "created_at")
    readonly_fields = ("id", "user", "provider", "subject", "email", "created_at", "updated_at")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: AuthIdentity | None = None) -> bool:
        return False
