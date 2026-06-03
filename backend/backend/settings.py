import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR.parent / ".env", override=False)

DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-only-insecure-secret-key"
    else:
        raise RuntimeError("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is not 1.")


def _csv_env(name: str, default: str = "") -> list[str]:
    raw = os.environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


ALLOWED_HOSTS = _csv_env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,backend")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "search",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "backend.observability.RequestIdMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "backend.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "backend.wsgi.application"
ASGI_APPLICATION = "backend.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS: list[dict[str, str]] = []

LANGUAGE_CODE = "ja"
TIME_ZONE = "Asia/Tokyo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

OPENSEARCH_HOST = os.environ.get("OPENSEARCH_HOST", "http://opensearch:9200")
OPENSEARCH_INDEX = os.environ.get("OPENSEARCH_INDEX", "jlaw-current")
OPENSEARCH_SCHEMA_VERSION = int(os.environ.get("OPENSEARCH_SCHEMA_VERSION", "2"))
OPENSEARCH_NUMBER_OF_SHARDS = int(os.environ.get("OPENSEARCH_NUMBER_OF_SHARDS", "4"))
OPENSEARCH_TIMEOUT_SECONDS = int(os.environ.get("OPENSEARCH_TIMEOUT_SECONDS", "30"))
OPENSEARCH_REQUEST_TIMEOUT_SECONDS = int(os.environ.get("OPENSEARCH_REQUEST_TIMEOUT_SECONDS", "10"))
OPENSEARCH_BULK_TIMEOUT_SECONDS = int(os.environ.get("OPENSEARCH_BULK_TIMEOUT_SECONDS", "60"))
OPENSEARCH_BULK_MAX_BYTES = int(os.environ.get("OPENSEARCH_BULK_MAX_BYTES", str(40 * 1024 * 1024)))
REINDEX_TOKEN = os.environ.get("REINDEX_TOKEN", "")

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ]
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {
            "format": "%(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "plain",
        },
    },
    "loggers": {
        "jlaw.requests": {
            "handlers": ["console"],
            "level": os.environ.get("JLAW_REQUEST_LOG_LEVEL", "INFO"),
            "propagate": False,
        },
    },
}
