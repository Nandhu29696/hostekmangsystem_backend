# views.py
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView
from account.serializers import UserRegistrationSerializer, UserLoginSerializer, UserProfileSerializer, UserChangePasswordSerializer, OTPVerifySerializer, OTPSendSerializer, ForgotPasswordSerializer, ResetPasswordWithOTPSerializer
from django.contrib.auth import authenticate
from account.renderers import UserRenderer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import IsAuthenticated 
from django.contrib.auth import get_user_model
from django.db.models import Q

User = get_user_model()
# Generate Token manually
def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token)
    }

class UserRegistrationView(APIView):
    renderer_classes = [UserRenderer]
    def post(self, request, format=None):
        serializer = UserRegistrationSerializer(data=request.data)
        if serializer.is_valid(raise_exception=True):
            user = serializer.save()
            token = get_tokens_for_user(user)
            return Response({"message": "Registration successful. "}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
class UserLoginView(APIView):
    renderer_classes = [UserRenderer]

    def post(self, request, format=None):
        serializer = UserLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data.get('email')
        password = serializer.validated_data.get('password')

        try:
            user = User.objects.get(email=email)
            # user = User.objects.get( Q(email__iexact=email) | Q(phone_number=email)  )
        except User.DoesNotExist:
            return Response(
                {'errors': {'non_field_error': ['Email or Password is not valid']}},
                status=status.HTTP_404_NOT_FOUND
            )

        # 🔒 CHECK ACTIVATION BEFORE AUTHENTICATION
        if not user.is_active:
            return Response(
                {"error": "Account not activated. Verify OTP."},
                status=status.HTTP_403_FORBIDDEN
            )

        # 🔐 NOW authenticate
        user = authenticate(email=email, password=password)
        if user is None:
            return Response(
                {'errors': {'non_field_error': ['Email or Password is not valid']}},
                status=status.HTTP_404_NOT_FOUND
            )

        token = get_tokens_for_user(user)
        return Response({
            'token': token,
            'userID': user.id,
            'role': user.role.name,
            'msg': 'Login success'
        }, status=status.HTTP_200_OK)

class UserProfileView(APIView):
    renderer_classes = [UserRenderer]
    permission_classes = [IsAuthenticated]
    def get(self, request, format=None):
        serializer = UserProfileSerializer(request.user)
        return Response(serializer.data ,status=status.HTTP_200_OK)
    
class UserChangePasswordView(APIView):
    renderer_classes = [UserRenderer]
    permission_classes = [IsAuthenticated]
    
    def post(self, request, format=None):
        """
        Change password endpoint
        
        Request Body:
        {
            "old_password": "current_password",
            "new_password": "new_password123",
            "confirm_password": "new_password123"
        }
        """
        serializer = UserChangePasswordSerializer(data=request.data, context={'user': request.user})
        if serializer.is_valid(raise_exception=True):
            return Response(
                {'message': 'Password changed successfully!'},
                status=status.HTTP_200_OK
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class VerifyOTPView(APIView):
    def post(self, request):
        serializer = OTPVerifySerializer(data=request.data)
        if serializer.is_valid():
            return Response({"message": "OTP verified successfully. Your account is now active."}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
class SendOTPView(APIView):
    def post(self, request, *args, **kwargs):
        serializer = OTPSendSerializer(data=request.data)
        if serializer.is_valid():
            try:
                response_data = serializer.create_otp_and_send()
                return Response(response_data, status=status.HTTP_200_OK)
            except Exception as e:
                return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ForgotPasswordView(APIView):
    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response({"msg": "OTP sent to email"})

class ResetPasswordView(APIView):
    def post(self, request):
        serializer = ResetPasswordWithOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response({"msg": "Password reset successful"})
