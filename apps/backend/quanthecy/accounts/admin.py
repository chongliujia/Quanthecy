from typing import Any

from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from quanthecy.api.auth import current_user
from quanthecy.operations.console import label, tr
from quanthecy.operations.policies import require_operator

from .administration import set_account_active
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

    def clean(self) -> dict[str, Any]:
        values = super().clean() or {}
        if values.get("is_superuser", self.instance.is_superuser) and not values.get(
            "is_staff", self.instance.is_staff
        ):
            raise ValidationError("A platform superuser must also have staff access.")
        return values


class AccountStatusForm(forms.Form):
    active = forms.TypedChoiceField(
        label=label("Account status", "账号状态"),
        choices=[("true", label("Active", "启用")), ("false", label("Disabled", "停用"))],
        coerce=lambda value: value == "true",
    )
    reason = forms.CharField(
        label=label("Reason", "操作原因"), max_length=500, widget=forms.Textarea(attrs={"rows": 3})
    )


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    add_form = AccountCreationForm
    form = AccountChangeForm
    list_display = ("account_email", "account_status", "access_level", "joined_at", "status_link")
    list_per_page = 30
    search_help_text = label("Search by email address", "按邮箱地址搜索用户")
    list_filter = ("is_active", "is_staff", "is_superuser")
    ordering = ("email",)
    search_fields = ("email",)
    readonly_fields = ("id", "email", "email_verified_at", "is_active", "date_joined", "last_login")
    fieldsets = (
        (None, {"fields": ("id", "email", "password", "email_verified_at")}),
        (
            label("Platform permissions", "平台权限"),
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        (label("Dates", "时间记录"), {"fields": ("date_joined", "last_login")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),)

    def get_list_display(self, request: HttpRequest) -> tuple[str, ...]:
        if not self.has_change_permission(request):
            return self.list_display[:-1]
        return self.list_display

    def get_readonly_fields(self, request: HttpRequest, obj: User | None = None) -> tuple[str, ...]:
        fields: tuple[str, ...] = self.readonly_fields if obj else ()
        if not request.user.is_superuser:
            fields += ("is_staff", "is_superuser", "groups", "user_permissions")
        elif obj and obj.pk == request.user.pk:
            fields += ("is_staff", "is_superuser")
        return fields

    def has_change_permission(self, request: HttpRequest, obj: User | None = None) -> bool:
        if obj and (obj.is_staff or obj.is_superuser) and not request.user.is_superuser:
            return False
        return super().has_change_permission(request, obj)

    @admin.display(description=label("Email address", "邮箱地址"), ordering="email")
    def account_email(self, obj: User) -> str:
        return obj.email

    @admin.display(description=label("Status", "状态"), ordering="is_active")
    def account_status(self, obj: User) -> str:
        return format_html(
            '<span class="console-badge {}"><i></i>{}</span>',
            "good" if obj.is_active else "neutral",
            tr("Active", "启用") if obj.is_active else tr("Disabled", "停用"),
        )

    @admin.display(description=label("Platform access", "平台身份"), ordering="is_staff")
    def access_level(self, obj: User) -> str:
        if obj.is_superuser:
            return tr("Administrator", "超级管理员")
        return tr("Operator", "操作员") if obj.is_staff else tr("User", "普通用户")

    @admin.display(description=label("Joined · UTC", "注册时间 · UTC"), ordering="date_joined")
    def joined_at(self, obj: User) -> str:
        return obj.date_joined.strftime("%Y-%m-%d %H:%M")

    @admin.display(description=label("Action", "操作"))
    def status_link(self, obj: User) -> str:
        return format_html(
            '<a href="{}">{} →</a>',
            reverse("admin:accounts_user_status", args=[obj.pk]),
            tr("Manage status", "管理状态"),
        )

    def get_urls(self) -> list[Any]:
        return [
            path(
                "<uuid:user_id>/status/",
                self.admin_site.admin_view(self.status_view),
                name="accounts_user_status",
            )
        ] + super().get_urls()

    def status_view(self, request: HttpRequest, user_id: Any) -> HttpResponse:
        actor = current_user(request)
        require_operator(actor, "accounts.change_user")
        user = get_object_or_404(User, pk=user_id)
        if not self.has_change_permission(request, user):
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied("Only a superuser can manage platform operators.")
        form = AccountStatusForm(
            request.POST if request.method == "POST" else None,
            initial={"active": "true" if user.is_active else "false"},
        )
        if request.method == "POST" and form.is_valid():
            try:
                set_account_active(
                    actor=actor,
                    user_id=user.pk,
                    active=form.cleaned_data["active"],
                    reason=form.cleaned_data["reason"],
                )
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                messages.success(
                    request,
                    tr(
                        "Account status saved. The operation was recorded.",
                        "账号状态已更新，操作已记录。",
                    ),
                )
                return redirect("admin:accounts_user_change", user.pk)
        return TemplateResponse(
            request,
            "admin/quanthecy/account_status.html",
            {
                **self.admin_site.each_context(request),
                "title": tr("Manage account status", "管理账号状态"),
                "target_user": user,
                "form": form,
            },
        )

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
