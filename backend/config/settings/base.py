"""
Base settings for College Online Examination System.
Targeting Gauhati University FYUGP Examination System Architecture.
"""

from pathlib import Path
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

# Signed 64-bit integer primary keys (consistent with MySQL 8.x schema design)
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

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
        'rest_framework.authentication.SessionAuthentication',
    ],
}

# Institutional Policy Configuration Gates (Section 9 Baseline)
# Strictly unconfigured until formally reviewed and approved by college authorities
EXAM_PIN_DELIVERY_METHOD = None  # UNCONFIGURED ('EMAIL', 'SMS', 'IN_PERSON')
EXAM_EVIDENCE_KEY_RETENTION_PERIOD = None  # UNCONFIGURED (Days integer)
INSTITUTIONAL_CONFIG_APPROVED = False

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
