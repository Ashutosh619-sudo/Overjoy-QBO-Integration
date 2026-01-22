"""
QuickBooks Online SDK Exceptions.
"""


class QBOSDKError(Exception):
    """Base exception for QBO SDK errors."""
    
    def __init__(self, message: str, response: str = None):
        super().__init__(message)
        self.message = message
        self.response = response
    
    def __str__(self):
        return self.message


class AuthenticationError(QBOSDKError):
    """Authentication/authorization error."""
    pass


class InvalidTokenError(AuthenticationError):
    """Invalid or expired access token (401)."""
    pass


class ExpiredTokenError(AuthenticationError):
    """Expired access token - needs refresh."""
    pass


class InvalidGrantError(AuthenticationError):
    """Invalid refresh token - needs re-authorization."""
    pass


class APIError(QBOSDKError):
    """Base class for API errors."""
    
    def __init__(self, message: str, status_code: int = None, response: str = None):
        super().__init__(message, response)
        self.status_code = status_code


class BadRequestError(APIError):
    """Bad request (400)."""
    pass


class ValidationError(APIError):
    """Validation error (400)."""
    pass


class ForbiddenError(APIError):
    """Forbidden - insufficient permissions (403)."""
    pass


class NotFoundError(APIError):
    """Resource not found (404)."""
    pass


class RateLimitError(APIError):
    """Rate limit exceeded (429)."""
    
    def __init__(self, message: str, retry_after: int = None, **kwargs):
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class ServerError(APIError):
    """Server error (5xx)."""
    pass


class InternalServerError(ServerError):
    """QBO internal server error (500)."""
    pass


class ServiceUnavailableError(ServerError):
    """QBO service unavailable (503)."""
    pass
