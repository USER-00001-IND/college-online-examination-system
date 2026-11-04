"""
Test settings for College Online Examination System.
Optimized for deterministic, fast in-memory test execution.
"""

from .base import *

DEBUG = False
ENVIRONMENT_NAME = 'test'

# Deterministic test secret key
SECRET_KEY = 'test-secret-key-strictly-for-automated-testing-runs-only-do-not-use-elsewhere'

ALLOWED_HOSTS = ['*']

# In-memory SQLite database for isolated unit test execution
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# Accelerated password hasher for unit tests (with PBKDF2 available for verification)
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
]

# Clean test execution output
LOGGING['handlers']['console']['level'] = 'CRITICAL'
LOGGING['root']['level'] = 'CRITICAL'
LOGGING['loggers']['django']['level'] = 'CRITICAL'
LOGGING['loggers']['college']['level'] = 'CRITICAL'

# In-memory email backend for automated testing
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

CORS_ALLOWED_ORIGINS = ['http://localhost:3000']
CSRF_TRUSTED_ORIGINS = ['http://localhost:3000']

# Allow WSGI timestamp fallback in test suites
ALLOW_WSGI_TIMESTAMP_FALLBACK = True
