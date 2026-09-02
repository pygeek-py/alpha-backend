class ProviderError(Exception):
    """Raised when an external data provider request fails: network error,
    non-2xx response, rate limit, or an unparseable payload. Distinct from a
    bug in our own code -- Celery tasks that call providers already retry on
    any exception, so this doesn't need its own retry logic, just a clear
    signal of where the failure came from.
    """
