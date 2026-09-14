# Confab Gateway (opt-in hosted tier)

Local-first stays the default in the app. This service exists **only** for users
who opt into the metered **Confab Hosted** LLM provider — it is not on the
private/offline path. It holds **one** funded upstream key, meters a per-user
monthly free-tier token cap, and provides an admin dashboard to manage access.
It stores **token counts only — never meeting content**.

## Run (dev)

```bash
cd apps/gateway
GATEWAY_ADMIN_TOKEN=... GATEWAY_UPSTREAM_KEY=sk-... \
  uv run uvicorn main:app --host 127.0.0.1 --port 8900 --reload
```

- Admin dashboard: http://127.0.0.1:8900/admin (enter the admin token once)
- Health: `GET /health`

## Endpoints

| Route | Auth | Purpose |
| --- | --- | --- |
| `POST /auth/register {email}` | — | Create/get the user, return a one-time API token |
| `GET /auth/me` | user token | Account + remaining free-tier tokens this month |
| `POST /v1/chat/completions` | user token | Metered proxy to the funded upstream (OpenAI-shaped) |
| `GET /admin/users` | admin token | All users + usage |
| `PATCH /admin/users/{id}` | admin token | Set `token_limit` and/or `status` (active\|blocked) |
| `POST /admin/users/{id}/reset` | admin token | Reset this month's usage |

## Config (env)

`GATEWAY_DB`, `GATEWAY_ADMIN_TOKEN`, `GATEWAY_UPSTREAM_URL`, `GATEWAY_UPSTREAM_KEY`,
`GATEWAY_UPSTREAM_MODEL`, `GATEWAY_FREE_LIMIT`.

## This is a skeleton — before it's public

- **Auth:** email→token with no verification. Add a magic-link or OAuth (reuse
  the desktop Google loopback pattern) so tokens can't be minted for others' emails.
- **Store:** SQLite + one process. Move to Postgres; keep the token *hash* only
  (already hashed here) behind a real secrets story.
- **Abuse controls:** per-key rate limits, streaming support, request-size caps,
  and an upstream spend ceiling so one funded key can't be run away with.
- **Legal:** proxying requests makes you a data processor — privacy policy, ToS,
  DPA. (We deliberately store no request content to keep this light.)
- **Desktop wiring (next slice):** a `confab-hosted` provider in the app's
  provider registry that signs in, calls `/v1/chat/completions` with the user's
  token, and falls back to BYO-key / local Ollama on a 402/403.
