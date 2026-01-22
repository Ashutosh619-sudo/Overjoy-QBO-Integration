# QBO Ingestion Service

A Django service that syncs Customers and Invoices from QuickBooks Online into a local database. It handles OAuth authentication, incremental data sync, and gracefully recovers from failures.

## Setup

### Prerequisites

- Python 3.10+
- A QuickBooks Developer account with a sandbox app

### Installation

```bash
cd Overjoy-QBO-Integration

# Create virtual environment
python3 -m venv env
source env/bin/activate

# Install dependencies
pip3 install -r requirements.txt

# Copy environment file
cp env.example.txt .env
```

### Configuration

Edit `.env` with your QBO app credentials:

```
QBO_CLIENT_ID=your_client_id
QBO_CLIENT_SECRET=your_client_secret
QBO_ENVIRONMENT=sandbox
```

You can find these in your Intuit Developer dashboard under your app's Keys & credentials.

### Database Setup

```bash
python manage.py migrate
```

This creates a SQLite database with tables for accounts, customers, invoices, and sync state.

### Running the Service

Start the API server:

```bash
python manage.py runserver
```

In a separate terminal, start the background sync process:

```bash
python manage.py qbo_run_sync
```

This polls QBO every 5 minutes for new and updated records.

## Authorization

The service uses OAuth 2.0 with the authorization code flow. Since QBO requires user consent through their UI, we rely on the OAuth Playground to bootstrap the connection.

### How it works

1. Go to the [QBO OAuth Playground](https://developer.intuit.com/app/developer/playground)
2. Select your app and click "Get authorization code"
3. Authorize a sandbox company when prompted
4. Copy the authorization code and realm ID from the playground

Then exchange these for tokens via the API:

```bash
curl -X POST http://localhost:8000/api/qbo/authorize/ \
  -H "Content-Type: application/json" \
  -d '{
    "code": "AUTH_CODE_FROM_PLAYGROUND",
    "realm_id": "REALM_ID_FROM_PLAYGROUND",
    "redirect_uri": "https://developer.intuit.com/v2/OAuth2Playground/RedirectUrl"
  }'
```

The service exchanges this code for access and refresh tokens, stores them in the database, and automatically refreshes the access token when it expires. QBO rotates refresh tokens on each use, so the service always persists the latest one.

If a refresh token becomes invalid (user revoked access, token expired after 100 days of inactivity), the account is marked as needing re-authorization.

## Incremental Syncing

The service uses timestamp-based incremental sync rather than fetching all records every time.

Every QBO object has a `MetaData.LastUpdatedTime` field. After each successful sync, we store the maximum timestamp we processed as a checkpoint. On the next sync, we query only for records where `LastUpdatedTime > checkpoint`.

For a new account with no checkpoint, the first sync fetches everything. Subsequent syncs only fetch what changed.

The sync state is tracked per account and per object type. If customer sync succeeds but invoice sync fails, they maintain independent checkpoints. The invoice sync will retry from its last checkpoint without re-fetching customers.

Records are upserted using the QBO object ID as the unique key. Processing the same record twice just updates it rather than creating duplicates.

## Failure Handling

The service is built with the assumption that failures are inevitable in distributed systems. Network issues, API rate limits, token expirations, and temporary service outages are all expected. Rather than failing catastrophically, the service implements multiple layers of resilience to ensure data consistency and minimize data loss.

### Design Philosophy

**Fail-safe, not fail-fast**: The service prioritizes data integrity and recovery over immediate failure. When something goes wrong, it:
- Preserves all successfully processed data
- Records detailed error information for debugging
- Automatically retries transient failures
- Resumes from the last known good state on the next attempt

**Isolation**: Failures in one account or object type don't affect others. If customer sync fails for Account A, invoice sync for Account A still proceeds, and Account B's syncs are unaffected.

### API Error Handling

The SDK implements intelligent retry logic at the HTTP request level, categorizing errors and applying appropriate strategies:

**Retryable Errors (with backoff)**:
- **Rate Limits (429)**: Uses exponential backoff (1s, 2s, 4s) to respect QBO's rate limits. The service automatically waits longer between retries to avoid overwhelming the API.
- **Server Errors (5xx)**: Uses linear backoff (1s, 2s, 3s) for transient server issues. These are typically temporary infrastructure problems that resolve quickly.
- **Network Errors**: Connection timeouts, DNS failures, and other network issues use linear backoff. The service assumes these are temporary connectivity problems.

**Non-retryable Errors (fail immediately)**:
- **Client Errors (4xx)**: Errors like 400 (Bad Request) or 404 (Not Found) indicate problems with the request itself. Retrying won't help, so the service fails immediately to avoid wasting time and API quota.
- **Authentication Errors (401)**: Invalid or expired tokens are handled separately through the token refresh mechanism.

**Configuration**: Retry behavior is configurable via environment variables:
- `SYNC_MAX_RETRIES` (default: 3): Maximum number of retry attempts
- `SYNC_RETRY_DELAY` (default: 5s): Base delay for backoff calculations

### Partial Sync Failures

The sync process processes records in batches. If a failure occurs midway through, the service ensures no data is lost:

**Checkpoint Management**:
- Checkpoints are only updated after a batch is **completely** processed and committed to the database
- If a sync fails after processing 500 of 1000 records, the checkpoint remains at the previous value
- The next sync automatically resumes from the last successful checkpoint, re-querying those 500 records

**Idempotent Upserts**:
- All database operations use upserts based on QBO object IDs
- Re-processing the same record multiple times simply updates it rather than creating duplicates
- This makes retries safe: even if a record was partially processed before a failure, re-processing it completes the operation correctly

**Transaction Boundaries**:
- Each batch is processed within a database transaction
- If any record in a batch fails, the entire batch is rolled back
- This prevents partial batches from being saved, maintaining data consistency

**Independent Object Type Syncs**:
- Customer and invoice syncs maintain separate checkpoints
- If customer sync succeeds but invoice sync fails, customers are saved and the invoice checkpoint is not updated
- The next sync will skip customers (already up-to-date) and retry invoices from the last checkpoint

### Token Expiration and Refresh

OAuth tokens have limited lifespans and require careful management:

**Proactive Token Refresh**:
- Access tokens expire after approximately 1 hour
- The service checks token validity before **every** API call
- Tokens are refreshed proactively 5 minutes before expiration (configurable via `TOKEN_REFRESH_BUFFER`)
- This prevents API calls from failing due to expired tokens

**Refresh Token Rotation**:
- QBO rotates refresh tokens on each use for security
- The service automatically persists the new refresh token to the database via a callback mechanism
- This ensures the latest token is always available for future refreshes

**Refresh Token Failures**:
- If a refresh token is rejected (e.g., user revoked access, token expired after 100 days of inactivity), QBO returns an `invalid_grant` error
- The service immediately marks the account as `is_token_expired = True`
- Expired accounts are automatically skipped in future sync cycles
- The account remains in the database with its sync state intact, ready for re-authorization
- Re-authorization can be done via the `/api/qbo/authorize/` endpoint without losing historical data

### Sync State Tracking

Every sync attempt is recorded in the database for monitoring and debugging:

**Per-Object-Type State**:
- Each account has separate `SyncState` records for customers and invoices
- Each state tracks:
  - **Status**: `pending`, `in_progress`, `success`, or `failed`
  - **Last attempt time**: When the sync was last attempted
  - **Last success time**: When the sync last succeeded
  - **Checkpoint**: The timestamp of the most recent successfully processed record
  - **Consecutive failures**: Count of failed attempts in a row
  - **Error message**: The most recent error message (if failed)

**Benefits**:
- **Visibility**: You can see exactly which accounts and object types are healthy
- **Debugging**: Error messages provide context for why syncs failed
- **Monitoring**: Consecutive failure counts help identify accounts that need attention
- **Resume capability**: Checkpoints ensure syncs can resume from the right point

**Example**: If an account shows `consecutive_failures: 3` for invoices, you know the invoice sync has been failing repeatedly and may need investigation or re-authorization.

### Account-Level Failure Isolation

When syncing multiple accounts, failures are isolated:

**Independent Processing**:
- Each account syncs independently in a try-catch block
- If Account A's sync fails, Account B's sync still proceeds
- Failed accounts are logged but don't stop the sync cycle

**Error Reporting**:
- The sync engine returns detailed results for each account
- Failed accounts include error messages and status for each object type
- This allows you to identify problematic accounts without affecting healthy ones

**Graceful Degradation**:
- The service continues operating even if some accounts are failing
- Healthy accounts continue syncing on schedule
- Problematic accounts can be fixed (re-authorized, debugged) without service downtime

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /api/qbo/authorize/ | Exchange auth code for tokens |
| GET | /api/qbo/accounts/ | List connected accounts |
| POST | /api/qbo/sync/ | Trigger sync manually |
| GET | /api/qbo/sync/status/ | Check sync status |
| GET | /api/qbo/customers/?realm_id=X | List synced customers |
| GET | /api/qbo/invoices/?realm_id=X | List synced invoices |

### Postman Collection

You can import the Postman collection to test all API endpoints:

[**Import Postman Collection**](https://grey-star-778986.postman.co/workspace/New-Team-Workspace~b100db5c-4fbd-4e2b-8948-d177990815b2/request/27740702-d4a87827-fcfc-4252-983e-2641be60ec25?action=share&creator=27740702&ctx=documentation)

## Project Structure

```
qbo-ingestion-service/
├── qbo_service/           # Django project settings
├── apps/qbo_ingestion/
│   ├── models.py          # Database models
│   ├── views.py           # API endpoints
│   ├── sync_engine.py     # Sync orchestration
│   ├── qbo_client.py      # Django/QBO integration
│   └── sdk/               # QBO API client
│       ├── __init__.py    # OAuth handling
│       ├── apis/          # API resources
│       └── exceptions.py  # Error types
└── manage.py
```

The SDK layer is intentionally separate from Django. It handles HTTP requests, pagination, and retries without any Django dependencies. The qbo_client module bridges the SDK with Django settings and database persistence.

## What I Would Improve

Given more time, here's what I'd focus on:

**Async sync API**: The `POST /api/qbo/sync/` endpoint currently runs synchronously, meaning the HTTP request blocks until the entire sync completes. For accounts with thousands of records, this can take minutes and risks timeouts. A better approach would be to queue the sync job and return immediately with a job ID. The client could then poll a status endpoint or receive a webhook when complete.

**Distributed sync scheduling**: Currently all accounts sync together every 5 minutes, which creates a thundering herd problem at scale. A better approach would store a `next_sync_at` timestamp per account and spread syncs evenly across the interval. This avoids bursts of API calls that could trigger rate limits.

**Background task queue**: The current approach runs sync in a polling loop. A proper setup would use Celery with Redis or RabbitMQ for scheduled tasks. This would make it easier to scale horizontally and handle failures with dead-letter queues.

**Support for deleted entities**: The last_modified_date approach doesn't get the deleted data from QBO, we will have to use CDC if in future we need to do something to deleted entities. 

**Webhooks instead of polling**: QBO supports webhooks for real-time notifications. This would reduce API calls and latency compared to polling every 5 minutes. The challenge is webhook verification and handling out-of-order events.

**Token encryption**: Access and refresh tokens are stored as plain text. In production, these should be encrypted at rest using something like Fernet or a KMS.

**Rate limit handling**: The current implementation does basic backoff, but QBO has specific rate limits that could be tracked more precisely. A token bucket or sliding window approach would be more robust.

**Monitoring and alerting**: Add metrics for sync duration, record counts, and failure rates. Alert when an account has consecutive failures or hasn't synced successfully in a while.

**Configuration-driven sync**: Right now, syncing customers and invoices is hardcoded. A registry pattern would make it easy to add new object types without changing the sync engine.

**Testing**: The codebase needs unit tests for the SDK, integration tests for the sync engine, and end-to-end tests with mocked QBO responses.
