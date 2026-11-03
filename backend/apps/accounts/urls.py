"""
URL Configuration for Accounts Domain.
College Online Examination System.
"""

from django.urls import path

from apps.accounts.views import (
    AdminTestView,
    CurrentUserView,
    FacultyTestView,
    LoginView,
    LogoutView,
    StudentTestView,
)

app_name = 'accounts'

urlpatterns = [
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('user/', CurrentUserView.as_view(), name='current-user'),
    # RBAC verification endpoints
    path('test/admin-only/', AdminTestView.as_view(), name='test-admin-only'),
    path('test/faculty-only/', FacultyTestView.as_view(), name='test-faculty-only'),
    path('test/student-only/', StudentTestView.as_view(), name='test-student-only'),
]
