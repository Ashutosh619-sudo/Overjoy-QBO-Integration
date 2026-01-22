"""
Django management command to run continuous sync service.

Usage:
    python manage.py qbo_run_sync           # Continuous sync
    python manage.py qbo_run_sync --once    # Single sync cycle
"""

import signal
import time
import logging
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from apps.qbo_ingestion.models import QBOAccount
from apps.qbo_ingestion.sync_engine import SyncEngine

logger = logging.getLogger(__name__)
shutdown_requested = False


def signal_handler(signum, frame):
    global shutdown_requested
    logger.info(f"Received signal {signum}, shutting down...")
    shutdown_requested = True


class Command(BaseCommand):
    help = 'Run the continuous QBO sync service'
    
    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Single sync cycle')
    
    def handle(self, *args, **options):
        global shutdown_requested
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        self.stdout.write(self.style.NOTICE('='*60))
        self.stdout.write(self.style.NOTICE('QuickBooks Online Sync Service'))
        self.stdout.write(self.style.NOTICE('='*60))
        self.stdout.write(f"Poll interval: {settings.SYNC_POLL_INTERVAL}s")
        
        if not settings.QBO_CLIENT_ID or not settings.QBO_CLIENT_SECRET:
            raise CommandError("QBO credentials not configured")
        
        if not QBOAccount.objects.exists():
            self.stdout.write(self.style.WARNING("\nNo accounts configured!"))
            if options['once']:
                return
        
        engine = SyncEngine()
        
        if options['once']:
            self._run_cycle(engine)
            return
        
        self.stdout.write("\nStarting continuous sync... (Ctrl+C to stop)\n")
        
        while not shutdown_requested:
            try:
                self._run_cycle(engine)
                
                if shutdown_requested:
                    break
                
                next_sync = datetime.utcnow().timestamp() + settings.SYNC_POLL_INTERVAL
                self.stdout.write(f"Next sync at {datetime.fromtimestamp(next_sync).isoformat()}")
                
                while not shutdown_requested and time.time() < next_sync:
                    time.sleep(1)
                    
            except KeyboardInterrupt:
                break
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error: {e}"))
                if not shutdown_requested:
                    time.sleep(60)
        
        self.stdout.write(self.style.SUCCESS("\nShutdown complete"))
    
    def _run_cycle(self, engine):
        start = datetime.utcnow()
        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"Sync cycle started at {start.isoformat()}")
        
        results = engine.sync_all_accounts()
        
        success = sum(1 for r in results if r.get('success'))
        customers = sum(r.get('customers', {}).get('count', 0) for r in results if r.get('customers', {}).get('status') == 'success')
        invoices = sum(r.get('invoices', {}).get('count', 0) for r in results if r.get('invoices', {}).get('status') == 'success')
        
        duration = (datetime.utcnow() - start).total_seconds()
        
        self.stdout.write(f"Completed in {duration:.1f}s")
        self.stdout.write(f"  Accounts: {success}/{len(results)}")
        self.stdout.write(f"  Customers: {customers}, Invoices: {invoices}")
