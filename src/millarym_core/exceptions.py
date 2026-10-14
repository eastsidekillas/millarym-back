from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

from app_production.errors import ActionError, NoRight


def core_exception_handler(exc, context):
    if isinstance(exc, NoRight):
        return Response({"detail": exc.message}, status=status.HTTP_403_FORBIDDEN)
    if isinstance(exc, ActionError):
        return Response({"detail": exc.message}, status=status.HTTP_400_BAD_REQUEST)
    response = exception_handler(exc, context)
    if response is not None and exc.__class__.__name__ == "ValidationError":
        response.data = {"errors": response.data}
    return response
