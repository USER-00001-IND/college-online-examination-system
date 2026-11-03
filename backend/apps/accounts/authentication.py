"""
Session Authentication for College Online Examination System.
Extends DRF SessionAuthentication to return RFC 7235-compliant 401 Unauthorized
for anonymous requests to protected endpoints.
"""

from rest_framework.authentication import SessionAuthentication


class ExamSessionAuthentication(SessionAuthentication):
    """
    Session authentication that provides an authenticate_header.
    Ensures DRF returns 401 UNAUTHORIZED (rather than 403 FORBIDDEN) when an unauthenticated
    client accesses protected views, while preserving full CSRF enforcement on state mutations.
    """

    def authenticate_header(self, request):
        return 'Session realm="api"'
