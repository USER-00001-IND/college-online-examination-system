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
if 'django-insecure' in SECRET_KEY or len(SECRET_KEY) < 50:
    raise ImproperlyConfigured(
        "CRITICAL SECURITY CONFIGURATION ERROR: Production SECRET_KEY is insecure. "
        "Must be a random string of at least 50 characters."
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

# --------------------------------------------------------------------------
# Reverse Proxy SSL Header Trust Boundary & TLS Termination (Finding B)
# --------------------------------------------------------------------------
# Django relies on SECURE_PROXY_SSL_HEADER to determine request.is_secure() when
# TLS terminates at the reverse proxy (Nginx).
#
# INTERACTION OF PROXY TLS TERMINATION, REDIRECTS, COOKIES, AND CSRF:
# When TLS is terminated at Nginx, Nginx communicates with Gunicorn/Django via plain HTTP
# (typically over a Unix domain socket or loopback network).
# 1. If SECURE_SSL_REDIRECT is True, Django redirects plain HTTP requests to HTTPS unless
#    request.is_secure() returns True.
# 2. If SECURE_PROXY_SSL_HEADER is enabled, Django trusts the specified header
#    ('HTTP_X_FORWARDED_PROTO', 'https') to determine request.is_secure().
# 3. If Gunicorn/Django can be accessed directly by clients (bypassing Nginx), an attacker can
#    spoof 'X-Forwarded-Proto: https' over plain HTTP, tricking Django into believing the
#    channel is encrypted and bypassing HTTPS enforcement.
# 4. Insecure channel spoofing also weakens CSRF protection and Secure cookie guarantees.
#
# FAIL-CLOSED DEFAULT & MANDATORY REVERSE-PROXY ISOLATION:
# Forwarded-header trust is disabled by default (SECURE_PROXY_SSL_HEADER = None).
# It may be enabled ONLY when the operator explicitly acknowledges the deployment boundary
# by setting TRUST_PROXY_SSL_HEADER=True in production .env, confirming that:
#   - Nginx is the sole ingress boundary and unconditionally overwrites
#     'proxy_set_header X-Forwarded-Proto $scheme;' (never forwards client-supplied values).
#   - Direct client access to Django/Gunicorn is mechanically blocked (via Unix domain socket
#     e.g., /run/gunicorn.sock mode 0660, or strict network firewall/namespace rules).
# Validate TRUST_PROXY_SSL_HEADER raw input if set
raw_trust_proxy = env('TRUST_PROXY_SSL_HEADER', default='False')
if isinstance(raw_trust_proxy, str) and raw_trust_proxy.strip().lower() not in (
    'true', 'false', '1', '0', 'yes', 'no', 't', 'f'
):
    raise ImproperlyConfigured(
        f"CRITICAL SECURITY CONFIGURATION ERROR: Invalid TRUST_PROXY_SSL_HEADER value '{raw_trust_proxy}'. "
        "Must be an explicit boolean string ('True' or 'False')."
    )

TRUST_PROXY_SSL_HEADER = env.bool('TRUST_PROXY_SSL_HEADER', default=False)
if TRUST_PROXY_SSL_HEADER:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
else:
    SECURE_PROXY_SSL_HEADER = None

# HTTPS and Cookie Security
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
