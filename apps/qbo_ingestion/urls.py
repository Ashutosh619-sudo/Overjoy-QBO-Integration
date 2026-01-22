"""
URL configuration for QBO Ingestion API.
"""

from django.urls import path
from .views import (
    AuthorizeView,
    AccountListView,
    SyncTriggerView,
    SyncStatusView,
    CustomerListView,
    InvoiceListView,
)

urlpatterns = [
    path('authorize/', AuthorizeView.as_view(), name='authorize'),
    path('accounts/', AccountListView.as_view(), name='accounts'),
    path('sync/', SyncTriggerView.as_view(), name='sync'),
    path('sync/status/', SyncStatusView.as_view(), name='sync-status'),
    path('customers/', CustomerListView.as_view(), name='customers'),
    path('invoices/', InvoiceListView.as_view(), name='invoices'),
]
