"""
Django REST Framework serializers for QBO Ingestion Service.
"""

from rest_framework import serializers
from .models import QBOAccount, Customer, Invoice


class QBOAccountSerializer(serializers.ModelSerializer):
    """Serializer for QBO accounts."""
    
    class Meta:
        model = QBOAccount
        fields = [
            'id', 'realm_id', 'company_name',
            'is_token_expired', 'created_at', 'updated_at'
        ]


class CustomerSerializer(serializers.ModelSerializer):
    """Serializer for customers."""
    
    class Meta:
        model = Customer
        fields = ['id', 'qbo_id', 'raw_data', 'created_at', 'updated_at']


class InvoiceSerializer(serializers.ModelSerializer):
    """Serializer for invoices."""
    
    class Meta:
        model = Invoice
        fields = ['id', 'qbo_id', 'customer_ref', 'raw_data', 'created_at', 'updated_at']


class AuthorizeRequestSerializer(serializers.Serializer):
    """Serializer for authorization request."""
    code = serializers.CharField(required=True)
    realm_id = serializers.CharField(required=True)
    redirect_uri = serializers.CharField(required=False, allow_blank=True)


class SyncRequestSerializer(serializers.Serializer):
    """Serializer for sync request."""
    realm_id = serializers.CharField(required=False, allow_blank=True)
