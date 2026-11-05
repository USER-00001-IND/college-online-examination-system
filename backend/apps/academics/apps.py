from django.apps import AppConfig


class AcademicsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.academics"
    verbose_name = "Academics"

    def ready(self):
        # Register Django system checks for institutional integrity
        # Strictly registers checks without executing database queries during ready()
        from . import checks
