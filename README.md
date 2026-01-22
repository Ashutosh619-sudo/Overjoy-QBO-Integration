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

The service assumes things will go wrong and tries to handle failures gracefully.

### API errors

Transient errors (rate limits, server errors, network issues) trigger automatic retries with backoff. Rate limits use exponential backoff (1s, 2s, 4s). Server and network errors use linear backoff (1s, 2s, 3s). Client errors like 400 or 404 fail immediately since retrying won't help.

### Partial sync failures

If a sync fails midway through processing batches, the checkpoint is not updated. The next sync attempt will re-query from the previous checkpoint. Since upserts are idempotent, re-processing records that were already saved doesn't cause duplicates.

### Token expiration

Access tokens expire after about an hour. The service checks token expiry before each API call and refreshes proactively (5 minutes before expiration) rather than waiting for a failure.

If the refresh token itself is rejected (invalid_grant error), the account is flagged and skipped in future syncs until re-authorized.

### Sync state tracking

Each sync attempt records:
- When it started
- Whether it succeeded or failed
- The error message if it failed
- The checkpoint if it succeeded

This makes it easy to see which accounts are healthy and which need attention.

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

**Webhooks instead of polling**: QBO supports webhooks for real-time notifications. This would reduce API calls and latency compared to polling every 5 minutes. The challenge is webhook verification and handling out-of-order events.

**Token encryption**: Access and refresh tokens are stored as plain text. In production, these should be encrypted at rest using something like Fernet or a KMS.

**Rate limit handling**: The current implementation does basic backoff, but QBO has specific rate limits that could be tracked more precisely. A token bucket or sliding window approach would be more robust.

**Monitoring and alerting**: Add metrics for sync duration, record counts, and failure rates. Alert when an account has consecutive failures or hasn't synced successfully in a while.

**Configuration-driven sync**: Right now, syncing customers and invoices is hardcoded. A registry pattern would make it easy to add new object types without changing the sync engine.

**Testing**: The codebase needs unit tests for the SDK, integration tests for the sync engine, and end-to-end tests with mocked QBO responses.
