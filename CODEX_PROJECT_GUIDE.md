# Codex Project Guide

The full project specification is in `Dairy_AI_Subscription_Management_Complete_Project_Blueprint.md`.

The blueprint's Phases 1–10 are complete. A user-requested account-access extension (admin, agent, and customer roles) is now authorized. Continue using `(localdb)\MSSQLLocalDB`; apply only the authentication migration for this extension. Report changed files, commands and results, limitations, and any required account setup, then wait for user approval before unrelated work.

Never create or alter a business database without explicit approval. The account-access request explicitly authorizes its necessary schema migration. Keep services bound to localhost, use parameterized SQL, keep secrets out of source control, and never let an LLM execute arbitrary SQL. Do not implement requirements from later phases early.

