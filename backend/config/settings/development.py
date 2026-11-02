"""
Development settings for College Online Examination System.
"""

from .base import *

DEBUG = True
ENVIRONMENT_NAME = 'development'

# Development secret key with fallback (never used in production)
SECRET_KEY = env(
    'SECRET_KEY',
    default='django-insecure-dev-dummy-key-for-local-testing-only-gu-fyugp-2026',
)

ALLOWED_HOSTS = env.list(
    'ALLOWED_HOSTS',
    default=['localhost', '127.0.0.1', '[::1]'],
)

# Database Configuration
# Uses MySQL if DB_NAME or DATABASE_URL provided; otherwise falls back to local SQLite for frictionless local dev
if env('DB_NAME', default=None) or env('DATABASE_URL', default=None):
    DATABASES = get_mysql_db_config(env)
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'dev_fallback.sqlite3',
        }
    }

# Enable Browsable API in development
REST_FRAMEWORK['DEFAULT_RENDERER_CLASSES'] = [
    'rest_framework.renderers.JSONRenderer',
    'rest_framework.renderers.BrowsableAPIRenderer',
]

# CORS and CSRF configurations for local frontend development (Vite @ 5173, etc.)
CORS_ALLOWED_ORIGINS = env.list(
    'CORS_ALLOWED_ORIGINS',
    default=[
        'http://localhost:3000',
        'http://localhost:5173',
        'http://127.0.0.1:5173',
    ],
)
CORS_ALLOW_CREDENTIALS = True

CSRF_TRUSTED_ORIGINS = env.list(
    'CSRF_TRUSTED_ORIGINS',
    default=[
        'http://localhost:3000',
        'http://localhost:5173',
        'http://127.0.0.1:5173',
    ],
)

# Ingress timestamp WSGI fallback permitted ONLY in development/testing (Option B Architecture)
ALLOW_WSGI_TIMESTAMP_FALLBACK = True
