"""
Base API class for QuickBooks Online SDK.

Provides core HTTP request handling and pagination for QBO queries.
"""

import time
import logging
from typing import Optional, Dict, Any, Generator, List

import requests

from ..exceptions import (
    QBOSDKError,
    AuthenticationError,
    RateLimitError,
    NotFoundError,
    ValidationError,
    ServerError
)

logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 1000


class ApiBase:
    """
    Base class for QBO API resources.
    
    Handles:
    - HTTP requests with authentication
    - Error handling and retries
    - Pagination for queries
    """
    
    def __init__(self):
        self._access_token: Optional[str] = None
        self._server_url: Optional[str] = None
        self._minor_version: int = 65
        self._max_retries: int = 3
        self._retry_delay: float = 1.0
    
    def set_access_token(self, token: str):
        """Set the access token for API requests."""
        self._access_token = token
    
    def set_server_url(self, url: str):
        """Set the base server URL."""
        self._server_url = url.rstrip('/')
    
    def set_minor_version(self, version: int):
        """Set the QBO API minor version."""
        self._minor_version = version
    
    def _get_headers(self) -> Dict[str, str]:
        """Get headers for API requests."""
        if not self._access_token:
            raise AuthenticationError("Access token not set")
        
        return {
            'Authorization': f'Bearer {self._access_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
    
    def _build_url(self, endpoint: str) -> str:
        """Build full URL for an endpoint."""
        if not self._server_url:
            raise QBOSDKError("Server URL not configured")
        
        url = f"{self._server_url}/{endpoint}"
        
        # Add minor version
        separator = '&' if '?' in url else '?'
        url = f"{url}{separator}minorversion={self._minor_version}"
        
        return url
    
    def _handle_response(self, response: requests.Response) -> Dict[str, Any]:
        """Handle API response and raise appropriate errors."""
        if response.status_code == 200:
            return response.json()
        
        # Try to parse error details
        error_detail = ""
        try:
            error_json = response.json()
            if 'Fault' in error_json:
                fault = error_json['Fault']
                errors = fault.get('Error', [])
                if errors:
                    error_detail = errors[0].get('Detail', errors[0].get('Message', ''))
        except (ValueError, KeyError):
            error_detail = response.text[:500] if response.text else ""
        
        status_code = response.status_code
        
        if status_code == 401:
            raise AuthenticationError(f"Authentication failed: {error_detail}")
        elif status_code == 403:
            raise AuthenticationError(f"Access forbidden: {error_detail}")
        elif status_code == 404:
            raise NotFoundError(f"Resource not found: {error_detail}")
        elif status_code == 400:
            raise ValidationError(f"Validation error: {error_detail}")
        elif status_code == 429:
            raise RateLimitError("Rate limit exceeded")
        elif status_code >= 500:
            raise ServerError(f"Server error ({status_code}): {error_detail}")
        else:
            raise QBOSDKError(f"API error ({status_code}): {error_detail}")
    
    def _request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Make HTTP request with retry logic."""
        last_exception = None
        
        for attempt in range(self._max_retries):
            try:
                response = requests.request(
                    method=method,
                    url=url,
                    headers=self._get_headers(),
                    timeout=30,
                    **kwargs
                )
                return self._handle_response(response)
                
            except RateLimitError:
                delay = self._retry_delay * (2 ** attempt)
                logger.warning(f"Rate limited, waiting {delay}s (attempt {attempt + 1})")
                time.sleep(delay)
                last_exception = RateLimitError("Rate limit exceeded after retries")
                
            except ServerError as e:
                if attempt < self._max_retries - 1:
                    delay = self._retry_delay * (attempt + 1)
                    logger.warning(f"Server error, retrying in {delay}s: {e}")
                    time.sleep(delay)
                last_exception = e
                
            except (AuthenticationError, NotFoundError, ValidationError):
                raise
                
            except requests.RequestException as e:
                if attempt < self._max_retries - 1:
                    delay = self._retry_delay * (attempt + 1)
                    logger.warning(f"Network error, retrying in {delay}s: {e}")
                    time.sleep(delay)
                last_exception = QBOSDKError(f"Network error: {e}")
        
        raise last_exception or QBOSDKError("Request failed after retries")
    
    def _query(self, query: str) -> Dict[str, Any]:
        """Execute a QBO query."""
        import urllib.parse
        encoded_query = urllib.parse.quote(query)
        url = self._build_url(f"query?query={encoded_query}")
        return self._request_with_retry('GET', url)
    
    def _query_generator(
        self,
        base_query: str,
        entity_name: str,
        page_size: int = DEFAULT_PAGE_SIZE
    ) -> Generator[List[Dict[str, Any]], None, None]:
        """
        Generator that yields paginated query results.
        
        Args:
            base_query: The SELECT query without STARTPOSITION/MAXRESULTS
            entity_name: The entity name (e.g., 'Customer', 'Invoice')
            page_size: Number of records per page
        
        Yields:
            List of entity dictionaries per page
        """
        start_position = 1
        
        while True:
            paginated_query = (
                f"{base_query} STARTPOSITION {start_position} MAXRESULTS {page_size}"
            )
            
            logger.debug(f"Executing query: {paginated_query}")
            
            response = self._query(paginated_query)
            query_response = response.get('QueryResponse', {})
            
            entities = query_response.get(entity_name, [])
            
            if not entities:
                break
            
            yield entities
            
            if len(entities) < page_size:
                break
            
            start_position += page_size
