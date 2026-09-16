from typing import Any

from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

ROLES = {
    "Quanthecy data viewer": [
        "operations.view_collection_status",
        "operations.view_raw_payloads",
        "operations.view_rawpayloaddeletion",
        "markets.view_researchtopic",
        "markets.view_collectiontarget",
        "markets.view_market",
        "markets.view_event",
        "markets.view_outcome",
        "markets.view_ingestioncheckpoint",
    ],
    "Quanthecy data administrator": [
        "markets.view_researchtopic",
        "markets.add_researchtopic",
        "markets.change_researchtopic",
        "markets.view_collectiontarget",
        "markets.add_collectiontarget",
        "markets.change_collectiontarget",
        "operations.view_collection_status",
        "operations.view_raw_payloads",
        "operations.purge_raw_payloads",
        "operations.view_rawpayloaddeletion",
        "operations.view_platformauditlog",
    ],
    "Quanthecy user support": [
        "accounts.view_user",
        "accounts.change_user",
        "organizations.view_organization",
        "organizations.view_organizationmembership",
        "operations.view_platformauditlog",
    ],
}


class Command(BaseCommand):
    help = "Create or reset standard operator groups. Does not grant staff access or assign users."

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        for name, keys in ROLES.items():
            permissions = []
            for key in keys:
                app, codename = key.split(".")
                try:
                    permissions.append(
                        Permission.objects.get(content_type__app_label=app, codename=codename)
                    )
                except Permission.DoesNotExist as exc:
                    raise CommandError(f"Missing {key}; run migrations first.") from exc
            group, _ = Group.objects.get_or_create(name=name)
            group.permissions.set(permissions)
            self.stdout.write(f"Configured {name}")
