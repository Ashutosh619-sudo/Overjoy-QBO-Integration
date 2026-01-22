"""
Django models for QBO Ingestion Service.

Design Decision: Minimal transformation
- Store QBO Id for efficient lookups and upserts
- Store full raw JSON payload for completeness
- Extract CustomerRef for invoices to enable relational queries

Trade-off Analysis:
- JSON storage vs normalized schema:
  - JSON preserves full QBO payload without transformation
  - Future schema changes don't require migrations
  - Trade-off: Querying nested data requires JSON parsing
"""

import json
from datetime import datetime
from typing import Optional, Dict, Any

from django.db import models
from django.db.models import JSONField


class SyncStatus(models.TextChoices):
    """Status of a sync operation."""
    PENDING = 'pending', 'Pending'
    IN_PROGRESS = 'in_progress', 'In Progress'
    SUCCESS = 'success', 'Success'
    FAILED = 'failed', 'Failed'


class ObjectType(models.TextChoices):
    """Types of QBO objects we sync."""
    CUSTOMER = 'Customer', 'Customer'
    INVOICE = 'Invoice', 'Invoice'


class QBOAccount(models.Model):
    """
    Represents a connected QuickBooks Online company/account.
    
    Each QBO company is identified by a realm_id. This table stores
    the OAuth credentials needed to access that company's data.
    
    Design Decision: One-to-many with customers/invoices
    - Allows supporting multiple QBO companies simultaneously
    - Each sync state is scoped to an account
    """
    
    realm_id = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text='QBO company/realm ID'
    )
    company_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text='Company name from QBO'
    )

    access_token = models.TextField(
        null=True,
        blank=True,
        help_text='Current access token'
    )
    refresh_token = models.TextField(
        help_text='OAuth refresh token (rotates on refresh!)'
    )
    access_token_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When access token expires'
    )

    is_token_expired = models.BooleanField(
        default=False,
        help_text='True if re-authorization is required'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'qbo_accounts'
        verbose_name = 'QBO Account'
        verbose_name_plural = 'QBO Accounts'

    def __str__(self):
        return f"{self.company_name or 'Unknown'} ({self.realm_id})"

    @classmethod
    def get_active_accounts(cls):
        """Get all accounts with valid (non-expired) tokens."""
        return cls.objects.filter(
            is_token_expired=False,
            refresh_token__isnull=False
        ).exclude(refresh_token='')

    @classmethod
    def create_or_update(
        cls,
        realm_id: str,
        refresh_token: str,
        access_token: Optional[str] = None,
        access_token_expires_at: Optional[datetime] = None,
        company_name: Optional[str] = None
    ) -> 'QBOAccount':
        """
        Create a new account or update existing one.
        
        This is the main entry point after OAuth authorization.
        """
        account, created = cls.objects.update_or_create(
            realm_id=realm_id,
            defaults={
                'refresh_token': refresh_token,
                'access_token': access_token,
                'access_token_expires_at': access_token_expires_at,
                'is_token_expired': False,
                **(({'company_name': company_name}) if company_name else {})
            }
        )

        if created:
            for obj_type in ObjectType.values:
                SyncState.objects.create(
                    account=account,
                    object_type=obj_type,
                    status=SyncStatus.PENDING
                )

        return account


class Customer(models.Model):
    """
    QBO Customer entity.
    
    Design Decision: Minimal transformation
    - Store QBO Id for efficient lookups and upserts
    - Store full raw JSON payload for completeness
    """

    account = models.ForeignKey(
        QBOAccount,
        on_delete=models.CASCADE,
        related_name='customers',
        help_text='QBO account this customer belongs to'
    )

    qbo_id = models.CharField(
        max_length=50,
        help_text='The QBO Customer.Id'
    )

    raw_data = JSONField(
        help_text='Full JSON payload from QBO'
    )

    sync_token = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text='QBO sync token for optimistic locking'
    )
    last_updated_time = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Metadata.LastUpdatedTime from QBO'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'customers'
        unique_together = ['account', 'qbo_id']
        indexes = [
            models.Index(fields=['account', 'qbo_id']),
        ]
    
    def __str__(self):
        display_name = self.raw_data.get('DisplayName', self.qbo_id) if self.raw_data else self.qbo_id
        return f"Customer {display_name}"

    @classmethod
    def upsert(
        cls,
        account: QBOAccount,
        qbo_id: str,
        raw_data: Dict[str, Any],
        sync_token: Optional[str] = None,
        last_updated_time: Optional[datetime] = None
    ) -> 'Customer':
        """
        Insert or update a customer record.
        
        Design Decision: Upsert pattern for idempotency
        - Same operation can be retried safely
        - No duplicate records on partial failures
        """
        customer, _ = cls.objects.update_or_create(
            account=account,
            qbo_id=qbo_id,
            defaults={
                'raw_data': raw_data,
                'sync_token': sync_token,
                'last_updated_time': last_updated_time
            }
        )
        return customer


class Invoice(models.Model):
    """
    QBO Invoice entity.
    
    Design Decision: Extract CustomerRef for relational queries
    - While we store the full raw payload, extracting CustomerRef.value
      enables efficient queries like "all invoices for customer X"
    """
    
    account = models.ForeignKey(
        QBOAccount, 
        on_delete=models.CASCADE,
        related_name='invoices',
        help_text='QBO account this invoice belongs to'
    )
    
    # QBO identifiers
    qbo_id = models.CharField(
        max_length=50,
        help_text='The QBO Invoice.Id'
    )
    
    # Extracted field per requirements
    customer_ref = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        db_index=True,
        help_text='CustomerRef.value from QBO'
    )
    
    raw_data = JSONField(
        help_text='Full JSON payload from QBO'
    )
    
    sync_token = models.CharField(
        max_length=50,
        null=True, 
        blank=True,
        help_text='QBO sync token'
    )
    last_updated_time = models.DateTimeField(
        null=True, 
        blank=True,
        help_text='Metadata.LastUpdatedTime from QBO'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'invoices'
        unique_together = ['account', 'qbo_id']
        indexes = [
            models.Index(fields=['account', 'qbo_id']),
            models.Index(fields=['account', 'customer_ref']),
        ]
    
    def __str__(self):
        doc_number = self.raw_data.get('DocNumber', self.qbo_id) if self.raw_data else self.qbo_id
        return f"Invoice {doc_number}"
    
    @classmethod
    def upsert(
        cls,
        account: QBOAccount,
        qbo_id: str,
        raw_data: Dict[str, Any],
        customer_ref: Optional[str] = None,
        sync_token: Optional[str] = None,
        last_updated_time: Optional[datetime] = None
    ) -> 'Invoice':
        """
        Insert or update an invoice record.
        
        Extracts CustomerRef.value from raw_data if not provided.
        """
        if customer_ref is None and 'CustomerRef' in raw_data:
            customer_ref = raw_data['CustomerRef'].get('value')
        
        invoice, _ = cls.objects.update_or_create(
            account=account,
            qbo_id=qbo_id,
            defaults={
                'raw_data': raw_data,
                'customer_ref': customer_ref,
                'sync_token': sync_token,
                'last_updated_time': last_updated_time
            }
        )
        return invoice


class SyncState(models.Model):
    """
    Tracks sync state per account per object type.
    
    Design Decision: Granular sync state tracking
    - Each (account, object_type) pair has independent sync state
    - Allows partial failures without blocking other syncs
    - Enables resumption from last successful checkpoint
    
    Key fields:
    - checkpoint: Watermark (LastUpdatedTime) for incremental sync
    - error_message: Last error for debugging
    """
    
    account = models.ForeignKey(
        QBOAccount,
        on_delete=models.CASCADE,
        related_name='sync_states',
        help_text='QBO account'
    )
    object_type = models.CharField(
        max_length=20,
        choices=ObjectType.choices,
        help_text='Type of object being synced'
    )
    
    last_attempt_time = models.DateTimeField(
        null=True, 
        blank=True,
        help_text='When sync was last attempted'
    )
    last_successful_sync_time = models.DateTimeField(
        null=True, 
        blank=True,
        help_text='When sync last succeeded'
    )
    
    status = models.CharField(
        max_length=20,
        choices=SyncStatus.choices,
        default=SyncStatus.PENDING,
        help_text='Current sync status'
    )
    
    checkpoint = models.CharField(
        max_length=100, 
        null=True, 
        blank=True,
        help_text='LastUpdatedTime checkpoint for incremental sync'
    )
    
    error_message = models.TextField(
        null=True, 
        blank=True,
        help_text='Last error message'
    )
    consecutive_failures = models.IntegerField(
        default=0,
        help_text='Number of consecutive failures'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'sync_states'
        unique_together = ['account', 'object_type']
        indexes = [
            models.Index(fields=['account', 'object_type']),
        ]
    
    def __str__(self):
        return f"SyncState({self.account.realm_id}, {self.object_type}, {self.status})"
    
    def mark_started(self):
        """Mark sync as started."""
        self.status = SyncStatus.IN_PROGRESS
        self.last_attempt_time = datetime.utcnow()
        self.error_message = None
        self.save(update_fields=['status', 'last_attempt_time', 'error_message', 'updated_at'])
    
    def mark_success(self, checkpoint: Optional[str] = None):
        """Mark sync as successful."""
        self.status = SyncStatus.SUCCESS
        self.last_successful_sync_time = datetime.utcnow()
        self.consecutive_failures = 0
        self.error_message = None
        if checkpoint:
            self.checkpoint = checkpoint
        self.save(update_fields=[
            'status', 'last_successful_sync_time', 'consecutive_failures', 
            'error_message', 'checkpoint', 'updated_at'
        ])
    
    def mark_failed(self, error_message: str):
        """Mark sync as failed."""
        self.status = SyncStatus.FAILED
        self.error_message = error_message
        self.consecutive_failures += 1
        self.save(update_fields=['status', 'error_message', 'consecutive_failures', 'updated_at'])
