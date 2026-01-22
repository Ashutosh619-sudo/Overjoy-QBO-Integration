"""
Django settings for QBO Ingestion Service.

Design Decision: Environment-based configuration
- All sensitive data from environment variables
- SQLite default for local development
- Can swap to PostgreSQL for production
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Build paths inside the project
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key secret in production!
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'django-insecure-dev-key-change-in-production')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DEBUG', 'True').lower() == 'true'

ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')


# Application definition
INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.auth',
    'rest_framework',
    'apps.qbo_ingestion',
]

# Minimal middleware for API application
MIDDLEWARE = [
    'django.middleware.common.CommonMiddleware',
]

# Django REST Framework configuration
REST_FRAMEWORK = {
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'DEFAULT_PARSER_CLASSES': [
        'rest_framework.parsers.JSONParser',
    ],
    'EXCEPTION_HANDLER': 'apps.qbo_ingestion.utils.custom_exception_handler',
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 100,
}

ROOT_URLCONF = 'qbo_service.urls'

WSGI_APPLICATION = 'qbo_service.wsgi.application'


# =============================================================================
# Database Configuration
# =============================================================================
# Design Decision: SQLite for simplicity
# Trade-off: No concurrent writes, but perfect for local sync service
# For production, set DATABASE_URL to PostgreSQL connection string

DATABASE_URL = os.getenv('DATABASE_URL')

if DATABASE_URL:
    # Production: Use PostgreSQL
    import dj_database_url
    DATABASES = {
        'default': dj_database_url.parse(DATABASE_URL)
    }
else:
    # Development: Use SQLite
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / os.getenv('DATABASE_PATH', 'qbo_data.db'),
        }
    }


# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = False
USE_TZ = True

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# =============================================================================
# QuickBooks Online Configuration
# =============================================================================

QBO_CLIENT_ID = os.getenv('QBO_CLIENT_ID')
QBO_CLIENT_SECRET = os.getenv('QBO_CLIENT_SECRET')
QBO_REDIRECT_URI = os.getenv('QBO_REDIRECT_URI', 'urn:ietf:wg:oauth:2.0:oob')
QBO_ENVIRONMENT = os.getenv('QBO_ENVIRONMENT', 'sandbox')

# OAuth URLs (Intuit's standard endpoints)
QBO_TOKEN_URL = 'https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer'
QBO_REVOKE_URL = 'https://developer.api.intuit.com/v2/oauth2/tokens/revoke'

# API Configuration
QBO_SANDBOX_BASE_URL = 'https://sandbox-quickbooks.api.intuit.com/v3/company'
QBO_PRODUCTION_BASE_URL = 'https://quickbooks.api.intuit.com/v3/company'
QBO_MINOR_VERSION = '75'


# =============================================================================
# Sync Configuration
# =============================================================================

# Polling interval in seconds (default: 5 minutes)
SYNC_POLL_INTERVAL = int(os.getenv('SYNC_POLL_INTERVAL', '300'))

# Maximum records per API request (QBO limit is 1000)
SYNC_PAGE_SIZE = int(os.getenv('SYNC_PAGE_SIZE', '1000'))

# Number of retries for failed API calls
SYNC_MAX_RETRIES = int(os.getenv('SYNC_MAX_RETRIES', '3'))

# Delay between retries (exponential backoff base in seconds)
SYNC_RETRY_DELAY = int(os.getenv('SYNC_RETRY_DELAY', '5'))

# Token refresh buffer (refresh before expiry, in seconds)
TOKEN_REFRESH_BUFFER = int(os.getenv('TOKEN_REFRESH_BUFFER', '300'))


# =============================================================================
# Logging Configuration
# =============================================================================

LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{asctime} - {name} - {levelname} - {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': LOG_LEVEL,
    },
    'loggers': {
        'apps.qbo_ingestion': {
            'handlers': ['console'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
        'urllib3': {
            'level': 'WARNING',
        },
    },
}
