"""
QuickBooks Online Client for Django.

This module provides a thin wrapper around the SDK for use with Django models.
It handles token persistence via callbacks when tokens are refreshed.
"""

import logging
from datetime import datetime
from typing import Optional, Callable

from django.conf import settings
from django.db import transaction

from .sdk import QuickBooksOnlineSDK, exchange_authorization_code
from .sdk.exceptions import InvalidGrantError

logger = logging.getLogger(__name__)


class QBOClient:
    """
    QBO client wrapper for Django integration.
    
    Wraps the SDK and handles token persistence to the database.
    """
    
    def __init__(
        self,
        realm_id: str,
        refresh_token: str,
        access_token: Optional[str] = None,
        token_expires_at: Optional[datetime] = None,
        on_token_refresh: Optional[Callable[[str, str, datetime], None]] = None
    ):
        """
        Initialize QBO client.
        
        Args:
            realm_id: QBO company/realm ID
            refresh_token: OAuth refresh token
            access_token: Current access token (optional)
            token_expires_at: When access token expires (optional)
            on_token_refresh: Callback when tokens are refreshed
        """
        self.realm_id = realm_id
        self._on_token_refresh = on_token_refresh
        
        self._sdk = QuickBooksOnlineSDK(
            client_id=settings.QBO_CLIENT_ID,
            client_secret=settings.QBO_CLIENT_SECRET,
            refresh_token=refresh_token,
            realm_id=realm_id,
            environment=settings.QBO_ENVIRONMENT,
            minor_version=settings.QBO_MINOR_VERSION,
            on_token_refresh=on_token_refresh,
            access_token=access_token,
            token_expires_at=token_expires_at
        )
    
    @property
    def customers(self):
        """Access the Customers API."""
        return self._sdk.customers
    
    @property
    def invoices(self):
        """Access the Invoices API."""
        return self._sdk.invoices
    
    @property
    def refresh_token(self) -> str:
        """Get the current refresh token."""
        return self._sdk.refresh_token
    
    def ensure_token_valid(self):
        """Ensure the access token is valid, refreshing if needed."""
        self._sdk.ensure_token_valid()


def create_client_for_account(account: 'QBOAccount') -> QBOClient:
    """
    Factory function to create a QBO client for a Django account model.
    
    Sets up the token refresh callback to persist tokens to database.
    
    Args:
        account: QBOAccount model instance
    
    Returns:
        Configured QBOClient
    """
    from .models import QBOAccount
    
    def on_token_refresh(access_token: str, refresh_token: str, expires_at: datetime):
        """Callback to persist refreshed tokens to database."""
        logger.info(f"Persisting refreshed tokens for realm_id={account.realm_id}")
        with transaction.atomic():
            acc = QBOAccount.objects.select_for_update().get(pk=account.pk)
            acc.access_token = access_token
            acc.refresh_token = refresh_token
            acc.access_token_expires_at = expires_at
            acc.is_token_expired = False
            acc.save(update_fields=[
                'access_token', 'refresh_token', 'access_token_expires_at',
                'is_token_expired', 'updated_at'
            ])
    
    return QBOClient(
        realm_id=account.realm_id,
        refresh_token=account.refresh_token,
        access_token=account.access_token,
        token_expires_at=account.access_token_expires_at,
        on_token_refresh=on_token_refresh
    )


def exchange_code_for_tokens(
    authorization_code: str,
    redirect_uri: Optional[str] = None
) -> dict:
    """
    Exchange an authorization code for tokens.
    
    Args:
        authorization_code: Code from OAuth Playground
        redirect_uri: Redirect URI (uses settings default if not provided)
    
    Returns:
        Dict with 'access_token', 'refresh_token', 'expires_in'
    """
    return exchange_authorization_code(
        client_id=settings.QBO_CLIENT_ID,
        client_secret=settings.QBO_CLIENT_SECRET,
        authorization_code=authorization_code,
        redirect_uri=redirect_uri or settings.QBO_REDIRECT_URI
    )
