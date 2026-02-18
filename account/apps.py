from django.apps import AppConfig


class AccountConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'account'
    
    def ready(self):
        from .models import Role
        for role in ['ADMIN', 'STUDENT', 'WARDEN']:
            Role.objects.get_or_create(name=role)

