# gallery_config/settings.py
import os
import dj_database_url # Add this
from pathlib import Path # BASE_DIR is likely already using this

BASE_DIR = Path(__file__).resolve().parent.parent

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-c(ylr$sumh*+9n0*%-1&eoo7b=)_$fsj7%l+*qm72tzlgu5$4z'

# --- DEBUG ---
# Set to False in production!
DEBUG = os.environ.get('DJANGO_DEBUG', '') != 'False' # Defaults to True locally unless DJANGO_DEBUG='False'

# --- ALLOWED_HOSTS ---
# For Render, your app will have a .onrender.com domain.
# We'll get this from an environment variable set by Render or one you set.
ALLOWED_HOSTS_STRING = os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost 127.0.0.1 your-app-name.onrender.com')
ALLOWED_HOSTS = ALLOWED_HOSTS_STRING.split(' ') if ALLOWED_HOSTS_STRING else []
# If your app name on Render will be 'art-gallery-demo', then ALLOWED_HOSTS could look like:
# ALLOWED_HOSTS = ['art-gallery-demo.onrender.com', 'localhost', '127.0.0.1'] # Add others if needed

# --- CSRF_TRUSTED_ORIGINS ---
# Important for POST requests on HTTPS
CSRF_TRUSTED_ORIGINS_STRING = os.environ.get('DJANGO_CSRF_TRUSTED_ORIGINS', 'http://localhost:8000 http://127.0.0.1:8000 https://your-app-name.onrender.com')
CSRF_TRUSTED_ORIGINS = CSRF_TRUSTED_ORIGINS_STRING.split(' ') if CSRF_TRUSTED_ORIGINS_STRING else []
# Example: CSRF_TRUSTED_ORIGINS = ['https://art-gallery-demo.onrender.com']


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'whitenoise.runserver_nostatic', # Add whitenoise for static files (before staticfiles)
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'artworks',
    # Add other apps if you created them (e.g., 'users', 'core')
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware', # Whitenoise Middleware (place high, after SecurityMiddleware)
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'gallery_config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
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

WSGI_APPLICATION = 'gallery_config.wsgi.application'


# --- Database ---
# https://docs.djangoproject.com/en/5.0/ref/settings/#databases
# Use dj_database_url to parse the DATABASE_URL environment variable
# Render will provide DATABASE_URL for its PostgreSQL service
DATABASES = {
    'default': dj_database_url.config(
        default=f'sqlite:///{BASE_DIR / "db.sqlite3"}', # Fallback to SQLite for local dev if DATABASE_URL not set
        conn_max_age=600,
        conn_health_checks=True, # Recommended for Render
    )
}
# If DATABASE_URL is set and has sslmode, ensure it's respected or set ssl_require appropriately
# For Render free tier Postgres, SSL is usually required. dj_database_url might handle this if the URL specifies sslmode.
# If you need to force SSL for Render's DB:
if 'DATABASE_URL' in os.environ:
     DATABASES['default']['OPTIONS'] = {'sslmode': 'require'}
# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# --- Static files (CSS, JavaScript, Images) ---
STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles') # Directory where collectstatic will gather files
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static')] # Your project-wide static files
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage' # For Whitenoise

# --- Media files (User-uploaded content like dekonts) ---
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')


DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_REDIRECT_URL = '/gallery/'
LOGOUT_REDIRECT_URL = '/gallery/'
# LOGIN_URL = '/accounts/login/' # Default, but can be explicit