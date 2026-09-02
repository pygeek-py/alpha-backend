import logging

from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger("alpha.errors")


def api_exception_handler(exc, context):
    """Wraps DRF's default handler so every error response has one consistent
    shape and every unhandled exception is logged with request context."""
    response = drf_exception_handler(exc, context)

    if response is None:
        request = context.get("request")
        logger.exception(
            "Unhandled exception on %s %s",
            getattr(request, "method", "?"),
            getattr(request, "path", "?"),
        )
        return None

    detail = response.data
    if isinstance(detail, dict) and "detail" in detail and len(detail) == 1:
        message = detail["detail"]
    else:
        message = detail

    response.data = {
        "error": {
            "status_code": response.status_code,
            "message": message,
        }
    }
    return response
