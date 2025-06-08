# create_admin.py
import os
import django
from django.contrib.auth import get_user_model
from django.core.management.base import CommandError

# Ensure Django settings are loaded
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gallery_config.settings')
django.setup()

User = get_user_model()

# Fetch superuser details from environment variables
# Provide defaults if you want, but it's better to require them for production
SUPERUSER_EMAIL = os.environ.get('DJANGO_SUPERUSER_EMAIL')
SUPERUSER_USERNAME = os.environ.get('DJANGO_SUPERUSER_USERNAME')
SUPERUSER_PASSWORD = os.environ.get('DJANGO_SUPERUSER_PASSWORD')

if not all([SUPERUSER_EMAIL, SUPERUSER_USERNAME, SUPERUSER_PASSWORD]):
    print("ERROR: DJANGO_SUPERUSER_EMAIL, DJANGO_SUPERUSER_USERNAME, and DJANGO_SUPERUSER_PASSWORD environment variables must be set.")
    # Exit with an error code if you want the build to fail here
    # import sys
    # sys.exit(1)
else:
    if not User.objects.filter(username=SUPERUSER_USERNAME).exists():
        print(f"Creating superuser: {SUPERUSER_USERNAME} ({SUPERUSER_EMAIL})")
        try:
            User.objects.create_superuser(SUPERUSER_USERNAME, SUPERUSER_EMAIL, SUPERUSER_PASSWORD)
            print("Superuser created successfully.")
        except Exception as e:
            print(f"Error creating superuser: {e}")
            # import sys
            # sys.exit(1) # Optionally fail the build if creation fails for other reasons
    else:
        print(f"Superuser '{SUPERUSER_USERNAME}' already exists. Ensuring password is up to date.")
        try:
            user = User.objects.get(username=SUPERUSER_USERNAME)
            user.set_password(SUPERUSER_PASSWORD) # Update password
            if SUPERUSER_EMAIL and user.email != SUPERUSER_EMAIL: # Update email if changed
                user.email = SUPERUSER_EMAIL
            user.save()
            print(f"Superuser '{SUPERUSER_USERNAME}' details ensured/updated.")
        except User.DoesNotExist:
             print(f"Superuser '{SUPERUSER_USERNAME}' was reported to exist but not found. This is unexpected.")
        except Exception as e:
            print(f"Error updating superuser '{SUPERUSER_USERNAME}': {e}")