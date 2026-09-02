import logging
import time
import uuid

logger = logging.getLogger("alpha.request")


class RequestLoggingMiddleware:
    """Logs one line per request with a correlation id, method, path, status, and duration."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = uuid.uuid4().hex[:12]
        started = time.monotonic()
        response = self.get_response(request)
        duration_ms = round((time.monotonic() - started) * 1000, 1)
        response["X-Request-ID"] = request.request_id
        logger.info(
            "%s %s %s %sms [%s]",
            request.method,
            request.get_full_path(),
            response.status_code,
            duration_ms,
            request.request_id,
        )
        return response
