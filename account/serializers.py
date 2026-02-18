# serializers.py
from xml.dom import ValidationErr
from rest_framework import serializers
from account.models import User, UserOTPVerification, Role
from django.utils.encoding import smart_str, force_bytes, DjangoUnicodeDecodeError
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from account.utils import Util
import random
from django.utils import timezone
from datetime import timedelta

class UserRegistrationSerializer(serializers.ModelSerializer):
    password2 = serializers.CharField(style={'input_type':'password'}, write_only=True)
    role = serializers.CharField(write_only=True)
    class Meta:
        model = User
        fields=['email', 'name', 'password', 'password2', 'tc', 'role']
        extra_kwargs={
        'password':{'write_only':True}
        }

    # Validating Password and Confirm Password while Registration
    def validate(self, attrs):
        password = attrs.get('password')
        password2 = attrs.get('password2')
        if password != password2:
            raise serializers.ValidationError("Password and Confirm Password doesn't match")
        return attrs

    def create(self, validated_data):
        role_name = validated_data.pop('role')
        role = Role.objects.get(name=role_name)
        # Create the User object
        user = User.objects.create_user(
            email=validated_data['email'],
            name=validated_data['name'],
            password=validated_data['password'],
            tc=validated_data['tc']
        )
        user.role = role
        # user.is_active = True
        user.save()

        # Generate OTP
        otp = random.randint(100000, 999999)

        # Create OTP verification record
        otp_verification = UserOTPVerification.objects.create(
            user=user,
            otp=otp,
            expires_at=timezone.now() + timedelta(minutes=5)  # OTP expiration set to 5 minutes
        )
        
        #Send Email
        body = f'Your OTP is {otp}. It will expire in 5 minutes.'
        data = {
            'subject':'Your OTP for Signup Verification',
            'body':body,
            'to_email':user.email
        }
        Util.send_email(data)

        return user

class UserLoginSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(max_length=255)
    class Meta:
        model = User
        fields = ['email', 'password']
    
class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id','email','name']
        
class UserChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(max_length=255, style={'input_type':'password'}, write_only=True)
    new_password = serializers.CharField(max_length=255, style={'input_type':'password'}, write_only=True)
    confirm_password = serializers.CharField(max_length=255, style={'input_type':'password'}, write_only=True)
    
    class Meta:
        fields = ['old_password', 'new_password', 'confirm_password']
    
    def validate(self, attrs):
        old_password = attrs.get('old_password')
        new_password = attrs.get('new_password')
        confirm_password = attrs.get('confirm_password')
        user = self.context.get('user')
        
        # Check if old password is correct
        if not user.check_password(old_password):
            raise serializers.ValidationError({"old_password": "Old password is not correct"})
        
        # Check if new password and confirm password match
        if new_password != confirm_password:
            raise serializers.ValidationError({"confirm_password": "New Password and Confirm Password doesn't match"})
        
        # Check if new password is same as old password
        if old_password == new_password:
            raise serializers.ValidationError({"new_password": "New password cannot be same as old password"})
        
        # Validate password strength (minimum 8 characters)
        if len(new_password) < 8:
            raise serializers.ValidationError({"new_password": "Password must be at least 8 characters long"})
        
        # Set the new password
        user.set_password(new_password) 
        user.save()
        return attrs

class OTPVerifySerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.IntegerField()

    def validate(self, data):
        email = data.get('email')
        otp = data.get('otp')

        # Retrieve the user
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise serializers.ValidationError("Invalid email address.")

        # Retrieve the most recent OTP record for this user
        try:
            otp_record = UserOTPVerification.objects.filter(user=user, is_verified=False).latest('created_at')
        except UserOTPVerification.DoesNotExist:
            raise serializers.ValidationError("No OTP record found for this user.")

        # Check if OTP is expired
        if otp_record.is_expired():
            raise serializers.ValidationError("The OTP has expired. Please request a new one.")

        # Check if the provided OTP is correct
        if otp_record.otp != otp:
            raise serializers.ValidationError("Invalid OTP.")

        # OTP is valid, mark it as verified
        otp_record.is_verified = True
        otp_record.save()

        # Activate the user's account
        user.is_active = True
        user.save()

        return user

class OTPSendSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        # Check if the email exists in the User table
        try:
            user = User.objects.get(email=value)
        except User.DoesNotExist:
            raise serializers.ValidationError("This email is not registered with us.")
        return value

    def create_otp_and_send(self):
        email = self.validated_data['email']
        user = User.objects.get(email=email)  # Fetch user for email content personalization

        # Generate OTP
        otp = random.randint(100000, 999999)

        # Create OTP verification record
        otp_verification = UserOTPVerification.objects.create(
            user=user,
            otp=otp,
            expires_at=timezone.now() + timedelta(minutes=5)  # OTP expiration set to 5 minutes
        )
         
        #Send Email
        body = f'Your OTP is {otp}. It will expire in 5 minutes.'
        data = {
            'subject':'Your OTP for Signup Verification',
            'body':body,
            'to_email':user.email
        }
        try:
            Util.send_email(data)
        except Exception as e:
            raise serializers.ValidationError(f"Failed to send OTP: {str(e)}")
        return {"msg": "OTP sent successfully"}
    
class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate(self, data):
        user = User.objects.get(email=data['email'])

        otp = random.randint(100000, 999999)
        UserOTPVerification.objects.create(
            user=user,
            otp=otp,
            expires_at=timezone.now() + timedelta(minutes=5)
        )

        Util.send_email({
            'subject': 'Password Reset OTP',
            'body': f'Your OTP is {otp}',
            'to_email': user.email
        })
        return data

class ResetPasswordWithOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.IntegerField()
    password = serializers.CharField()
    password2 = serializers.CharField()

    def validate(self, data):
        if data['password'] != data['password2']:
            raise serializers.ValidationError("Passwords do not match")

        user = User.objects.get(email=data['email'])
        otp_record = UserOTPVerification.objects.filter(
            user=user, otp=data['otp'], is_verified=False
        ).latest('created_at')

        if otp_record.is_expired():
            raise serializers.ValidationError("OTP expired")

        otp_record.is_verified = True
        otp_record.save()

        user.set_password(data['password'])
        user.save()
        return data
