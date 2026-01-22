"""
QuickBooks Online SDK.

Minimal SDK for syncing Customers and Invoices from QBO.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Callable

import requests

from .apis import Customers, Invoices
from .exceptions import (
    QBOSDKError,
    AuthenticationError,
    InvalidGrantError
)

logger = logging.getLogger(__name__)

TOKEN_ENDPOINT_SANDBOX = 'https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer'
TOKEN_ENDPOINT_PRODUCTION = 'https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer'

API_BASE_SANDBOX = 'https://sandbox-quickbooks.api.intuit.com/v3/company'
API_BASE_PRODUCTION = 'https://quickbooks.api.intuit.com/v3/company'


def exchange_authorization_code(
    client_id: str,
    client_secret: str,
    authorization_code: str,
    redirect_uri: str
) -> dict:
    """
    Exchange authorization code for tokens.
    
    Returns:
        Dict with 'access_token', 'refresh_token', 'expires_in'
    """
    response = requests.post(
        TOKEN_ENDPOINT_SANDBOX,
        auth=(client_id, client_secret),
        headers={'Accept': 'application/json'},
        data={
            'grant_type': 'authorization_code',
            'code': authorization_code,
            'redirect_uri': redirect_uri
        },
        timeout=30
    )

    if response.status_code != 200:
        try:
            error = response.json().get('error_description', response.text)
        except ValueError:
            error = response.text
        raise AuthenticationError(f"Token exchange failed: {error}")
    
    return response.json()


class QuickBooksOnlineSDK:
    """
    QuickBooks Online SDK client.
    
    Handles OAuth token management and provides access to API resources.
    """
    
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        realm_id: str,
        environment: str = 'sandbox',
        minor_version: int = 65,
        on_token_refresh: Optional[Callable[[str, str, datetime], None]] = None,
        access_token: Optional[str] = None,
        token_expires_at: Optional[datetime] = None
    ):
        """
        Initialize the SDK.
        
        Args:
            client_id: OAuth client ID
            client_secret: OAuth client secret
            refresh_token: OAuth refresh token
            realm_id: QBO company/realm ID
            environment: 'sandbox' or 'production'
            minor_version: QBO API minor version
            on_token_refresh: Callback when tokens are refreshed
            access_token: Current access token (optional, avoids refresh on first use)
            token_expires_at: When access token expires (optional)
        """
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._realm_id = realm_id
        self._minor_version = minor_version
        self._on_token_refresh = on_token_refresh
        
        if environment == 'production':
            self._token_url = TOKEN_ENDPOINT_PRODUCTION
            self._base_url = f"{API_BASE_PRODUCTION}/{realm_id}"
        else:
            self._token_url = TOKEN_ENDPOINT_SANDBOX
            self._base_url = f"{API_BASE_SANDBOX}/{realm_id}"
        
        self._access_token: Optional[str] = access_token
        self._token_expires_at: Optional[datetime] = token_expires_at
        
        self.customers = Customers()
        self.invoices = Invoices()
        
        self._configure_apis()
        
        if self._access_token:
            self._update_api_tokens()
    
    @property
    def refresh_token(self) -> str:
        """Get current refresh token."""
        return self._refresh_token
    
    def _configure_apis(self):
        """Configure all API resources."""
        for api in [self.customers, self.invoices]:
            api.set_server_url(self._base_url)
            api.set_minor_version(self._minor_version)
    
    def _update_api_tokens(self):
        """Update access token on all API resources."""
        for api in [self.customers, self.invoices]:
            api.set_access_token(self._access_token)
    
    def _refresh_tokens(self):
        """Refresh the access token using the refresh token."""
        logger.info("Refreshing QBO access token")
        
        response = requests.post(
            self._token_url,
            auth=(self._client_id, self._client_secret),
            headers={'Accept': 'application/json'},
            data={
                'grant_type': 'refresh_token',
                'refresh_token': self._refresh_token
            },
            timeout=30
        )
        
        if response.status_code != 200:
            try:
                error_data = response.json()
                error = error_data.get('error', '')
                error_desc = error_data.get('error_description', response.text)
                
                if error == 'invalid_grant':
                    raise InvalidGrantError(f"Refresh token invalid: {error_desc}")
            except ValueError:
                pass
            raise AuthenticationError(f"Token refresh failed: {response.text}")
        
        token_data = response.json()
        
        self._access_token = token_data['access_token']
        self._refresh_token = token_data['refresh_token']
        
        expires_in = token_data.get('expires_in', 3600)
        self._token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        
        self._update_api_tokens()
        
        if self._on_token_refresh:
            self._on_token_refresh(
                self._access_token,
                self._refresh_token,
                self._token_expires_at
            )
        
        logger.info("Token refresh successful")
    
    def ensure_token_valid(self):
        """Ensure access token is valid, refreshing if needed."""
        if self._access_token is None:
            self._refresh_tokens()
        elif self._token_expires_at:
            now = datetime.now(timezone.utc)
            expires_at = self._token_expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if now >= expires_at - timedelta(minutes=5):
                self._refresh_tokens()


__all__ = [
    'QuickBooksOnlineSDK',
    'exchange_authorization_code',
    'QBOSDKError',
    'AuthenticationError',
    'InvalidGrantError',
]
