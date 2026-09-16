from urllib.parse import urlsplit
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from quanthecy.accounts.models import User
from quanthecy.organizations.models import Organization
from quanthecy.organizations.policies import require_org_role

from .catalog import DEFAULT_ENDPOINTS
from .models import AgentRun, ModelConfiguration
from .schemas import ConfigurationInput, ConfigurationOut


def cipher() -> Fernet:
    try:
        return Fernet(settings.AGENT_ENCRYPTION_KEY.encode())
    except (ValueError, TypeError) as exc:
        raise ValidationError("The platform encryption key is not configured correctly.") from exc


def encryption_available() -> bool:
    try:
        cipher()
        return True
    except ValidationError:
        return False


def endpoint(value: str, provider: str) -> str:
    value = value.rstrip("/")
    parsed = urlsplit(value)
    if (
        value != value.strip()
        or parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or any(char.isspace() for char in value)
        or value not in settings.AGENT_ALLOWED_ENDPOINTS
    ):
        raise ValidationError("This API base URL is not an allowed model connection.")
    if provider == "openai" and value != "https://api.openai.com/v1":
        raise ValidationError("Choose OpenAI-compatible for a custom endpoint.")
    return value


def validate_model_target(base_url: str, model: str) -> None:
    if base_url == "https://api.openai.com/v1" and model.lower().startswith(
        ("deepseek", "qwen", "kimi", "claude", "gemini")
    ):
        raise ValidationError(
            "This model is not served by the OpenAI endpoint. Choose its provider and API base URL."
        )


def decrypt_key(config: ModelConfiguration) -> str:
    if not config.encrypted_api_key:
        return ""
    try:
        return cipher().decrypt(config.encrypted_api_key.encode()).decode()
    except (InvalidToken, UnicodeError) as exc:
        raise ValidationError(
            "The saved API key cannot be decrypted. Replace it in settings."
        ) from exc


def configuration_value(config: ModelConfiguration) -> ConfigurationOut:
    return ConfigurationOut(
        revision=config.revision,
        provider=config.provider,
        base_url=config.base_url,
        model=config.model,
        has_api_key=bool(config.encrypted_api_key),
        encryption_available=encryption_available(),
        enabled=config.enabled,
        daily_run_limit=config.daily_run_limit,
        max_output_tokens=config.max_output_tokens,
        allowed_endpoints=settings.AGENT_ALLOWED_ENDPOINTS,
    )


def get_configuration(actor: User, organization_id: UUID) -> ConfigurationOut:
    require_org_role(actor, organization_id, {"OWNER"})
    config = ModelConfiguration.objects.filter(organization_id=organization_id).first()
    return configuration_value(config or ModelConfiguration(organization_id=organization_id))


@transaction.atomic
def save_configuration(
    actor: User, organization_id: UUID, payload: ConfigurationInput
) -> ConfigurationOut:
    require_org_role(actor, organization_id, {"OWNER"})
    Organization.objects.select_for_update().get(pk=organization_id)
    require_org_role(actor, organization_id, {"OWNER"})
    config, _ = ModelConfiguration.objects.get_or_create(organization_id=organization_id)
    if payload.revision != config.revision:
        raise ValidationError("Settings changed in another session. Reload before saving.")
    target = endpoint(payload.base_url, payload.provider)
    validate_model_target(target, payload.model.strip())
    secret = payload.api_key.get_secret_value() if payload.api_key is not None else ""
    if len(secret) > 4096 or any(c in secret for c in "\r\n"):
        raise ValidationError("Invalid API key format.")
    if secret and payload.clear_api_key:
        raise ValidationError("Choose either replacing or removing the API key.")
    if (
        target != config.base_url
        and config.encrypted_api_key
        and not (secret or payload.clear_api_key)
    ):
        raise ValidationError("Replace or remove the saved API key when changing its endpoint.")
    if secret:
        config.encrypted_api_key = cipher().encrypt(secret.encode()).decode()
    elif payload.clear_api_key:
        config.encrypted_api_key = ""
    config.provider = payload.provider
    config.base_url = target
    config.model = payload.model.strip()
    config.enabled = payload.enabled
    config.daily_run_limit = payload.daily_run_limit
    config.max_output_tokens = payload.max_output_tokens
    if config.enabled and not config.model:
        raise ValidationError("A model ID is required before enabling research.")
    if (
        config.enabled
        and (config.provider in {"openai", "anthropic"} or target in DEFAULT_ENDPOINTS)
        and not config.encrypted_api_key
    ):
        raise ValidationError("An API key is required for this provider.")
    config.revision += 1
    config.updated_by = actor
    config.save()
    AgentRun.objects.filter(
        organization_id=organization_id, state__in=["PENDING", "RUNNING"]
    ).update(
        state="CANCELLED",
        stage="cancelled",
        error_code="configuration_changed",
        finished_at=timezone.now(),
    )
    return configuration_value(config)
