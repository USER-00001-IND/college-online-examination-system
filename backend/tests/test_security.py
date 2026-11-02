"""
Tests for production security baseline and HTTP security headers.
"""

import importlib
import os
from unittest import mock
from django.test import SimpleTestCase


class ProductionSecurityBaselineTests(SimpleTestCase):
    """Verifies that production configuration enforces all required security headers and flags."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.valid_prod_env = {
            'SECRET_KEY': 'a-valid-production-secret-key-with-sufficient-entropy-12345',
            'ALLOWED_HOSTS': 'exam.college.edu',
            'DB_NAME': 'prod_exam_db',
            'DB_USER': 'prod_exam_user',
            'DB_PASSWORD': 'strong_production_password_value',
            'DB_HOST': 'db-cluster.internal',
            'DB_PORT': '3306',
            'CORS_ALLOWED_ORIGINS': 'https://exam.college.edu',
            'CSRF_TRUSTED_ORIGINS': 'https://exam.college.edu',
            'SECURE_SSL_REDIRECT': 'True',
        }

    def test_production_security_flags(self):
        """Verify production security headers, cookie flags, and HSTS settings."""
        with mock.patch.dict(os.environ, self.valid_prod_env, clear=False):
            prod = importlib.import_module('config.settings.production')
            importlib.reload(prod)

            self.assertFalse(prod.DEBUG)
            self.assertTrue(prod.SECURE_BROWSER_XSS_FILTER)
            self.assertTrue(prod.SECURE_CONTENT_TYPE_NOSNIFF)
            self.assertEqual(prod.X_FRAME_OPTIONS, 'DENY')
            self.assertTrue(prod.SECURE_SSL_REDIRECT)
            self.assertTrue(prod.SESSION_COOKIE_SECURE)
            self.assertTrue(prod.CSRF_COOKIE_SECURE)
            self.assertTrue(prod.SESSION_COOKIE_HTTPONLY)
            self.assertEqual(prod.SESSION_COOKIE_SAMESITE, 'Lax')
            self.assertEqual(prod.CSRF_COOKIE_SAMESITE, 'Lax')
            self.assertEqual(prod.SECURE_HSTS_SECONDS, 31536000)
            self.assertTrue(prod.SECURE_HSTS_INCLUDE_SUBDOMAINS)
            self.assertTrue(prod.SECURE_HSTS_PRELOAD)

    def test_production_renderers_exclude_browsable_api(self):
        """Verify BrowsableAPIRenderer is omitted in production to avoid schema/API probing."""
        with mock.patch.dict(os.environ, self.valid_prod_env, clear=False):
            prod = importlib.import_module('config.settings.production')
            importlib.reload(prod)

            renderer_classes = prod.REST_FRAMEWORK['DEFAULT_RENDERER_CLASSES']
            self.assertIn('rest_framework.renderers.JSONRenderer', renderer_classes)
            self.assertNotIn('rest_framework.renderers.BrowsableAPIRenderer', renderer_classes)

    def test_production_disallows_timestamp_fallback(self):
        """Verify Option B WSGI timestamp fallback is forbidden in production."""
        with mock.patch.dict(os.environ, self.valid_prod_env, clear=False):
            prod = importlib.import_module('config.settings.production')
            importlib.reload(prod)

            self.assertFalse(prod.ALLOW_WSGI_TIMESTAMP_FALLBACK)
