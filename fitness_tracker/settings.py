"""
Django settings for fitness_tracker project.

Started with 'django-admin startproject' (Django 4.2); now runs on Django 5.2 LTS.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/5.2/ref/settings/
"""

import os
from pathlib import Path

from dotenv import load_dotenv

from fitness_tracker.env import env_list, env_origins

load_dotenv(Path(__file__).resolve().parent.parent / '.env')

# boto3 finds AWS credentials itself; the public client flows used here need none.
COGNITO_REGION = os.getenv('COGNITO_REGION')
COGNITO_USER_POOL_ID = os.getenv('COGNITO_USER_POOL_ID')
COGNITO_CLIENT_ID = os.getenv('COGNITO_CLIENT_ID')

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('SECRET_KEY', '')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DEBUG', 'false').lower() == 'true'
if not SECRET_KEY:
    if not DEBUG:
        raise RuntimeError('Set a private SECRET_KEY')
    from django.core.management.utils import get_random_secret_key
    SECRET_KEY = get_random_secret_key()

ALLOWED_HOSTS = env_list('ALLOWED_HOSTS', '127.0.0.1,localhost')


# Application definition

# Stateless API: accounts live in Cognito, so there is no admin, session or
# user table to serve.
INSTALLED_APPS = [
    'django.contrib.staticfiles',
    'graphene_django',
    'corsheaders',
    'accounts',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'fitness_tracker.urls'

CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = env_origins('CORS_ALLOWED_ORIGINS')

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
            ],
        },
    },
]

WSGI_APPLICATION = 'fitness_tracker.wsgi.application'


# No database: nothing is persisted locally.
DATABASES = {}


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = 'static/'

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

GRAPHQL_MAX_DEPTH = int(os.getenv('GRAPHQL_MAX_DEPTH', '5'))
# Schema introspection (and GraphiQL's explorer) follows DEBUG unless set explicitly.
GRAPHQL_INTROSPECTION = os.getenv('GRAPHQL_INTROSPECTION', str(DEBUG)).lower() == 'true'

GRAPHENE = {
    'SCHEMA': 'fitness_tracker.schema.schema',
}
