from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """Custom user model so auth can be extended later (e.g. multi-user support)
    without the painful mid-project AUTH_USER_MODEL migration."""
