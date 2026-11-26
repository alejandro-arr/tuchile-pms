"""Configuración centralizada de Turismo TUCHILE PMS con Controles ISO/IEC 27001:2022.

Implementa:
- Patrón Creacional Singleton (`ConfiguracionSeguraSingleton`) con validación Fail-Fast (Control A.8.9).
- Separación estricta de entornos `ENVIRONMENT` ('production' vs 'development', Control A.8.31).
- Cero secretos hardcodeados en código fuente (Control A.8.28) y bitácora de auditoría (Control A.8.15).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from pms.security.constants import (
    DB_QUERY_TIMEOUT_SEGUNDOS,
    DIAS_RETENCION_LOGS_AUDITORIA,
    ENTORNOS_VALIDOS,
    LIMITE_INACTIVIDAD_SESION_SEGUNDOS,
    MIN_LONGITUD_PASSWORD,
)

BASE_DIR = Path(__file__).resolve().parent.parent


def _cargar_archivo_env(ruta_env: Path) -> None:
    """Carga variables desde un archivo .env local si existe (sin sobrescribir variables del sistema)."""
    if not ruta_env.exists():
        return
    for linea in ruta_env.read_text(encoding="utf-8").splitlines():
        texto = linea.strip()
        if not texto or texto.startswith("#") or "=" not in texto:
            continue
        clave, valor = texto.split("=", 1)
        os.environ.setdefault(clave.strip(), valor.strip().strip('"').strip("'"))


_cargar_archivo_env(BASE_DIR / ".env")


class ConfiguracionSeguraSingleton:
    """Patrón Creacional GoF: Singleton para configuración centralizada y validación Fail-Fast (ISO A.8.9 / A.8.31)."""

    _instancia: ConfiguracionSeguraSingleton | None = None

    def __new__(cls) -> ConfiguracionSeguraSingleton:
        if cls._instancia is None:
            cls._instancia = super().__new__(cls)
            cls._instancia._inicializar_y_validar()
        return cls._instancia

    def _inicializar_y_validar(self) -> None:
        self.environment: str = os.environ.get("ENVIRONMENT", "development").strip().lower()
        if self.environment not in ENTORNOS_VALIDOS:
            raise ImproperlyConfigured(
                f"Bloqueo Fail-Fast (ISO 27001 A.8.31): ENVIRONMENT='{self.environment}' no es válido."
            )

        self.secret_key: str = os.environ.get("DJANGO_SECRET_KEY", "").strip()
        self.encryption_key: str = os.environ.get("FIELD_ENCRYPTION_KEY_AES256", "").strip()

        if self.environment == "production" and (not self.secret_key or not self.encryption_key):
            raise ImproperlyConfigured(
                "Bloqueo Fail-Fast (ISO 27001 A.8.9 / A.8.28): Faltan variables críticas en producción."
            )

        if not self.secret_key:
            self.secret_key = os.environ.get(
                "FALLBACK_DEV_KEY", "dev-only-tuchile-pms-iso27001-key-no-prod"
            )
        if not self.encryption_key:
            self.encryption_key = "dev-only-aes256-tuchile-pms-key-2026"

        # Control A.8.12: Supresión total de stack traces en modo producción
        self.debug: bool = (
            os.environ.get("DJANGO_DEBUG", "True").lower() == "true"
            and self.environment != "production"
        )

    def obtener_config_bd(self) -> dict[str, Any]:
        """Retorna la configuración de Base de Datos aislando entornos (Control A.8.31) y timeout 5s (A.8.28)."""
        motor = os.environ.get("DB_ENGINE", "sqlite3").strip().lower()
        db_password = os.environ.get("DB_PASSWORD", "").strip()
        if motor in ("postgresql", "postgres", "supabase") and db_password:
            return {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": os.environ.get("DB_NAME", "postgres"),
                "USER": os.environ.get("DB_USER", "postgres.njcuxwxqimzjcqfbrryx"),
                "PASSWORD": db_password,
                "HOST": os.environ.get("DB_HOST", "aws-1-sa-east-1.pooler.supabase.com"),
                "PORT": os.environ.get("DB_PORT", "5432"),
                "CONN_MAX_AGE": 60,
                "OPTIONS": {
                    "sslmode": "require",
                    "connect_timeout": DB_QUERY_TIMEOUT_SEGUNDOS,
                },
            }
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
            "OPTIONS": {
                "timeout": DB_QUERY_TIMEOUT_SEGUNDOS,
            },
        }


CONFIG_SINGLETON = ConfiguracionSeguraSingleton()

ENVIRONMENT = CONFIG_SINGLETON.environment
SECRET_KEY = CONFIG_SINGLETON.secret_key
FIELD_ENCRYPTION_KEY_AES256 = CONFIG_SINGLETON.encryption_key
DEBUG = CONFIG_SINGLETON.debug

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost,.onrender.com,testserver").split(",")
    if h.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "pms",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "tuchile_config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "tuchile_config.wsgi.application"

DATABASES = {
    "default": CONFIG_SINGLETON.obtener_config_bd(),
}

# Control A.8.24: Hashing seguro de contraseñas con Bcrypt / PBKDF2 y largo mínimo 12 caracteres
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": MIN_LONGITUD_PASSWORD},
    },
]

# Control A.8.5: Expiración de sesión por inactividad en 1800 segundos (30 minutos)
SESSION_COOKIE_AGE = LIMITE_INACTIVIDAD_SESION_SEGUNDOS
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = ENVIRONMENT == "production"
CSRF_COOKIE_SECURE = ENVIRONMENT == "production"

LANGUAGE_CODE = "es-cl"
TIME_ZONE = "America/Santiago"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
CSRF_TRUSTED_ORIGINS = ["https://*.onrender.com"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Control A.8.15: Bitácora de auditoría con rotación diaria y retención de 365 días
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "iso_audit": {
            "format": "%(asctime)s | %(levelname)s | %(message)s",
        },
    },
    "handlers": {
        "audit_file": {
            "level": "INFO",
            "class": "logging.handlers.TimedRotatingFileHandler",
            "filename": BASE_DIR / "audit_security.log",
            "when": "D",
            "interval": 1,
            "backupCount": DIAS_RETENCION_LOGS_AUDITORIA,
            "formatter": "iso_audit",
            "encoding": "utf-8",
        },
    },
    "loggers": {
        "pms.audit": {
            "handlers": ["audit_file"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
