"""
Views for authentication and user management.
"""

from rest_framework import generics, status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView

from apps.accounts.serializers import (
    UserSerializer,
    UserRegistrationSerializer,
    CustomTokenObtainPairSerializer,
    ChangePasswordSerializer,
    UpdateProfileSerializer,
)


class RegisterView(generics.CreateAPIView):
    """View for user registration."""

    permission_classes = [permissions.AllowAny]
    serializer_class = UserRegistrationSerializer

    def get_queryset(self):
        """Return user queryset."""
        from django.contrib.auth import get_user_model
        User = get_user_model()
        return User.objects.all()

    def create(self, request, *args, **kwargs):
        """Create a new user account."""
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            {
                "message": "User registered successfully",
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_201_CREATED,
        )


class CustomTokenObtainPairView(TokenObtainPairView):
    """Custom JWT token view with user information."""

    serializer_class = CustomTokenObtainPairSerializer


class UserProfileView(generics.RetrieveUpdateAPIView):
    """View for retrieving and updating user profile."""

    serializer_class = UpdateProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        """Return the current user."""
        return self.request.user

    def get_serializer_class(self):
        """Return appropriate serializer based on request method."""
        if self.request.method == "GET":
            return UserSerializer
        return UpdateProfileSerializer


class ChangePasswordView(generics.UpdateAPIView):
    """View for changing user password."""

    serializer_class = ChangePasswordSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        """Return the current user."""
        return self.request.user


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def user_me(request):
    """Get current user information."""
    serializer = UserSerializer(request.user)
    return Response(serializer.data)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def logout(request):
    """Logout current user."""
    try:
        refresh_token = request.data["refresh_token"]
        from rest_framework_simplejwt.tokens import RefreshToken

        token = RefreshToken(refresh_token)
        token.blacklist()
        return Response({"message": "Successfully logged out"}, status=status.HTTP_200_OK)
    except Exception:
        return Response({"error": "Invalid token"}, status=status.HTTP_400_BAD_REQUEST)
