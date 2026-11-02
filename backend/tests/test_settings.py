"""
Tests for Django configuration loading across environments.
"""

import importlib
import os
from unittest import mock
from django.conf import settings
from django.test import TestCase


class SettingsLoadingTests(TestCase):
    """Verifies that settings modules load cleanly and contain expected configurations."""

    def test_test_settings_loaded(self):
        """Verify the active test settings configuration."""
        self.assertEqual(settings.ENVIRONMENT_NAME, 'test')
        self.assertFalse(settings.DEBUG)
        self.assertEqual(settings.DEFAULT_AUTO_FIELD, 'django.db.models.BigAutoField')

    def test_installed_domain_apps(self):
        """Verify all 10 modular apps from Chunk 02 domain design are installed."""
        expected_apps = [
            'apps.core.apps.CoreConfig',
            'apps.accounts.apps.AccountsConfig',
            'apps.academics.apps.AcademicsConfig',
            'apps.examinations.apps.ExaminationsConfig',
            'apps.questions.apps.QuestionsConfig',
            'apps.attempts.apps.AttemptsConfig',
            'apps.evidence.apps.EvidenceConfig',
            'apps.uploads.apps.UploadsConfig',
            'apps.evaluations.apps.EvaluationsConfig',
            'apps.operations.apps.OperationsConfig',
        ]
        for app in expected_apps:
            self.assertIn(app, settings.INSTALLED_APPS)

    def test_unconfigured_institutional_policy_gates(self):
        """Verify institutional policy variables are strictly unconfigured initially."""
        self.assertIsNone(settings.EXAM_PIN_DELIVERY_METHOD)
        self.assertIsNone(settings.EXAM_EVIDENCE_KEY_RETENTION_PERIOD)
        self.assertFalse(settings.INSTULTIONAL_CONFIG_APPROVED if hasattr(settings, 'INSTULTIONAL_CONFIG_APPROVED') else settings.INSTITUTIONAL_CONFIG_APPROVED)

    def test_development_settings_loading(self):
        """Verify development settings load with appropriate development defaults."""
        dev_settings = importlib.import_module('config.settings.development')
        self.assertTrue(dev_settings.DEBUG)
        self.assertEqual(dev_settings.ENVIRONMENT_NAME, 'development')
        self.assertTrue(dev_settings.ALLOW_WSGI_TIMESTAMP_FALLBACK)
        self.assertIn('localhost', dev_settings.ALLOWED_HOSTS)

    def test_production_settings_loading_with_valid_env(self):
        """Verify production settings load cleanly when valid environment variables are present."""
        env_vars = {
            'SECRET_KEY': 'a-valid-production-secret-key-with-sufficient-entropy-12345',
            'ALLOWED_HOSTS': 'exam.college.edu,api.college.edu',
            'DB_NAME': 'prod_exam_db',
            'DB_USER': 'prod_exam_user',
            'DB_PASSWORD': 'strong_production_password_value',
            'DB_HOST': 'db-cluster.internal',
            'DB_PORT': '3306',
            'CORS_ALLOWED_ORIGINS': 'https://exam.college.edu',
            'CSRF_TRUSTED_ORIGINS': 'https://exam.college.edu',
            'SECURE_SSL_REDIRECT': 'True',
        }
        with mock.patch.dict(os.environ, env_vars, clear=False):
            prod_settings = importlib.import_module('config.settings.production')
            importlib.reload(prod_settings)
            self.assertFalse(prod_settings.DEBUG)
            self.assertEqual(prod_settings.ENVIRONMENT_NAME, 'production')
            self.assertFalse(prod_settings.ALLOW_WSGI_TIMESTAMP_FALLBACK)
            self.assertEqual(prod_settings.DATABASES['default']['ENGINE'], 'django.db.backends.mysql')
            self.assertEqual(prod_settings.DATABASES['default']['NAME'], 'prod_exam_db')
            self.assertIn('exam.college.edu', prod_settings.ALLOWED_HOSTS)
