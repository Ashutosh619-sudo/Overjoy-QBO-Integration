"""
URL configuration for QBO Ingestion Service.
"""

from django.urls import path, include

urlpatterns = [
    # QBO Ingestion API
    path('api/qbo/', include('apps.qbo_ingestion.urls')),
]
