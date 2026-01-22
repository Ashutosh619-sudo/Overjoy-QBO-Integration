"""
Utility functions for QBO Ingestion Service.
"""

import logging
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status

from .sync_engine import AccountNotFoundError, RevokedRefreshTokenError
from .sdk.exceptions import QBOSDKError, AuthenticationError

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    """Custom exception handler for Django REST Framework."""
    response = exception_handler(exc, context)
    
    if response is not None:
        return response
    
    if isinstance(exc, AccountNotFoundError):
        return Response({'error': str(exc)}, status=status.HTTP_404_NOT_FOUND)
    
    if isinstance(exc, (RevokedRefreshTokenError, AuthenticationError)):
        return Response({'error': str(exc)}, status=status.HTTP_401_UNAUTHORIZED)
    
    if isinstance(exc, QBOSDKError):
        return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
    
    logger.exception(f"Unhandled exception: {exc}")
    return Response({'error': 'Internal server error'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
