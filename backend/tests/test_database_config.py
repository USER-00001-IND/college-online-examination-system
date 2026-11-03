"""
Tests for database configuration schema and credential safety.
"""

import importlib
import os
from unittest import mock
from django.conf import settings
from django.test import SimpleTestCase
import environ

from config.settings.base import get_mysql_db_config


class DatabaseConfigurationTests(SimpleTestCase):
    """Verifies MySQL 8.x configuration specifications and credential leak prevention."""

    def test_default_auto_field_is_bigautofield(self):
        """Verify DEFAULT_AUTO_FIELD uses signed 64-bit integer BigAutoField."""
        self.assertEqual(settings.DEFAULT_AUTO_FIELD, 'django.db.models.BigAutoField')

    def test_mysql_configuration_structure(self):
        """Verify get_mysql_db_config generates compliant MySQL 8.x InnoDB settings."""
        dummy_env = environ.Env()
        with mock.patch.dict(os.environ, {
            'DB_NAME': 'test_exam_db',
            'DB_USER': 'test_app_user',
            'DB_PASSWORD': 'super_secret_password',
            'DB_HOST': 'db.internal',
            'DB_PORT': '3306',
        }):
            config = get_mysql_db_config(dummy_env)
            default_db = config['default']

            self.assertEqual(default_db['ENGINE'], 'django.db.backends.mysql')
            self.assertEqual(default_db['NAME'], 'test_exam_db')
            self.assertEqual(default_db['USER'], 'test_app_user')
            self.assertEqual(default_db['HOST'], 'db.internal')
            self.assertEqual(default_db['PORT'], '3306')
            self.assertEqual(default_db['OPTIONS']['charset'], 'utf8mb4')

            init_cmd = default_db['OPTIONS']['init_command']
            self.assertIn('STRICT_TRANS_TABLES', init_cmd)
            self.assertIn('ONLY_FULL_GROUP_BY', init_cmd)
            self.assertIn('default_storage_engine=INNODB', init_cmd)

    def test_production_database_config_enforces_mysql(self):
        """Verify production environment strictly enforces MySQL engine."""
        env_vars = {
            'SECRET_KEY': 'a-valid-production-secret-key-with-sufficient-entropy-12345',
            'ALLOWED_HOSTS': 'exam.college.edu',
            'DB_NAME': 'prod_exam_db',
            'DB_USER': 'prod_exam_user',
            'DB_PASSWORD': 'strong_production_password_value',
            'DB_HOST': 'db-cluster.internal',
            'DB_PORT': '3306',
            'REDIS_URL': 'redis://127.0.0.1:6379/1',
        }
        with mock.patch.dict(os.environ, env_vars, clear=False):
            prod = importlib.import_module('config.settings.production')
            importlib.reload(prod)

            self.assertEqual(prod.DATABASES['default']['ENGINE'], 'django.db.backends.mysql')
            self.assertNotEqual(prod.DATABASES['default']['ENGINE'], 'django.db.backends.sqlite3')
