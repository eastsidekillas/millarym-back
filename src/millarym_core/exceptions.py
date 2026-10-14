from rest_framework.views import exception_handler


def core_exception_handler(exc, context):
    """Ошибки валидации отдаём единообразно: {"errors": {...}}."""
    response = exception_handler(exc, context)
    if response is not None and exc.__class__.__name__ == "ValidationError":
        response.data = {"errors": response.data}
    return response
