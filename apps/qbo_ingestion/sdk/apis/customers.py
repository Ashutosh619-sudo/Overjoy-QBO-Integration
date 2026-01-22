"""
QuickBooks Online Customers API.

Only includes methods needed for:
- Initial backfill (get all)
- Incremental sync (get updated since timestamp)
"""

from typing import Optional, Generator, List, Dict, Any
from .api_base import ApiBase


class Customers(ApiBase):
    """Customers API - minimal implementation for sync requirements."""
    
    def get_all_generator(
        self,
        last_updated_time: Optional[str] = None
    ) -> Generator[List[Dict[str, Any]], None, None]:
        """
        Generator that yields batches of customers.
        
        Args:
            last_updated_time: ISO timestamp for incremental sync.
                              If None, fetches all customers (initial backfill).
        
        Yields:
            List of customer dictionaries per batch.
        """
        if last_updated_time:
            query = (
                f"SELECT * FROM Customer "
                f"WHERE MetaData.LastUpdatedTime > '{last_updated_time}' "
                f"ORDER BY MetaData.LastUpdatedTime ASC"
            )
        else:
            query = "SELECT * FROM Customer ORDER BY MetaData.LastUpdatedTime ASC"
        
        yield from self._query_generator(query, 'Customer')
