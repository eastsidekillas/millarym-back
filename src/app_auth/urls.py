from django.urls import path

from .views import LoginAPIView, LogoutAPIView, MeAPIView, PasswordChangeAPIView, TokenRefreshAPIView

urlpatterns = [
    path("users/login/", LoginAPIView.as_view(), name="login"),
    path("users/logout/", LogoutAPIView.as_view(), name="logout"),
    path("users/me/", MeAPIView.as_view(), name="me"),
    path("users/password/", PasswordChangeAPIView.as_view(), name="password-change"),
    path("token/refresh/", TokenRefreshAPIView.as_view(), name="token-refresh"),
]
