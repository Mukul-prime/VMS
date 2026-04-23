"""
Django settings for IronHeart project.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "django-insecure-+6mkavww#95$9+86$t)%aj5e1f(_5ph#$-x1%-^*6o4e-y(m$i"

DEBUG = True

ALLOWED_HOSTS = ["*"]  # ✅ Fixed: localhost allow karo


# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

EXTERNAL_APPS = [
    "UserData",
    "rest_framework",
    "Objects",
    "Camera",
    "corsheaders",
]
INSTALLED_APPS += EXTERNAL_APPS


MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",       # ✅ Sabse pehle rehna chahiye
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    # ❌ REMOVED: XFrameOptionsMiddleware — ye iframe/stream block karta tha
]

ROOT_URLCONF = "IronHeart.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "IronHeart.wsgi.application"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Database
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": "VMSD",
        "USER": "root",
        "PASSWORD": "Monu@12345",
        "HOST": "localhost",
        "PORT": "3306",
    }
}

MEDIA_URL = "/media/"
MEDIA_ROOT = os.path.join(BASE_DIR, "media")

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = "static/"

# ✅ CORS — properly configured for streaming
CORS_ALLOW_ALL_ORIGINS = True          # Dev ke liye sab allow

CORS_ALLOW_CREDENTIALS = True

CORS_ALLOW_HEADERS = [
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "dnt",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
    "cache-control",               # ✅ Streaming ke liye zaroori
    "pragma",                      # ✅ Streaming ke liye zaroori
]

CORS_ALLOW_METHODS = [
    "DELETE",
    "GET",
    "OPTIONS",
    "PATCH",
    "POST",
    "PUT",
]

# ✅ Streaming response ke liye — Django response buffer disable
DATA_UPLOAD_MAX_MEMORY_SIZE = None
FILE_UPLOAD_MAX_MEMORY_SIZE = None