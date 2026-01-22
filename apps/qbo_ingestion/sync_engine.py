"""
Sync Engine for QBO Ingestion Service.

Orchestrates the synchronization of Customers and Invoices from QBO to local database.

Design Decision: Timestamp-based incremental sync
- QBO supports querying by Metadata.LastUpdatedTime
- First sync is always full (no checkpoint)
- Subsequent syncs query only records updated since last checkpoint

Failure Recovery:
- Each object type syncs independently
- Checkpoint is updated only after successful batch processing
- On failure, next sync resumes from last checkpoint
- Idempotent upserts prevent duplicates on retry
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple

from django.db import transaction

from .models import QBOAccount, Customer, Invoice, SyncState, ObjectType, SyncStatus
from .qbo_client import create_client_for_account, QBOClient
from .sdk.exceptions import InvalidGrantError, QBOSDKError

logger = logging.getLogger(__name__)


class SyncError(Exception):
    """Sync operation error."""
    pass


class AccountNotFoundError(Exception):
    """Account not found."""
    pass


class RevokedRefreshTokenError(Exception):
    """Refresh token has been revoked."""
    pass


class SyncEngine:

    SYNC_CONFIG = [
        {'name': 'customers', 'method': 'sync_customers'},
        {'name': 'invoices', 'method': 'sync_invoices'},
    ]
    
    def _parse_last_updated_time(self, iso_string: str) -> Optional[datetime]:
        """Parse QBO's ISO datetime string to datetime object."""
        if not iso_string:
            return None
        try:
            if iso_string.endswith('Z'):
                iso_string = iso_string[:-1] + '+00:00'
            return datetime.fromisoformat(iso_string)
        except (ValueError, TypeError):
            logger.warning(f"Could not parse datetime: {iso_string}")
            return None
    
    def _update_checkpoint(self, current: Optional[str], new_value: Optional[str]) -> Optional[str]:
        """Update checkpoint if new value is greater."""
        if new_value and (not current or new_value > current):
            return new_value
        return current
    
    
    def sync_customers(
        self,
        account: QBOAccount,
        client: QBOClient
    ) -> Tuple[int, Optional[str]]:
        """
        Sync customers for an account.
        
        Returns:
            Tuple of (records_processed, new_checkpoint)
        """
        logger.info(f"Starting customer sync for realm_id={account.realm_id}")
        
        # Ensure token is valid before API calls
        client.ensure_token_valid()
        
        # Get current sync state
        sync_state, _ = SyncState.objects.get_or_create(
            account=account,
            object_type=ObjectType.CUSTOMER,
            defaults={'status': SyncStatus.PENDING}
        )
        last_sync_time = sync_state.checkpoint
        
        # Mark sync as started
        sync_state.mark_started()
        
        total_processed = 0
        max_checkpoint = last_sync_time
        
        try:
            # Fetch customers using SDK
            for customer_batch in client.customers.get_all_generator(last_sync_time):
                batch_count = len(customer_batch)
                logger.info(f"Processing batch of {batch_count} customers")
                
                with transaction.atomic():
                    for customer_data in customer_batch:
                        qbo_id = customer_data.get('Id')
                        sync_token = customer_data.get('SyncToken')
                        metadata = customer_data.get('MetaData', {})
                        last_updated_str = metadata.get('LastUpdatedTime')
                        last_updated = self._parse_last_updated_time(last_updated_str)
                        
                        max_checkpoint = self._update_checkpoint(max_checkpoint, last_updated_str)
                        
                        Customer.upsert(
                            account=account,
                            qbo_id=qbo_id,
                            raw_data=customer_data,
                            sync_token=sync_token,
                            last_updated_time=last_updated
                        )
                        total_processed += 1
                
                logger.debug(f"Committed batch, total processed: {total_processed}")
            
            # Mark sync as successful
            sync_state.mark_success(max_checkpoint)
            
            logger.info(
                f"Customer sync completed: {total_processed} records, "
                f"checkpoint={max_checkpoint}"
            )
            return total_processed, max_checkpoint
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Customer sync failed: {error_msg}")
            sync_state.mark_failed(error_msg)
            raise
    
    def sync_invoices(
        self,
        account: QBOAccount,
        client: QBOClient
    ) -> Tuple[int, Optional[str]]:
        """
        Sync invoices for an account.
        """
        logger.info(f"Starting invoice sync for realm_id={account.realm_id}")
        
        # Ensure token is valid before API calls
        client.ensure_token_valid()
        
        # Get current sync state
        sync_state, _ = SyncState.objects.get_or_create(
            account=account,
            object_type=ObjectType.INVOICE,
            defaults={'status': SyncStatus.PENDING}
        )
        last_sync_time = sync_state.checkpoint
        
        # Mark sync as started
        sync_state.mark_started()
        
        total_processed = 0
        max_checkpoint = last_sync_time
        
        try:
            for invoice_batch in client.invoices.get_all_generator(last_sync_time):
                batch_count = len(invoice_batch)
                logger.info(f"Processing batch of {batch_count} invoices")
                
                with transaction.atomic():
                    for invoice_data in invoice_batch:
                        qbo_id = invoice_data.get('Id')
                        sync_token = invoice_data.get('SyncToken')
                        
                        customer_ref = None
                        if 'CustomerRef' in invoice_data:
                            customer_ref = invoice_data['CustomerRef'].get('value')
                        
                        metadata = invoice_data.get('MetaData', {})
                        last_updated_str = metadata.get('LastUpdatedTime')
                        last_updated = self._parse_last_updated_time(last_updated_str)
                        
                        max_checkpoint = self._update_checkpoint(max_checkpoint, last_updated_str)
                        
                        Invoice.upsert(
                            account=account,
                            qbo_id=qbo_id,
                            raw_data=invoice_data,
                            customer_ref=customer_ref,
                            sync_token=sync_token,
                            last_updated_time=last_updated
                        )
                        total_processed += 1
                
                logger.debug(f"Committed batch, total processed: {total_processed}")
            
            sync_state.mark_success(max_checkpoint)
            
            logger.info(
                f"Invoice sync completed: {total_processed} records, "
                f"checkpoint={max_checkpoint}"
            )
            return total_processed, max_checkpoint
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Invoice sync failed: {error_msg}")
            sync_state.mark_failed(error_msg)
            raise
    
    def _sync_object_type(
        self,
        account: QBOAccount,
        client: QBOClient,
        config: Dict[str, str]
    ) -> Dict[str, Any]:
        """Sync a single object type and return result."""
        name = config['name']
        sync_method = getattr(self, config['method'])
        
        try:
            count, checkpoint = sync_method(account, client)
            return {
                'status': 'success',
                'count': count,
                'checkpoint': checkpoint,
                'error': None
            }
        except InvalidGrantError:
            account.is_token_expired = True
            account.save(update_fields=['is_token_expired', 'updated_at'])
            raise RevokedRefreshTokenError("Refresh token is invalid or revoked")
        except Exception as e:
            logger.error(f"{name} sync failed: {e}")
            return {
                'status': 'failed',
                'count': 0,
                'error': str(e)
            }
    
    def sync_account(self, realm_id: str) -> Dict[str, Any]:
        """Perform a full sync for a specific account."""
        logger.info(f"Starting sync for realm_id={realm_id}")
        
        results = {'realm_id': realm_id, 'success': False}
        for config in self.SYNC_CONFIG:
            results[config['name']] = {'status': 'pending', 'count': 0, 'error': None}
        
        try:
            account = QBOAccount.objects.filter(realm_id=realm_id).first()
            if not account:
                raise AccountNotFoundError(f"Account with realm_id={realm_id} not found")
            
            if account.is_token_expired:
                raise RevokedRefreshTokenError("Token has been marked as expired")
            
            try:
                client = create_client_for_account(account)
            except InvalidGrantError:
                account.is_token_expired = True
                account.save(update_fields=['is_token_expired', 'updated_at'])
                raise RevokedRefreshTokenError("Refresh token is invalid or revoked")
            
            for config in self.SYNC_CONFIG:
                results[config['name']] = self._sync_object_type(account, client, config)
            
            results['success'] = all(
                results[c['name']]['status'] == 'success' for c in self.SYNC_CONFIG
            )
            
            logger.info(f"Sync completed for realm_id={realm_id}: {results}")
            return results
            
        except (AccountNotFoundError, RevokedRefreshTokenError):
            raise
        except Exception as e:
            logger.error(f"Sync failed for realm_id={realm_id}: {e}")
            raise SyncError(f"Sync failed: {e}")
    
    def sync_all_accounts(self) -> List[Dict[str, Any]]:
        """Sync all active accounts."""
        logger.info("Starting sync for all active accounts")
        results = []
        
        accounts = QBOAccount.get_active_accounts()
        logger.info(f"Found {accounts.count()} active accounts to sync")
        
        for account in accounts:
            try:
                result = self.sync_account(account.realm_id)
                results.append(result)
            except RevokedRefreshTokenError as e:
                logger.error(f"Account {account.realm_id} needs re-authorization: {e}")
                results.append({
                    'realm_id': account.realm_id,
                    'success': False,
                    'error': 'Re-authorization required',
                    'customers': {'status': 'skipped'},
                    'invoices': {'status': 'skipped'}
                })
            except Exception as e:
                logger.error(f"Sync failed for {account.realm_id}: {e}")
                results.append({
                    'realm_id': account.realm_id,
                    'success': False,
                    'error': str(e),
                    'customers': {'status': 'failed'},
                    'invoices': {'status': 'failed'}
                })
        
        success_count = sum(1 for r in results if r.get('success'))
        logger.info(f"Sync cycle completed: {success_count}/{len(results)} accounts successful")
        
        return results
    
    def get_sync_status(self, realm_id: str) -> Dict[str, Any]:
        """Get the current sync status for an account."""
        account = QBOAccount.objects.filter(realm_id=realm_id).first()
        if not account:
            raise AccountNotFoundError(f"Account not found: {realm_id}")
        
        sync_states = SyncState.objects.filter(account=account)
        
        customer_count = Customer.objects.filter(account=account).count()
        invoice_count = Invoice.objects.filter(account=account).count()
        
        status = {
            'realm_id': realm_id,
            'company_name': account.company_name,
            'is_token_expired': account.is_token_expired,
            'record_counts': {
                'customers': customer_count,
                'invoices': invoice_count
            },
            'sync_states': {}
        }
        
        for state in sync_states:
            status['sync_states'][state.object_type] = {
                'status': state.status,
                'last_attempt': state.last_attempt_time.isoformat() if state.last_attempt_time else None,
                'last_success': state.last_successful_sync_time.isoformat() if state.last_successful_sync_time else None,
                'checkpoint': state.checkpoint,
                'consecutive_failures': state.consecutive_failures,
                'error': state.error_message
            }
        
        return status
