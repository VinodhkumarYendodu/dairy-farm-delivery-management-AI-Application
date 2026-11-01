# Database migrations

Migrations are applied in filename order and recorded in `dbo.SchemaMigrations`. The runner is idempotent: already recorded migrations are skipped. Each migration uses `GO` to separate SQL Server batches and is committed atomically as a whole.

- `001_master_data.sql`: customers, routes, products, prices, and audit log.
- `002_availability_subscriptions.sql`: daily availability, subscriptions, selected weekdays, and subscription status history.
- `003_deliveries.sql`: idempotent subscription/date delivery records with route/customer/product snapshots and delivery status fields.
- `004_billing_payments.sql`: delivery charges, manual payments, payment allocations, and customer ledger adjustments.
- `005_notification_outbox.sql`: deduplicated email notification queue, delivery state, retry scheduling, and provider diagnostics.
- `006_documents_rag.sql`: uploaded document metadata and extracted, source-linked text chunks for the local RAG index.
- `007_authentication.sql`: administrator, agent, and customer accounts plus expiring/revocable login sessions.
- `008_customer_support.sql`: customer issue tickets and optional photo metadata.
- `009_customer_issue_comments.sql`: auditable staff comments associated with ticket status updates.

