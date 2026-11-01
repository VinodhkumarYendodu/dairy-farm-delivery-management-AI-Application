# Dairy AI Subscription Management

Local-first Windows application for dairy subscription operations. Phases 1–10 are implemented. The configured SQL Server is `(localdb)\MSSQLLocalDB`.

## Requirements

- Python 3.14 (detected in the current workspace as 3.14.6; the `py` launcher is not installed)
- Microsoft ODBC Driver 17 for SQL Server for SQL connectivity
- SQL Server LocalDB instance `(localdb)\MSSQLLocalDB` using the supplied `MSSQL_CONNECTION_STRING` in `.env`
- Ollama is optional; install models manually when needed
- Docker Desktop is optional for n8n

Requirements include `fastapi`, `uvicorn[standard]`, `pydantic-settings`, `email-validator`, `pyodbc`, `httpx`, `pytest`, `faiss-cpu`, `pypdf`, `pandas`, and `openpyxl`. They are installed in the project `.venv` on Python 3.14.6.

## Setup (PowerShell)

```powershell
Set-Location D:\Projects\dairy-ai-subscriptions
python --version
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Windows Authentication is enabled by default. `MSSQL_CONNECTION_STRING` follows the pattern used in the Expense Tracker project: ODBC Driver 17, `(localdb)\MSSQLLocalDB`, the `DairySubscriptionDB` database, and `Trusted_Connection=yes`. Set it in the environment or `.env`; the app forces the configured `DB_DATABASE` into that connection string. The local ODBC 17 connection uses the driver's default encryption behavior. If you enable encryption later, use a certificate trusted by Windows outside local development.

Check local prerequisites without connecting to SQL or downloading models:

```powershell
python scripts/check_environment.py
```

## Run the API and UI

Create the configured project database and apply versioned schema migrations:

```powershell
.\.venv\Scripts\python.exe scripts/migrate_database.py
```

This creates only `DairySubscriptionDB` if it does not exist and then applies pending scripts from `database/migrations`. Rerunning the command skips recorded migrations. It does not insert invented product, route, customer, price, or stock values.

Phase 2 API endpoints cover customer CRUD/deactivation, products and status, effective-dated product prices, and delivery routes. Phase 3 adds daily availability, stock commitments, and confirmed subscription proposals. Phase 4 adds delivery generation and status tracking. Phase 5 adds charges, manual payments, allocations, customer adjustments, and ledgers. Phase 6 adds the local intent-based AI assistant. Open `/docs` for request schemas. The HTML/CSS/JavaScript interface and API are served together by FastAPI.

Run the app and API in one process:

```powershell
.\scripts\run_api.ps1
```

Open `http://127.0.0.1:8000/` for the app, `http://127.0.0.1:8000/api/health` for health, or `http://127.0.0.1:8000/docs` for API schemas.

The SQL health check performs only `SELECT 1`. Ollama health checks `/api/tags`; they never download models. To install models manually, use `ollama pull llama3.2:3b` and `ollama pull qwen3-embedding:0.6b`.

## Local n8n (optional)

```powershell
Copy-Item .env.n8n.example .env.n8n
# Edit .env.n8n and replace the placeholder with a unique long random key.
docker compose --env-file .env.n8n -f docker-compose.n8n.yml up -d
```

Open `http://127.0.0.1:5678`. Stop n8n without deleting persistent data:

```powershell
docker compose --env-file .env.n8n -f docker-compose.n8n.yml down
```

The compose file pins n8n to `2.45.6`; update it deliberately after validating an upgrade. The Phase 7 workflow and Gmail OAuth setup are documented below.

## Phase 2 master data

- Customers: create, search, view, edit, and deactivate. Historical records are retained.
- Products: create, activate/deactivate, and maintain effective-dated prices; prices are stored as `DECIMAL` values.
- Delivery routes: create and list routes for customer assignment.
- Audit logs: record master-data changes without copying customer contact details into the audit summary.
- Seed imports: provide your own JSON values; there are no built-in example prices, routes, or customers.

Example import shape (replace every placeholder with approved business data):

```json
{
  "routes": [{"route_name": "YOUR_ROUTE", "description": null}],
  "products": [{"product_code": "YOUR_CODE", "product_name": "YOUR_PRODUCT", "unit_of_measure": "litre"}],
  "customers": [{"customer_code": "YOUR_CUSTOMER_CODE", "full_name": "CUSTOMER_NAME", "mobile": "MOBILE", "address": "DELIVERY_ADDRESS", "preferred_contact_method": "PHONE"}]
}
```

Validate without writing with `python scripts/seed_master_data.py path\to\master-data.json`. Add `--apply` to insert the supplied values after review.

For a clearly marked local sample dataset, preview with `python scripts/seed_demo_chennai.py` and apply with `python scripts/seed_demo_chennai.py --apply`. It creates demo routes in Adyar, Velachery, and Anna Nagar; three demo products with illustrative prices; fictional demo customers using `.invalid` email addresses; and seven days of demo stock. It does not create subscriptions, deliveries, charges, payments, or notification jobs. Re-running skips existing demo records and availability rows.

The ODBC connection uses Driver 17, LocalDB, and Windows Authentication, matching the provided connection details. The generated application connection also selects `DairySubscriptionDB`; the bootstrap step connects to `master` only to create that database. LocalDB must be able to start under the current Windows account.

## Phase 3 availability and subscriptions

Migration `002_availability_subscriptions.sql` creates daily availability, subscriptions, selected weekdays, and status history. Apply pending migrations with `python scripts/migrate_database.py`; the runner skips migrations already recorded. This command uses the configured LocalDB connection.

The Daily Availability and Subscriptions page supports availability entry, proposal creation, recording a customer decision, viewing shortages, and retrying stock validation for confirmed waitlisted proposals. API endpoints are `GET/POST /api/v1/availability`, `GET/POST /api/v1/subscriptions`, `POST /api/v1/subscriptions/{id}/confirm`, `POST /api/v1/subscriptions/{id}/approve`, and `GET /api/v1/subscriptions/{id}/history`.

Proposal date ranges must be finite and inclusive. Selected weekdays use ISO numbering (Monday=1 through Sunday=7). Confirmation automatically validates every delivery date. Missing availability is treated as zero stock. Approval locks the date/product availability keys in a SQL Server `SERIALIZABLE` transaction, checks all committed subscriptions, then records the status change and history atomically. Availability edits below approved commitments are rejected. Unit price is snapshotted from the effective price on the proposal start date when one exists; no price is invented when none exists.

Waitlist priority, expiry, holidays, Sunday rules, and same-day cutoffs remain business decisions. Phase 3 does not implement schedule amendments or cancellation; those are not used to free stock in this phase.

## Phase 4 delivery planning

Migration `003_deliveries.sql` creates delivery records with a unique subscription/date constraint. Apply pending migrations with `python scripts/migrate_database.py`. `POST /api/v1/deliveries/generate` accepts an inclusive date range and creates records only for approved subscription dates. It is idempotent, records generated deliveries in the audit log, and uses serializable transactions plus key-range locks and the unique constraint to prevent duplicates. `GET /api/v1/deliveries` supports date, route, customer, and status filters; `PATCH /api/v1/deliveries/{id}` updates delivery status, quantity, or notes.

The Delivery Planning page supports generation, route-wise lists, and status updates for `PLANNED`, `OUT_FOR_DELIVERY`, `DELIVERED`, `MISSED`, and `CANCELLED`. Delivered quantity defaults to planned quantity when marking a delivery delivered. Correcting a delivered, missed, or cancelled delivery requires a reason and is audited. Cancelling a subscription marks its future planned deliveries cancelled while retaining completed and past records; generation ignores cancelled subscriptions. Delivery route is snapshotted from the customer's assigned route when generated. Updates are available at `PATCH /api/v1/deliveries?delivery_id=...` and the resource form `PATCH /api/v1/deliveries/{delivery_id}`.

## Phase 5 billing and manual payments

Migration `004_billing_payments.sql` creates customer charges, payments, payment allocations, and auditable customer adjustment/refund entries. Apply pending migrations with `python scripts/migrate_database.py`. `POST /api/v1/charges/generate` creates one charge per delivered delivery and is idempotent. It uses the subscription unit-price snapshot when available, otherwise the effective product price on the delivery date; deliveries without an applicable price are reported and skipped. Charge amounts use Python `Decimal` and round half-up to two currency decimals.

`POST /api/v1/payments` records cash, bank transfer, UPI, or other manual payments. Optional allocations are user-supplied per charge, can be partial, cannot exceed the payment amount or charge balance, and cannot cross customer accounts. Payment references are unique when provided. Any unallocated remainder remains account credit and is not automatically assigned to charges. `GET /api/v1/customers/{id}/ledger` reports charges, payments, adjustments, outstanding balance, unallocated credit, and open per-charge balances. Financial amounts are returned as exact strings in these API responses.

The Payments page supports charge generation, manual recording/allocation, and reasoned debit/credit adjustments or refund ledger entries. A refund entry updates the local ledger only; it does not execute a cash refund. The Customer Ledger page shows the account balance and open charges. Tax, billing cycles, statements/receipt exports, and automatic payment allocation remain unimplemented decisions/features.

## Phase 6 local AI assistant

The AI Assistant page sends standalone questions to `POST /api/v1/ai/chat`. Ollama uses the configured local chat model (`llama3.2:3b`). The model can choose only from fixed read-only intents: active subscription count, today's scheduled demand by product, pending confirmations, outstanding balances, monthly delivered charges, and delivered route volume. Monthly charges default to the previous calendar month; route volume defaults to the current month. Both can use a custom date range. Product filters must match one active product.

The API validates the model's JSON intent plan against a strict schema, then calls predefined reporting services and parameterized SQL repositories. Model output never becomes SQL or a write action. Customer-provided text included in results is treated as data; only required report fields are sent for explanation. The response includes the structured results along with the model's concise explanation. If Ollama is unavailable, AI chat reports the dependency error while ordinary API and application business operations remain available. Startup never downloads models.

Verify manually with `ollama list`; install the chat model only when you choose using `ollama pull llama3.2:3b`. The assistant currently handles each question independently; it does not use previous chat messages to resolve follow-up references. AI endpoint: `POST /api/v1/ai/chat` with `{"question":"How many subscriptions are active?"}`.

## Phase 7 email automation

Migration `005_notification_outbox.sql` creates the durable outbox with a unique deduplication key, state tracking, retry schedule, provider response, and failure details. Apply pending migrations with `python scripts/migrate_database.py`. Subscription proposal/decision, cancellation, missed-delivery, payment receipt, and manually queued monthly statement events are persisted in the same database transaction as their business event. A missing customer email produces a visible `SKIPPED` item. External delivery failure does not undo a committed business transaction.

The `Email / Workflow Status` application page shows integration/outbox status and provides explicit controls for processing pending messages. No messages are automatically sent when events are created. Processing stays disabled until `N8N_WEBHOOK_URL` points to the active local workflow. A connection failure is retried with backoff; a timeout, server error, or expired worker lease is marked `REQUIRES_REVIEW` because delivery may already have happened. Retrying that state requires explicit acknowledgment that a duplicate email may result. Failed messages can also be queued for retry. Monthly statements are queued per customer and calendar month; repeated requests deduplicate to the existing notification.

### Configure Gmail through n8n

1. Start n8n with the local Docker Compose instructions above and open `http://127.0.0.1:5678`.
2. Import `integrations/n8n/dairy_notifications_workflow.json`.
3. In n8n, create a Gmail OAuth2 credential named `Dairy Gmail OAuth2`, complete Google's OAuth flow, and select it on the Gmail node. OAuth tokens remain in n8n's encrypted store, not this repository.
4. Activate the workflow and copy its production webhook URL, normally `http://127.0.0.1:5678/webhook/dairy-notifications`.
5. Set `N8N_WEBHOOK_URL` in the application `.env`, restart FastAPI, then check the Email / Workflow Status page.
6. Process a notification only after reviewing the outbox. This operation sends email through Gmail.

The workflow responds successfully only after Gmail completes its send node. The application currently puts an aggregate monthly statement summary in the email; a PDF attachment/export is outside this phase. Do not put credentials, OAuth tokens, or the n8n encryption key in this repository.

### Phase 8 local document knowledge base

Migration `006_documents_rag.sql` adds the document catalog and extracted text chunks in SQL Server. Run `python scripts/migrate_database.py` where LocalDB connectivity is available. Documents and a persisted FAISS index are stored locally at `DOCUMENT_STORAGE_PATH` and `FAISS_INDEX_PATH`; these runtime directories are ignored by Git. Uploads are limited to PDF, Markdown, or UTF-8 plain text and default to a 10 MB maximum. Encrypted PDFs, empty or unreadable documents, and files with common credential/private-key patterns are rejected. Scanned image-only PDFs need OCR and are not supported. No credentials or unrelated personal documents should be uploaded.

Indexing uses the configured local Ollama embedding model (`qwen3-embedding:0.6b`). Ask-answer generation uses `llama3.2:3b`. Install these models manually with Ollama; the application never downloads them. If either model is unavailable, indexing/search reports the local dependency issue and normal business operations remain usable. Search uses normalized vectors and local inner-product similarity. It uses FAISS where native wheels are supported and an exact NumPy index on Windows to avoid native DLL initialization failures. Answers are constrained to retrieved excerpts; each source includes a document, chunk number, and excerpt. If no relevant passage is found, the assistant says the indexed material is insufficient. Retrieved text is untrusted and cannot override the assistant rules or trigger business actions.

The Document Knowledge Base application page uploads, lists, re-indexes, deletes, and queries documents. API routes are `POST /api/v1/documents` (multipart field `file`), `GET /api/v1/documents`, `POST /api/v1/documents/ask` (`{"question":"..."}`), `POST /api/v1/documents/{id}/reindex`, and `DELETE /api/v1/documents/{id}`. Deletion removes the source file, SQL chunks, metadata, and rebuilds the local FAISS index.

## Phase 9 dashboard and reports

The Dashboard and Reports page presents active customers and subscriptions, pending confirmations, current outstanding balance, billed sales, collected payments, daily demand/stock, and delivery status. Dashboard sales are delivered customer charges; collections are payments received. They are separate values. Availability shows entered stock alongside approved commitments and remaining quantity. Depletion warnings appear when entered stock has no remaining quantity; no undocumented low-stock threshold is assumed.

Filtered reports cover availability/utilization, scheduled demand, delivered sales/charges, collections summarized by date and payment method, route summaries, customer master data, subscriptions, deliveries, customer ledger, outstanding balances, payments, and notifications. Date ranges are bounded to 366 inclusive days. Outstanding balances are current account balances; ledger rows may be filtered by period and show the account balance separately from the period net change. Demand is an estimate from approved subscription schedules, not confirmed stock or actual sales.

API routes are `GET /api/v1/reports/dashboard` and `GET /api/v1/reports/{availability|demand|sales|collections|routes|customers|subscriptions|deliveries|ledger|outstanding|payments|notifications}`. Report filters include `from_date`, `through_date`, and relevant customer/product/route/status fields. Add `format=csv` or `format=xlsx` to download a report; the default is JSON. Financial values are kept as decimal strings in JSON/CSV and exported as numeric Excel cells.

The report page uses the FastAPI API only and provides CSV and Excel download buttons. Excel exports use pandas and openpyxl; there is no dependency on cloud reporting services.

## Tests

```powershell
python -m pytest
```

## Phase 10 hardening and local deployment

The customer workspace includes a product assistant, customer-confirmed delivery scheduling, individual delivery changes before the configured SLA cutoff, and issue reports with optional JPG/PNG/WEBP photos (8 MB maximum). Customer issue records are persisted by migration `008_customer_support.sql`; photos are stored locally in `CUSTOMER_ISSUE_STORAGE_PATH` and are included in local backups. Admins and agents can review the support queue in **Customer issues**. Product answers use the active catalog and the local Ollama model when available; catalog-backed answers remain available when Ollama is offline.

The application and app bind to localhost; configuration rejects non-local Ollama/n8n URLs and unsafe database identifiers. Business API routes require bearer authentication. Admin, agent, and customer roles are enforced in the API, with customer data scoped to the linked account. Keep the application on this local PC and do not expose it to a network. SQL health output is sanitized so failed connection details cannot expose a supplied connection string.

Rotating logs are written to `LOG_DIRECTORY` (default `./logs`), limited by `LOG_MAX_BYTES` (default 2 MB) and `LOG_BACKUP_COUNT` (default five backups). Logs do not include request bodies or customer records. The strict environment check verifies required packages, the ODBC driver, local binding, and absence of SQL passwords without contacting SQL Server, Ollama, or downloading models:

```powershell
.\.venv\Scripts\python.exe scripts/check_environment.py --strict
```

### Start the application

Copy `.env.example` to `.env`, review the LocalDB and storage settings, then open a PowerShell terminal in the project folder:

```powershell
.\scripts\run_api.ps1
```


The app and API listen together at `127.0.0.1:8000`. For development reload, use `scripts/run_api.ps1 -Reload`. Ctrl+C stops the foreground process.

### Back up and restore

Create a single ZIP backup containing a SQL Server copy-only/checksummed `.bak`, local documents, FAISS index, customer issue photos, and a SHA-256 manifest:

```powershell
.\.venv\Scripts\python.exe scripts/backup_local.py
```

Backups are written to `BACKUP_DIRECTORY` (default `./backups`), which is excluded from Git. They contain customer and financial information; protect copies with Windows disk encryption and store them in a controlled location. Backup retention and off-device copy schedules are operator responsibilities. n8n credentials are stored separately in its Docker volume and are not included in this application backup.

Restore validates archive paths and checksums, writes local files to a new folder, and restores SQL into a **new database name**. It refuses to overwrite either an existing restore folder or database. It does not alter `.env`:

```powershell
.\.venv\Scripts\python.exe scripts/restore_local.py .\backups\dairy_backup_TIMESTAMP.zip --database-name DairySubscriptionDB_RestoreCheck
```

Inspect the restored database and files before switching `DB_DATABASE`, `DOCUMENT_STORAGE_PATH`, and `FAISS_INDEX_PATH` in `.env`. The restored data folder and database are separate from the live application state. For routine recovery, restore first to a validation name, verify the data, then plan any cutover separately.

Dependency review: `faiss-cpu` is pinned to tested Windows/Python 3.14 wheel `1.13.2`. The current requirements audit found no known vulnerabilities. Install the review tool from the development requirements and re-run it before dependency updates:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\pip-audit.exe -r requirements.txt
```

The project environment checker covers all runtime packages. Re-run `python -m pip install -r requirements.txt` after dependency changes and review advisories before updating pins.

Tax treatment, missed-delivery chargeability, payment allocation order, and cash refund handling still need business decisions.

## Account logins and roles

Sign-in is required for all business API endpoints and application pages. Accounts use three roles:

- **Admin** can manage customer and agent logins, all operational data, products, prices, and routes.
- **Agent** can manage customer records and day-to-day availability, subscriptions, deliveries, payments, reports, and documents. Product, price, route, and account administration is restricted to admins.
- **Customer** can view only the linked customer profile, subscriptions, deliveries, and ledger. Customer logins cannot access staff APIs or other customers' records.

Passwords are stored as salted PBKDF2-HMAC-SHA256 hashes. Bearer tokens are random, stored only as hashes in SQL Server, and expire after eight hours. Five consecutive failed logins temporarily lock the account. Users can change their password from Home; changing it revokes existing sessions. Admins can deactivate accounts, which also revokes their sessions.

After applying the authentication migration, create the initial administrator interactively so the password is not placed in shell history. In PowerShell, run:

    .\.venv\Scripts\python.exe scripts/migrate_database.py --no-create
    .\.venv\Scripts\python.exe scripts/create_admin.py

The bootstrap command refuses to create another administrator after one exists. Sign in and use **User access** to create admin, agent, and customer logins; customer accounts must link to an existing active customer record. Give each person a temporary password and have them change it after signing in. The application remains restricted to localhost; this login feature does not make the app safe to expose on a network or the public internet.

