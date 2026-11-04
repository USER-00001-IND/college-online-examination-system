"""
Base settings for College Online Examination System.
Targeting Gauhati University FYUGP Examination System Architecture.
"""

from pathlib import Path
import os
import environ

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent
REPO_DIR = BASE_DIR.parent

# Initialize django-environ
env = environ.Env()

# Read .env file from BASE_DIR or REPO_DIR if it exists
env_file = BASE_DIR / '.env'
if not env_file.exists():
    env_file = REPO_DIR / '.env'
if env_file.exists():
    environ.Env.read_env(str(env_file))

# Application definition
APP_VERSION = '1.0.0'
SYSTEM_NAME = 'College Online Examination System'
ENVIRONMENT_NAME = env.str('ENVIRONMENT_NAME', default='development')

INSTALLED_APPS = [
    # Django Core Applications
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-Party Libraries
    'rest_framework',
    'corsheaders',

    # Local Domain Apps (Chunk 02 Architecture)
    'apps.core.apps.CoreConfig',
    'apps.accounts.apps.AccountsConfig',
    'apps.academics.apps.AcademicsConfig',
    'apps.students.apps.StudentsConfig',
    'apps.faculty.apps.FacultyConfig',
    'apps.enrollments.apps.EnrollmentsConfig',
    'apps.examinations.apps.ExaminationsConfig',
    'apps.questions.apps.QuestionsConfig',
    'apps.attempts.apps.AttemptsConfig',
    'apps.evidence.apps.EvidenceConfig',
    'apps.uploads.apps.UploadsConfig',
    'apps.evaluations.apps.EvaluationsConfig',
    'apps.operations.apps.OperationsConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

# Reverse Proxy SSL Header Trust Boundary (Disabled by default across all environments)
# Enabled only in production when TRUST_PROXY_SSL_HEADER=True and Nginx isolation is verified
SECURE_PROXY_SSL_HEADER = None

# Reverse Proxy Client IP Trust Boundary (Independent of SSL Header Trust)
# When False (default), client IP is strictly taken from validated REMOTE_ADDR
# When True, X-Forwarded-For first hop is validated via Python ipaddress module
TRUST_PROXY_CLIENT_IP = env.bool('TRUST_PROXY_CLIENT_IP', default=False)

# Centralized CSRF Failure Handler
CSRF_FAILURE_VIEW = 'apps.core.views.csrf_failure_view'

# Cache Backend Configuration (Used for authentication rate limiting and session storage)
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'college-cache-default',
    }
}

# Authentication Throttling & Brute-Force Rate Limiting Settings
AUTH_THROTTLE_IP_LIMIT = env.int('AUTH_THROTTLE_IP_LIMIT', default=15)
AUTH_THROTTLE_IP_WINDOW = env.int('AUTH_THROTTLE_IP_WINDOW', default=300)  # 5 minutes
AUTH_THROTTLE_TARGET_LIMIT = env.int('AUTH_THROTTLE_TARGET_LIMIT', default=5)
AUTH_THROTTLE_TARGET_WINDOW = env.int('AUTH_THROTTLE_TARGET_WINDOW', default=300)  # 5 minutes

# Signed 64-bit integer primary keys (consistent with MySQL 8.x schema design)
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Custom Authentication User Model (Chunk 04 Identity Foundation)
AUTH_USER_MODEL = 'accounts.User'

# Password Validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {
            'min_length': 8,
        },
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Authentication Backends (supports username or email login)
AUTHENTICATION_BACKENDS = [
    'apps.accounts.backends.EmailOrUsernameModelBackend',
    'django.contrib.auth.backends.ModelBackend',
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True

# Static and Media Files
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Private Upload Storage (Handwritten answer scripts stored outside webroot)
PRIVATE_UPLOAD_ROOT = BASE_DIR / 'private_uploads'

# Django REST Framework Configuration
REST_FRAMEWORK = {
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'DEFAULT_PARSER_CLASSES': [
        'rest_framework.parsers.JSONParser',
        'rest_framework.parsers.MultiPartParser',
        'rest_framework.parsers.FormParser',
    ],
    'EXCEPTION_HANDLER': 'apps.core.exceptions.custom_exception_handler',
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'apps.accounts.authentication.ExamSessionAuthentication',
    ],
}

# Institutional Policy Configuration Gates (Section 9 Baseline)
# Strictly unconfigured until formally reviewed and approved by college authorities
EXAM_PIN_DELIVERY_METHOD = None  # UNCONFIGURED ('EMAIL', 'SMS', 'IN_PERSON')
EXAM_EVIDENCE_KEY_RETENTION_PERIOD = None  # UNCONFIGURED (Days integer)
INSTITUTIONAL_CONFIG_APPROVED = False

# Email Configuration
EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.smtp.EmailBackend')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'noreply@college.edu')

# MySQL 8.x Connection Helper
def get_mysql_db_config(environ_obj):
    """Generates standard MySQL 8.x InnoDB database connection dictionary."""
    return {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': environ_obj('DB_NAME', default='college_exam_db'),
            'USER': environ_obj('DB_USER', default='college_app'),
            'PASSWORD': environ_obj('DB_PASSWORD', default=''),
            'HOST': environ_obj('DB_HOST', default='127.0.0.1'),
            'PORT': str(environ_obj('DB_PORT', default='3306')),
            'OPTIONS': {
                'charset': 'utf8mb4',
                'init_command': (
                    "SET sql_mode='STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION,ONLY_FULL_GROUP_BY';"
                    "SET default_storage_engine=INNODB;"
                ),
            },
        }
    }

# Logging Configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'filters': {
        'sensitive_data_filter': {
            '()': 'apps.core.logging.SensitiveDataFilter',
        },
    },
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} [{name}:{lineno}] {message}',
            'style': '{',
        },
        'json': {
            '()': 'apps.core.logging.JSONLogFormatter',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'filters': ['sensitive_data_filter'],
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'college': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
