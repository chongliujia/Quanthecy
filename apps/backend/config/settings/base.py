import os
from pathlib import Path

from quanthecy.agents.catalog import DEFAULT_ENDPOINTS

BASE_DIR = Path(__file__).resolve().parents[2]

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
DEBUG = False
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,backend").split(",")
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "quanthecy.accounts",
    "quanthecy.organizations",
    "quanthecy.operations",
    "quanthecy.markets",
    "quanthecy.research",
    "quanthecy.agents",
    "quanthecy.watchlists",
    "quanthecy.alerts",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "quanthecy.operations.console.AdminLanguageMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
ASGI_APPLICATION = "config.asgi.application"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "quanthecy" / "operations" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "quanthecy.operations.console.console_context",
            ]
        },
    }
]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "quanthecy"),
        "USER": os.environ.get("POSTGRES_USER", "quanthecy"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "quanthecy-dev-only"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 0,
        "OPTIONS": {"connect_timeout": 3},
    }
}
AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_TRUSTED_ORIGINS = [
    value for value in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if value
]
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CLICKHOUSE_URL = os.environ.get("CLICKHOUSE_URL", "http://localhost:8123")
NEWS_FEEDS_ENABLED = os.environ.get("NEWS_FEEDS_ENABLED", "true").lower() == "true"
NEWS_DOCUMENTS_ENABLED = os.environ.get("NEWS_DOCUMENTS_ENABLED", "true").lower() == "true"
NEWS_PROXY_URL = os.environ.get("NEWS_PROXY_URL", "")
AGENT_ENCRYPTION_KEY = os.environ.get("AGENT_ENCRYPTION_KEY", "")
AGENT_ALLOWED_ENDPOINTS = [
    value.strip().rstrip("/")
    for value in (os.environ.get("AGENT_ALLOWED_ENDPOINTS") or ",".join(DEFAULT_ENDPOINTS)).split(
        ","
    )
    if value.strip()
]
CLICKHOUSE_DATABASE = os.environ.get("CLICKHOUSE_DATABASE", "quanthecy")
CLICKHOUSE_USER = os.environ.get("CLICKHOUSE_USER", "quanthecy")
CLICKHOUSE_PASSWORD = os.environ.get("CLICKHOUSE_PASSWORD", "quanthecy-dev-only")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
