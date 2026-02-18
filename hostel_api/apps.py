from django.apps import AppConfig


class HostelApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'hostel_api'

    def ready(self):
        import hostel_api.signals
