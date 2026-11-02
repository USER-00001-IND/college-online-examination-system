"""
Tests for missing or insecure mandatory environment variables in production.
"""

import importlib
import os
from unittest import mock
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase


class MissingEnvironmentVariablesTests(SimpleTestCase):
    """Verifies fail-closed behavior when mandatory production environment variables are absent."""

    def _get_base_valid_env(self):
        return {
            'SECRET_KEY': 'a-valid-production-secret-key-with-sufficient-entropy-12345',
            'ALLOWED_HOSTS': 'exam.college.edu',
            'DB_NAME': 'prod_exam_db',
            'DB_USER': 'prod_exam_user',
            'DB_PASSWORD': 'strong_production_password_value',
            'DB_HOST': 'db-cluster.internal',
            'DB_PORT': '3306',
        }

    def test_missing_secret_key_raises_error(self):
        """Verify production fails to load if SECRET_KEY is missing."""
        env_vars = self._get_base_valid_env()
        env_vars['SECRET_KEY'] = ''
        with mock.patch.dict(os.environ, env_vars, clear=False):
            with self.assertRaises(ImproperlyConfigured) as ctx:
                prod = importlib.import_module('config.settings.production')
                importlib.reload(prod)
            self.assertIn('SECRET_KEY', str(ctx.exception))

    def test_insecure_secret_key_raises_error(self):
        """Verify production fails if SECRET_KEY has insecure prefix or short length."""
        env_vars = self._get_base_valid_env()
        env_vars['SECRET_KEY'] = 'django-insecure-short'
        with mock.patch.dict(os.environ, env_vars, clear=False):
            with self.assertRaises(ImproperlyConfigured) as ctx:
                prod = importlib.import_module('config.settings.production')
                importlib.reload(prod)
            self.assertIn('SECRET_KEY is insecure', str(ctx.exception))

    def test_missing_allowed_hosts_raises_error(self):
        """Verify production fails if ALLOWED_HOSTS is empty."""
        env_vars = self._get_base_valid_env()
        env_vars['ALLOWED_HOSTS'] = ''
        with mock.patch.dict(os.environ, env_vars, clear=False):
            with self.assertRaises(ImproperlyConfigured) as ctx:
                prod = importlib.import_module('config.settings.production')
                importlib.reload(prod)
            self.assertIn('ALLOWED_HOSTS', str(ctx.exception))

    def test_wildcard_allowed_hosts_raises_error(self):
        """Verify production fails if ALLOWED_HOSTS contains '*'."""
        env_vars = self._get_base_valid_env()
        env_vars['ALLOWED_HOSTS'] = '*'
        with mock.patch.dict(os.environ, env_vars, clear=False):
            with self.assertRaises(ImproperlyConfigured) as ctx:
                prod = importlib.import_module('config.settings.production')
                importlib.reload(prod)
            self.assertIn("Wildcard '*' is forbidden", str(ctx.exception))

    def test_missing_database_variables_raises_error(self):
        """Verify production fails if DB_PASSWORD or DB_HOST is missing."""
        for missing_var in ['DB_NAME', 'DB_USER', 'DB_PASSWORD', 'DB_HOST']:
            env_vars = self._get_base_valid_env()
            env_vars[missing_var] = ''
            with mock.patch.dict(os.environ, env_vars, clear=False):
                with self.assertRaises(ImproperlyConfigured) as ctx:
                    prod = importlib.import_module('config.settings.production')
                    importlib.reload(prod)
                self.assertIn('CRITICAL DATABASE CONFIGURATION ERROR', str(ctx.exception))

    def test_wildcard_cors_raises_error(self):
        """Verify production fails if CORS_ALLOWED_ORIGINS contains '*'."""
        env_vars = self._get_base_valid_env()
        env_vars['CORS_ALLOWED_ORIGINS'] = '*'
        with mock.patch.dict(os.environ, env_vars, clear=False):
            with self.assertRaises(ImproperlyConfigured) as ctx:
                prod = importlib.import_module('config.settings.production')
                importlib.reload(prod)
            self.assertIn("Wildcard '*' is forbidden in production CORS", str(ctx.exception))
