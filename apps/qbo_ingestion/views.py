"""
Django REST Framework views for QBO Ingestion Service.

API Endpoints:
- POST /api/qbo/authorize/           - Exchange auth code for tokens
- GET  /api/qbo/accounts/            - List all accounts
- POST /api/qbo/sync/                - Trigger sync
- GET  /api/qbo/sync/status/         - Get sync status
- GET  /api/qbo/customers/           - List customers
- GET  /api/qbo/invoices/            - List invoices
"""

import logging
from datetime import datetime, timedelta

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response

from .models import QBOAccount, Customer, Invoice, SyncState
from .serializers import (
    QBOAccountSerializer,
    CustomerSerializer,
    InvoiceSerializer,
    AuthorizeRequestSerializer,
    SyncRequestSerializer,
)
from .qbo_client import exchange_code_for_tokens
from .sync_engine import SyncEngine, AccountNotFoundError, RevokedRefreshTokenError
from .sdk.exceptions import AuthenticationError

logger = logging.getLogger(__name__)


class AuthorizeView(APIView):
    """Exchange OAuth authorization code for tokens."""
    
    def post(self, request):
        serializer = AuthorizeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        code = serializer.validated_data['code']
        realm_id = serializer.validated_data['realm_id']
        redirect_uri = serializer.validated_data.get('redirect_uri')
        
        try:
            token_data = exchange_code_for_tokens(code, redirect_uri)
            
            expires_at = datetime.utcnow() + timedelta(
                seconds=token_data.get('expires_in', 3600)
            )
            
            account = QBOAccount.create_or_update(
                realm_id=realm_id,
                refresh_token=token_data['refresh_token'],
                access_token=token_data['access_token'],
                access_token_expires_at=expires_at,
            )
            
            return Response({
                'success': True,
                'account': QBOAccountSerializer(account).data
            })
            
        except AuthenticationError as e:
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class AccountListView(APIView):
    """List all QBO accounts."""
    
    def get(self, request):
        accounts = QBOAccount.objects.all().order_by('-created_at')
        return Response({
            'count': accounts.count(),
            'results': QBOAccountSerializer(accounts, many=True).data
        })


class SyncTriggerView(APIView):
    """Trigger sync for one or all accounts."""
    
    def post(self, request):
        serializer = SyncRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        realm_id = serializer.validated_data.get('realm_id')
        engine = SyncEngine()
        
        try:
            if realm_id:
                result = engine.sync_account(realm_id)
                return Response({
                    'success': result.get('success', False),
                    'results': [result]
                })
            else:
                results = engine.sync_all_accounts()
                success_count = sum(1 for r in results if r.get('success'))
                return Response({
                    'success': success_count == len(results),
                    'results': results
                })
                
        except AccountNotFoundError as e:
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_404_NOT_FOUND
            )
        except RevokedRefreshTokenError as e:
            return Response(
                {'success': False, 'error': str(e), 'requires_reauthorization': True},
                status=status.HTTP_401_UNAUTHORIZED
            )


class SyncStatusView(APIView):
    """Get sync status for all or specific account."""
    
    def get(self, request):
        realm_id = request.query_params.get('realm_id')
        engine = SyncEngine()
        
        if realm_id:
            try:
                return Response(engine.get_sync_status(realm_id))
            except AccountNotFoundError as e:
                return Response(
                    {'error': str(e)},
                    status=status.HTTP_404_NOT_FOUND
                )
        
        accounts = QBOAccount.objects.all()
        statuses = []
        for account in accounts:
            try:
                statuses.append(engine.get_sync_status(account.realm_id))
            except Exception as e:
                statuses.append({'realm_id': account.realm_id, 'error': str(e)})
        
        return Response({'count': len(statuses), 'results': statuses})


class CustomerListView(APIView):
    """List customers for an account."""
    
    def get(self, request):
        realm_id = request.query_params.get('realm_id')
        
        if not realm_id:
            return Response(
                {'error': 'realm_id query parameter required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        account = get_object_or_404(QBOAccount, realm_id=realm_id)
        customers = Customer.objects.filter(account=account).order_by('-updated_at')
        
        return Response({
            'count': customers.count(),
            'results': CustomerSerializer(customers, many=True).data
        })


class InvoiceListView(APIView):
    """List invoices for an account."""
    
    def get(self, request):
        realm_id = request.query_params.get('realm_id')
        
        if not realm_id:
            return Response(
                {'error': 'realm_id query parameter required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        account = get_object_or_404(QBOAccount, realm_id=realm_id)
        invoices = Invoice.objects.filter(account=account).order_by('-updated_at')
        
        return Response({
            'count': invoices.count(),
            'results': InvoiceSerializer(invoices, many=True).data
        })
