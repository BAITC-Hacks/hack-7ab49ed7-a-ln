class ApiError(Exception):
    status_code = 500
    code = "internal_error"
    retryable = False

    def __init__(self, message: str, details: list[dict] | None = None, retryable: bool | None = None):
        super().__init__(message)
        self.message = message
        self.details = details
        if retryable is not None:
            self.retryable = retryable


class Unauthorized(ApiError):
    status_code = 401
    code = "unauthorized"


class NotFound(ApiError):
    status_code = 404
    code = "not_found"


class Conflict(ApiError):
    status_code = 409
    code = "conflict"


class RunNotReady(ApiError):
    status_code = 409
    code = "run_not_ready"
    retryable = True


class ValidationFailed(ApiError):
    status_code = 400
    code = "validation_error"


class PayloadTooLarge(ApiError):
    status_code = 413
    code = "payload_too_large"


class RateLimited(ApiError):
    status_code = 429
    code = "rate_limited"
    retryable = True


class ServiceUnavailable(ApiError):
    status_code = 503
    code = "service_unavailable"
    retryable = True
