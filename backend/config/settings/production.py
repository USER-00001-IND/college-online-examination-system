"""
Production settings for College Online Examination System.
Enforces strict security baselines, fail-closed secrets validation, and production headers.
"""

from django.core.exceptions import ImproperlyConfigured
from .base import *

# Production must never run in debug mode
DEBUG = False
ENVIRONMENT_NAME = 'production'

# Secret Key Validation
SECRET_KEY = env('SECRET_KEY', default=None)
if not SECRET_KEY:
    raise ImproperlyConfigured(
        "CRITICAL SECURITY CONFIGURATION ERROR: SECRET_KEY must be provided via environment variables."
    )
if 'django-insecure' in SECRET_KEY or len(SECRET_KEY) < 32:
    raise ImproperlyConfigured(
        "CRITICAL SECURITY CONFIGURATION ERROR: Production SECRET_KEY is insecure. "
        "Must be a random string of at least 32 characters."
    )

# Host Header Validation
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=[])
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "CRITICAL SECURITY CONFIGURATION ERROR: ALLOWED_HOSTS must be explicitly defined in production."
    )
if '*' in ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "CRITICAL SECURITY CONFIGURATION ERROR: Wildcard '*' is forbidden in production ALLOWED_HOSTS."
    )

# Strict MySQL Database Configuration Validation
DB_NAME = env('DB_NAME', default=None)
DB_USER = env('DB_USER', default=None)
DB_PASSWORD = env('DB_PASSWORD', default=None)
DB_HOST = env('DB_HOST', default=None)
DB_PORT = str(env('DB_PORT', default='3306'))

if not (DB_NAME and DB_USER and DB_PASSWORD and DB_HOST):
    raise ImproperlyConfigured(
        "CRITICAL DATABASE CONFIGURATION ERROR: Production requires explicit MySQL environment variables: "
        "DB_NAME, DB_USER, DB_PASSWORD, DB_HOST."
    )

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': DB_NAME,
        'USER': DB_USER,
        'PASSWORD': DB_PASSWORD,
        'HOST': DB_HOST,
        'PORT': DB_PORT,
        'OPTIONS': {
            'charset': 'utf8mb4',
            'init_command': (
                "SET sql_mode='STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION,ONLY_FULL_GROUP_BY';"
                "SET default_storage_engine=INNODB;"
            ),
        },
    }
}

# Strict CORS and CSRF Configuration
CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS', default=[])
if '*' in CORS_ALLOWED_ORIGINS:
    raise ImproperlyConfigured(
        "CRITICAL SECURITY CONFIGURATION ERROR: Wildcard '*' is forbidden in production CORS_ALLOWED_ORIGINS."
    )
CORS_ALLOW_CREDENTIALS = True

CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[])

# HTTPS and Proxy Security
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', default=True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False  # Permit client SPA access to CSRF cookie for AJAX mutations
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'

# Security Headers
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_HSTS_SECONDS = 31536000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Option B Consistency Model — Reverse proxy ingress timestamping is mandatory
# Fallback to WSGI arrival timestamp is strictly prohibited in production
ALLOW_WSGI_TIMESTAMP_FALLBACK = False

# REST Framework production renderers (strictly JSON, no browsable API)
REST_FRAMEWORK['DEFAULT_RENDERER_CLASSES'] = [
    'rest_framework.renderers.JSONRenderer',
]

# JSON structured logging for log aggregator ingestion
LOGGING['handlers']['console']['formatter'] = 'json'
