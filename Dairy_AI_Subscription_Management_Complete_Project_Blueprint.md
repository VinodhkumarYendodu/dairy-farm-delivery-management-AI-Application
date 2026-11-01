# Dairy AI Subscription Management System
## Complete Project Blueprint and Codex Implementation Specification

**Project path:** `C:\Projects\dairy-ai-subscriptions`  
**Deployment:** Local Windows PC  
**Primary stack:** Streamlit, Python, FastAPI, SQL Server, Ollama, n8n, FAISS  
**Implementation approach:** Build and test one phase at a time with Codex.

This document describes the complete target project. It is not an instruction to build every feature in one pass. Implement the phases in order and stop for user approval after each phase.

---

## 1. Business objective

Create a local-first dairy subscription application to manage customers, milk products, daily stock availability, recurring subscriptions, customer confirmations, automatic stock-based approval, delivery planning, manual payments, email notifications, reports, and a local AI assistant.

The core application and AI must run locally. Gmail/Google Workspace is an external service used only for email delivery after the integration is configured.

### Main capabilities

1. Customer and delivery-address management.
2. Configurable milk products and prices.
3. Daily availability by milk product.
4. Daily and selected-weekday subscriptions.
5. Customer confirmation before approval.
6. Automatic approval only when stock is available for all applicable delivery dates.
7. Waitlist/review outcome when stock is insufficient.
8. Daily delivery planning and delivery status tracking.
9. Manual payment recording, billing, customer ledger, and outstanding balances.
10. Email notifications through local n8n workflows and Gmail/Google Workspace.
11. Local Ollama AI assistant for questions about business data.
12. Local document search (RAG) using Ollama embeddings and FAISS.
13. Streamlit dashboards, reports, and Excel exports.

## 2. Confirmed technology decisions

| Component | Technology |
|---|---|
| OS | Windows |
| IDE | VS Code + Codex |
| Frontend | Streamlit |
| Backend | Python + FastAPI |
| Database | Microsoft SQL Server |
| SQL authentication | Windows Authentication where available |
| SQL driver | `pyodbc` + Microsoft ODBC Driver 18 |
| Local LLM runtime | Ollama |
| Chat model | `llama3.2:3b` |
| Embedding model | `qwen3-embedding:0.6b` |
| Vector search | FAISS |
| Data processing | pandas |
| Excel | openpyxl |
| Charts | Plotly |
| Workflow automation | n8n via Docker |
| Email | Gmail / Google Workspace OAuth2 |
| Deployment | Local Windows PC |

Use the existing Python 3.14 environment initially. Check package compatibility before installing. If a required package does not support Python 3.14, report the issue and propose a project-local supported version; do not silently modify global Python.

## 3. Architecture

```text
Streamlit UI (localhost:8501)
        |
        v
FastAPI backend (localhost:8000)
  |       |          |
  |       |          +--> n8n (localhost:5678) --> Gmail/Workspace
  |       |
  |       +--> Ollama (localhost:11434)
  |                |
  |                +--> Chat model
  |                +--> Embedding model --> FAISS document index
  |
  +--> SQL Server (business source of truth)
```

### Architecture rules

- Streamlit is presentation only; no direct SQL or business logic in UI pages.
- FastAPI validates requests and calls business services.
- Business rules live in service modules.
- SQL Server is the source of truth for customers, subscriptions, stock, deliveries, charges, and payments.
- Use parameterized SQL only.
- Never allow the LLM to execute arbitrary SQL.
- The LLM may classify a question into an approved intent; backend services perform validated queries.
- Financial calculations use Python `Decimal` and SQL `DECIMAL`, never floating-point arithmetic.
- n8n handles notifications and orchestration; it is not the business database.
- FAISS stores document vectors; SQL Server remains authoritative for structured records.
- Bind services to `127.0.0.1` by default.

## 4. Functional requirements

### 4.1 Customers

Fields: unique customer code, name, mobile, email, address, area, delivery route, preferred contact method, active status, notes, created/updated timestamps.

Functions: create, search, view, edit, deactivate. Do not hard-delete customers with historical subscriptions or financial activity. Audit important changes.

### 4.2 Milk products and pricing

Products are configurable, not hard-coded. Example products may include cow milk and buffalo milk.

Fields: product code, name, unit (litre by default), active status. Maintain price history with effective-from/effective-to dates. Historical transactions must retain their original price snapshot.

### 4.3 Daily availability

Availability is entered for each date and product.

Example:

| Date | Product | Available litres |
|---|---|---:|
| 01-Nov-2026 | Cow milk | 100 |
| 01-Nov-2026 | Buffalo milk | 40 |

Calculate committed quantity and remaining quantity. Do not approve subscriptions that exceed stock. Use SQL transactions and appropriate locking/consistency controls to prevent concurrent approvals from over-allocating stock. If an availability edit would make approved allocations invalid, reject it or create an explicit administrator exception; never silently overbook.

### 4.4 Subscriptions

Supported frequencies:

- `DAILY`: every day in the subscription date range.
- `SELECTED_DAYS`: only selected weekdays, such as Monday, Wednesday, Friday.

Fields: subscription number, customer, product, quantity per delivery, frequency, selected weekdays, start date, optional end date, status, customer confirmation status/time, approval time, unit-price snapshot, notes.

Lifecycle:

```text
DRAFT
  -> PENDING_CUSTOMER_CONFIRMATION
      -> DECLINED
      -> customer confirms
          -> stock validation
              -> APPROVED
              -> WAITLISTED / REQUIRES_REVIEW
```

Business rules:

- Customer confirmation is mandatory before approval.
- On confirmation, check stock for every applicable date in the requested period.
- If stock is sufficient on all applicable dates, approve automatically.
- If any date is short, do not partially approve silently. Set `WAITLISTED` or `REQUIRES_REVIEW` and show dates and shortage quantities.
- Administrator can resolve shortage, amend the proposal, or reject it.
- Changes to approved subscriptions must be revalidated.
- Cancellation stops future delivery generation but preserves historical deliveries and payments.
- Keep status history and audit reasons.
- Do not invent waitlist priority rules; make them configurable after business confirmation.

### 4.5 Delivery planning

Generate deliveries from approved subscriptions. Fields include delivery date, subscription, customer, route, product, planned quantity, delivered quantity, status, timestamp, and notes.

Statuses: `PLANNED`, `OUT_FOR_DELIVERY`, `DELIVERED`, `MISSED`, `CANCELLED`.

Rules:

- Respect subscription date range and selected weekdays.
- Prevent duplicate delivery rows for the same subscription/date.
- Generation must be idempotent: running it twice must not create duplicates.
- Provide customer-wise and route-wise lists.
- Record delivered/missed status and audit corrections.
- Preserve historical deliveries after subscription cancellation.

### 4.6 Billing and manual payments

Initial release records payments manually; no payment gateway.

Functions: calculate customer charges, record cash/bank transfer/UPI/other payments, allocate partial payments, produce receipts/statements, calculate outstanding balances, record adjustments/refunds as separate auditable transactions.

Use `DECIMAL` in SQL and `Decimal` in Python. Prevent duplicate payment references where supplied. Never silently edit historical transactions.

### 4.7 Email notifications

Use a notification outbox in SQL Server and n8n for orchestration. Gmail/Google Workspace OAuth2 is configured in the email phase.

Events: confirmation request, approved, waitlisted/review required, cancelled, delivery exception, payment receipt, monthly statement.

Requirements:

- Templates separate from business logic.
- Store pending notification events before n8n processes them.
- Track sent/failed status, attempts, provider response, and timestamps.
- Retry safely and avoid duplicate messages.
- Email failure must not roll back a valid subscription/payment.
- Never store Gmail passwords or OAuth tokens in source code.
- App must indicate whether email integration is configured.

### 4.8 Local AI assistant

Use Ollama `llama3.2:3b`.

Example questions:

- How many active subscriptions are there?
- What is today's cow milk requirement?
- Which customers are awaiting confirmation?
- Which customers have outstanding balances?
- What were sales last month?
- Which delivery routes have the highest volume?

Safe flow:

1. Classify request into an approved intent.
2. Validate dates, product names, and parameters.
3. Map intent to a predefined backend service/report.
4. Execute parameterized SQL in that service.
5. Return structured results to the LLM for plain-language explanation.

LLM must not execute arbitrary SQL, access credentials, invent results, or perform unconfirmed writes. Any consequential write must go through a normal validated UI/API workflow with explicit confirmation. Normal business operations must continue if Ollama is unavailable.

### 4.9 Document RAG

Use `qwen3-embedding:0.6b` through Ollama and FAISS for internal procedures, FAQs, pricing policies, delivery instructions, and other approved documents.

Pipeline: upload -> validate -> extract text -> chunk with source metadata -> embed locally -> save FAISS index -> retrieve relevant chunks -> generate grounded answer with source references.

Support re-index and delete. Do not index credentials or unrelated personal files. Treat retrieved document text as untrusted content, not system instructions. If evidence is missing, say so. Keep structured business-data queries separate from document RAG.

### 4.10 Dashboard and reports

Dashboard: active customers, active subscriptions, today's demand by product, available/committed/remaining stock, today's deliveries, pending confirmations, outstanding balances, daily/monthly sales, low-stock warnings.

Reports: customer list, subscriptions, subscription changes/cancellations, demand, availability/utilization, delivery register, route summary, sales, customer ledger, outstanding balances, payment register, notification status.

Provide filters and CSV/Excel export with pandas/openpyxl. Label forecasts as estimates, never as confirmed stock or actual sales.

## 5. Database design

Create the database only in Phase 2 after explicit user approval. Use versioned SQL scripts/migrations, constraints, indexes, and transactions.

### Core tables

| Table | Purpose / key fields |
|---|---|
| `Customers` | CustomerId PK, CustomerCode unique, name, mobile, email, address, area, route, contact preference, IsActive, timestamps |
| `DeliveryRoutes` | RouteId PK, RouteName, description, active flag |
| `MilkProducts` | MilkProductId PK, ProductCode unique, ProductName, UnitOfMeasure, active flag |
| `ProductPrices` | ProductPriceId PK, MilkProductId FK, PricePerUnit DECIMAL(12,2), EffectiveFrom, EffectiveTo |
| `DailyAvailability` | AvailabilityId PK, date, product FK, AvailableQuantity DECIMAL(12,3), unique(date, product) |
| `Subscriptions` | SubscriptionId PK, unique number, customer/product FKs, quantity DECIMAL(12,3), frequency, start/end, status, confirmation status/time, approved time, price snapshot |
| `SubscriptionDays` | SubscriptionDayId PK, subscription FK, DayOfWeek, unique(subscription, weekday) |
| `SubscriptionStatusHistory` | HistoryId PK, subscription FK, old/new status, timestamp, actor, reason |
| `Deliveries` | DeliveryId PK, subscription/customer/product FKs, date, planned/delivered quantities, status, delivered timestamp, unique(subscription, date) |
| `CustomerCharges` | ChargeId PK, customer/delivery refs, date, quantity, unit price, amount DECIMAL(14,2), description |
| `Payments` | PaymentId PK, customer FK, date, amount DECIMAL(14,2), method, reference, notes, actor |
| `PaymentAllocations` | AllocationId PK, payment FK, charge FK, allocated amount |
| `NotificationOutbox` | Event type, recipient, payload reference, status, attempts, last error, timestamps |
| `Documents` | Document metadata, storage path, checksum, indexing status |
| `DocumentChunks` | Document FK, chunk number, text, metadata, vector/index reference |
| `Imports` | File, import type, status, counts, errors |
| `AuditLogs` | Actor, action, entity, entity ID, timestamp, safe before/after summary |
| `AppUsers` / `Roles` | Add if multi-user authentication is required |
| `SystemSettings` | Non-secret settings only |

### Integrity rules

- Use foreign keys, unique/check constraints, and indexes.
- Use `DECIMAL` for quantities and currency.
- Use parameterized SQL.
- Use transactions for approval/allocation, delivery generation, and payment allocation.
- Store price snapshots for historical charges.
- Document weekday numbering and timezone/date handling.
- Never physically delete financial or delivery history.
- Add indexes for delivery date, customer, product, subscription status, and payment date.

## 6. API design

Use `/api/v1` routes.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health` | Dependency health |
| GET | `/api/health/live` | Process liveness |
| GET/POST | `/api/v1/customers` | List/create |
| GET/PATCH | `/api/v1/customers/{id}` | Read/update |
| GET/POST | `/api/v1/products` | List/create |
| GET/POST | `/api/v1/availability` | Read/set availability |
| GET/POST | `/api/v1/subscriptions` | Search/create proposal |
| POST | `/api/v1/subscriptions/{id}/confirm` | Record confirmation |
| POST | `/api/v1/subscriptions/{id}/approve` | Validate and approve |
| POST | `/api/v1/subscriptions/{id}/cancel` | Cancel future schedule |
| POST | `/api/v1/deliveries/generate` | Generate deliveries |
| GET/PATCH | `/api/v1/deliveries` | List/update delivery |
| POST | `/api/v1/payments` | Record payment |
| GET | `/api/v1/reports/...` | Reports |
| POST | `/api/v1/ai/chat` | Safe intent-based AI |
| POST | `/api/v1/documents` | Upload document |
| POST | `/api/v1/documents/{id}/index` | Index/re-index |

Use Pydantic request/response schemas, validation, consistent error responses, and tests. Add authentication/role authorization before exposing the app beyond a single trusted local user.

## 7. Streamlit pages

1. Home / Dashboard
2. Customers
3. Milk Products
4. Daily Availability
5. Subscriptions
6. Delivery Planning
7. Payments
8. Customer Ledger
9. Reports
10. AI Assistant
11. Document Knowledge Base
12. Email / Workflow Status
13. Settings

Keep forms straightforward, validate before submission, show API feedback, label units and dates, paginate large lists, and confirm consequential actions. All pages call FastAPI; none query SQL directly.

## 8. Suggested project structure

```text
C:\Projects\dairy-ai-subscriptions\
├── api\
│   ├── main.py
│   └── v1\routes\
├── app\
│   ├── Home.py
│   └── pages\
├── core\
│   ├── config.py
│   ├── logging_config.py
│   └── exceptions.py
├── database\
│   ├── connection.py
│   ├── repositories\
│   └── migrations\
├── schemas\
├── services\
│   ├── customer_service.py
│   ├── availability_service.py
│   ├── subscription_service.py
│   ├── delivery_service.py
│   ├── payment_service.py
│   ├── reporting_service.py
│   └── notification_service.py
├── integrations\
│   ├── ollama_client.py
│   ├── n8n_client.py
│   └── email_templates\
├── ai\
│   ├── intent_router.py
│   ├── prompts\
│   └── rag\
├── scripts\
├── tests\
│   ├── unit\
│   ├── integration\
│   └── api\
├── data\
│   ├── documents\
│   └── faiss_index\
├── logs\
├── .env.example
├── .env.n8n.example
├── .gitignore
├── docker-compose.n8n.yml
├── requirements.txt
├── README.md
└── CODEX_PROJECT_GUIDE.md
```

Keep `.env`, logs, runtime uploads, database backups, and FAISS runtime files out of Git unless deliberately versioned.

## 9. Environment configuration

Example `.env.example`:

```dotenv
APP_NAME=Dairy AI Subscription Management
APP_ENV=development
APP_HOST=127.0.0.1
APP_PORT=8000
APP_TIMEZONE=Asia/Kolkata

DB_SERVER=localhost
DB_DATABASE=DairySubscriptionDB
DB_DRIVER=ODBC Driver 18 for SQL Server
DB_TRUSTED_CONNECTION=yes
DB_ENCRYPT=yes
DB_TRUST_SERVER_CERTIFICATE=yes

OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2:3b
OLLAMA_EMBEDDING_MODEL=qwen3-embedding:0.6b

N8N_BASE_URL=http://127.0.0.1:5678
N8N_WEBHOOK_URL=

DOCUMENT_STORAGE_PATH=./data/documents
FAISS_INDEX_PATH=./data/faiss_index
LOG_LEVEL=INFO
```

`localhost` SQL server is an example; confirm the user's actual instance name. Do not create the database in Phase 1. `.env` must be Git-ignored. Never commit passwords, OAuth tokens, API keys, or n8n encryption keys. Validate configuration without printing secrets. For local development, document the implications of trusting the SQL Server certificate; production should use a properly trusted certificate.

## 10. Local setup commands

```powershell
Set-Location C:\Projects\dairy-ai-subscriptions
py -3.14 --version
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

If PowerShell blocks activation:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Start FastAPI:

```powershell
uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
```

URLs: `http://127.0.0.1:8000/api/health`, `/api/health/live`, `/docs`.

Start Streamlit in another terminal:

```powershell
.\.venv\Scripts\Activate.ps1
streamlit run app/Home.py
```

URL: `http://127.0.0.1:8501`.

Check Ollama and install models manually when ready:

```powershell
ollama --version
ollama list
ollama pull llama3.2:3b
ollama pull qwen3-embedding:0.6b
```

Application startup must not automatically download models.

## 11. Local n8n with Docker

Illustrative `docker-compose.n8n.yml`:

```yaml
services:
  n8n:
    image: docker.n8n.io/n8nio/n8n:latest
    restart: unless-stopped
    ports:
      - "127.0.0.1:5678:5678"
    environment:
      - GENERIC_TIMEZONE=Asia/Kolkata
      - TZ=Asia/Kolkata
      - N8N_ENCRYPTION_KEY=${N8N_ENCRYPTION_KEY}
      - N8N_SECURE_COOKIE=false
    volumes:
      - n8n_data:/home/node/.n8n

volumes:
  n8n_data:
```

Pin a tested n8n version for stable use rather than keeping `latest`. Generate a strong unique encryption key and keep it in untracked `.env.n8n`.

```powershell
Copy-Item .env.n8n.example .env.n8n
# Edit .env.n8n and set N8N_ENCRYPTION_KEY.
docker compose --env-file .env.n8n -f docker-compose.n8n.yml up -d
docker compose --env-file .env.n8n -f docker-compose.n8n.yml logs -f n8n
```

Open `http://127.0.0.1:5678`.

Stop without deleting persistent data:

```powershell
docker compose --env-file .env.n8n -f docker-compose.n8n.yml down
```

Gmail OAuth2 and workflows are implemented in the email phase, not Phase 1.

## 12. Dependency strategy

Start with only the dependencies needed for the current phase. Candidate Phase 1 packages:

```text
fastapi
uvicorn[standard]
streamlit
pydantic-settings
pyodbc
httpx
pytest
```

Add later as needed: `pandas`, `openpyxl`, `plotly`, `faiss-cpu`, `python-multipart`, `pypdf`. Check Python 3.14 support and lock tested versions. Do not install every future dependency in Phase 1.

## 13. Implementation roadmap

### Phase 1 — Foundation

- Project skeleton and package structure.
- Configuration, `.env.example`, logging, `.gitignore`.
- FastAPI health and liveness endpoints.
- SQL Server connection module using Windows Authentication.
- Safe `SELECT 1` connectivity check only.
- Ollama availability/model check; no automatic downloads.
- Minimal Streamlit home page that calls the API.
- Environment checker and pytest foundation.
- Local n8n Docker Compose setup and documentation.
- README and run commands.

**Not included:** business schema, customer/subscription workflows, payments, AI chat, RAG, Gmail OAuth, email workflows, dashboard reports.

**Acceptance:** dependencies install in a virtual environment; API starts; health reports dependencies without secrets; SQL test only runs `SELECT 1`; Ollama check does not download models; Streamlit reaches API; tests pass; secrets are Git-ignored.

### Phase 2 — Database and master data

- Obtain approval before creating the database.
- Add versioned SQL migrations/schema.
- Implement customers, products, routes, price history, audit.
- Add repository layer, APIs, Streamlit pages, sample seed script.
- Test constraints, CRUD, and historical retention.

### Phase 3 — Availability and subscription engine

- Daily stock entry and remaining-stock calculation.
- Daily and selected-weekday subscription proposal.
- Customer confirmation.
- Automatic approval only after successful all-date stock validation.
- Waitlist/review on shortages.
- Transaction-safe stock allocation and status history.
- Test date boundaries, weekdays, shortages, and concurrent approval.

### Phase 4 — Delivery planning

- Generate deliveries from approved subscriptions.
- Respect dates and selected weekdays.
- Prevent duplicates; generation must be idempotent.
- Route/customer lists and delivery outcome updates.
- Preserve historical delivery records.

### Phase 5 — Billing and manual payments

- Customer charges and price snapshots.
- Manual payments, partial allocation, receipts, statements.
- Customer ledger and outstanding balance.
- Auditable adjustments/refunds.
- Decimal-safe calculations and reconciliation tests.

### Phase 6 — Local AI assistant

- Ollama integration and approved intent catalogue.
- Validate intent parameters.
- Route intents to predefined backend services.
- AI chat page with grounded results.
- No arbitrary SQL and no unconfirmed write actions.
- Core application must work if Ollama is offline.

### Phase 7 — Email automation

- Notification outbox.
- n8n webhook/workflows.
- Gmail/Workspace OAuth2.
- Confirmation, approval, cancellation, delivery, receipt, statement templates.
- Retry, deduplication, failure tracking, status page.
- Email failure must not undo business transactions.

### Phase 8 — RAG knowledge base

- Document upload, validation, text extraction, chunking.
- Local embeddings through Ollama.
- FAISS persistence and retrieval.
- Source-grounded answers, re-index and delete.
- Do not allow retrieved content to override system rules or trigger actions.

### Phase 9 — Dashboard and advanced reports

- Operational dashboard and report filters.
- Stock utilization, demand, sales, collections, routes, customer ledger.
- CSV/Excel export.
- Forecasts labelled as estimates.

### Phase 10 — Hardening and local deployment

- Authentication/roles if needed.
- Backup/restore for SQL Server, documents, and FAISS.
- Log rotation, monitoring, configuration checks.
- Security/dependency review.
- Windows run scripts and user/admin documentation.
- Restore test and full workflow integration tests.

## 14. Test strategy

Use pytest.

**Unit tests:** schedule generation, weekday logic, availability, shortage decisions, pricing, charges, payment allocations, balances, intent validation, notification retry logic.

**Integration tests:** SQL repositories, transaction rollback, concurrent stock allocation, delivery idempotency, notification outbox, mocked Ollama HTTP.

**API tests:** valid/invalid payloads, missing customer/product, invalid date range, confirmation required, insufficient stock, duplicate payment reference, authorization.

Use a dedicated test database. Never run destructive tests against live business data.

## 15. Security and operational safeguards

- Localhost binding by default.
- Windows Authentication where possible.
- No secrets in source control.
- Parameterized SQL only.
- Validate every API request.
- Add role authorization before multi-user/public exposure.
- Audit sensitive changes.
- Back up SQL Server and uploaded documents.
- Do not expose n8n publicly.
- Protect n8n encryption key and OAuth credentials.
- Do not log unnecessary customer personal data.
- LLM cannot directly query SQL or change financial records.
- Define retention and backup policies.

## 16. Business decisions to confirm before production

Do not invent these values in code:

1. Milk products and units.
2. Price per product and effective dates.
3. Daily stock by product.
4. Whether subscriptions are open-ended or have an end date.
5. Whether approval requires stock for the full requested period.
6. Waitlist priority.
7. Same-day change/cancellation cut-off.
8. Holiday and Sunday delivery rules.
9. Whether missed deliveries are chargeable.
10. Billing cycle and statement period.
11. Payment allocation order.
12. Applicable tax treatment.
13. Customer confirmation channel and expiry.
14. Delivery routes and assignment rules.
15. Email sender and approved templates.
16. User roles and permissions.

## 17. Codex project instructions

Treat this file as the master specification. For every phase:

1. Read the full specification and identify the current phase.
2. Inspect the repository before modifying files.
3. Implement only the current phase and explicit dependencies.
4. Do not overwrite working code unnecessarily.
5. Add tests for every implemented feature.
6. Run tests and relevant static checks; fix failures.
7. Update README with exact setup/run commands.
8. List created and modified files.
9. Report commands run and test results.
10. State limitations and decisions needed from the user.
11. Stop and wait for approval before the next phase.

Never implement future phases early. Never invent unresolved business rules. Never add cloud AI dependencies. Never allow arbitrary LLM SQL. Never store secrets in code. Never create/alter a production database without approval. Do not claim completion without running tests.

### Initial Codex prompt — Phase 1 only

```text
Read CODEX_PROJECT_GUIDE.md completely.

Implement Phase 1 only for the Dairy AI Subscription Management System.

Before coding:
- Inspect the project folder and installed Python version.
- Check package compatibility with the installed Python version.
- Report compatibility issues before changing the environment.
- Do not modify global Python installations.

Implement:
- project skeleton
- configuration and .env.example
- structured logging
- FastAPI health and liveness endpoints
- SQL Server Windows Authentication connection module
- safe SELECT 1 connectivity check
- Ollama availability/model check
- minimal Streamlit home page calling the API
- environment checker
- pytest foundation
- local n8n Docker Compose setup and documentation
- README and .gitignore

Do not create the business database or schema.
Do not implement customers, subscriptions, deliveries, payments, AI chat,
RAG, Gmail OAuth, email workflows, or dashboard reports.

Use modular code, type hints, validation, tests, and localhost binding.
Never hard-code secrets. Do not automatically download Ollama models.

At completion, run tests and report exact results, list changed files,
provide PowerShell run commands, explain manual setup, and stop after
Phase 1. Wait for my approval before Phase 2.
```

## 18. Definition of done

The complete system is ready when customers/products can be maintained; stock can be entered and cannot be over-allocated; confirmed subscriptions are approved only when stock is sufficient; deliveries are generated accurately; charges/payments/balances reconcile; notifications work; local AI answers supported questions through validated services; RAG answers cite indexed sources; reports reconcile with SQL Server; backups restore successfully; and the full application runs on the local Windows PC without a cloud AI dependency.

**Recommended execution:** Start with Phase 1, validate the local environment, and proceed sequentially. Each phase must leave a working, tested application.
