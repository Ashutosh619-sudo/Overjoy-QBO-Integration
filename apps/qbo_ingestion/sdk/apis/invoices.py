"""
QuickBooks Online Invoices API.

Only includes methods needed for:
- Initial backfill (get all)
- Incremental sync (get updated since timestamp)
"""

from typing import Optional, Generator, List, Dict, Any
from .api_base import ApiBase


class Invoices(ApiBase):
    """Invoices API - minimal implementation for sync requirements."""
    
    def get_all_generator(
        self,
        last_updated_time: Optional[str] = None
    ) -> Generator[List[Dict[str, Any]], None, None]:
        """
        Generator that yields batches of invoices.
        
        Args:
            last_updated_time: ISO timestamp for incremental sync.
                              If None, fetches all invoices (initial backfill).
        
        Yields:
            List of invoice dictionaries per batch.
        """
        if last_updated_time:
            # Incremental sync - only get updated records
            query = (
                f"SELECT * FROM Invoice "
                f"WHERE MetaData.LastUpdatedTime > '{last_updated_time}' "
                f"ORDER BY MetaData.LastUpdatedTime ASC"
            )
        else:
            # Initial backfill - get all records
            query = "SELECT * FROM Invoice ORDER BY MetaData.LastUpdatedTime ASC"
        
        yield from self._query_generator(query, 'Invoice')
