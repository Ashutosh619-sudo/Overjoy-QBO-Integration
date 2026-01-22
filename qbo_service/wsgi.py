"""
WSGI config for QBO Ingestion Service.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'qbo_service.settings')

application = get_wsgi_application()
