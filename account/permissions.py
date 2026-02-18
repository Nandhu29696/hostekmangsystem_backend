# account/permissions.py
from rest_framework.permissions import BasePermission
from account.models import Role

class IsAdminOrWarden(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return (
            user.is_authenticated
            and user.role
            and user.role.name in [Role.ADMIN, Role.WARDEN]
        )

class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return (
            user.is_authenticated
            and user.role
            and user.role.name == Role.ADMIN
        )