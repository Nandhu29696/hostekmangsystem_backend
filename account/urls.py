# urls.py
from django.urls import path, include
from account.views import UserRegistrationView, UserLoginView, UserProfileView, VerifyOTPView, SendOTPView, ForgotPasswordView, ResetPasswordView, UserChangePasswordView
from rest_framework_simplejwt.views import TokenRefreshView

urlpatterns = [
    path('register', UserRegistrationView.as_view(), name='register'),
    path('verify-otp', VerifyOTPView.as_view(), name='verify-otp'),
    path('login', UserLoginView.as_view(), name='login'),
    path('forgot-password', ForgotPasswordView.as_view()),
    path('reset-password', ResetPasswordView.as_view()),
    path('profile', UserProfileView.as_view(), name='profile'),
    path('change-password', UserChangePasswordView.as_view(), name='change-password'),
    path('token/refresh', TokenRefreshView.as_view(), name='token_refresh'),
]