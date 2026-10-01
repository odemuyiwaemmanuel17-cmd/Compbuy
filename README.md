# Compbuy

A marketplace for buying and selling businesses. Sellers publish a company with its
financials; buyers search the catalogue, save favourites, place offers, and negotiate
in a thread that opens automatically.

Built with **FastAPI** (async), **Supabase** for PostgreSQL and authentication,
**Jinja2** server-side rendering with Tailwind CSS, and **python-dotenv** configuration.

---

## Quick start

```bash
# 1. Install dependencies
python -m pip install -r requirements.txt

# 2. Configure Supabase
cp .env.example .env
#    then set SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY, SESSION_SECRET

# 3. Apply the schema (from the Supabase CLI, in the project directory)
supabase db push          # or paste supabase/migrations/0001_initial_schema.sql
                          # into the SQL editor, then run supabase/seed.sql

# 4. Run it
python run.py             # http://127.0.0.1:8000
python run.py --reload    # auto-restart on changes
```

Generate a session secret with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Demo accounts after `seed.sql`: `seller@compbuy.demo`, `buyer@compbuy.demo`,
`other@compbuy.demo` — password `demo-password`.

---

## Project layout

```
app/
  main.py            application factory: middleware, routers, exception handlers
  config.py          dotenv-loaded Settings (the only reader of os.environ)
  database.py        Supabase gateway + Query protocol (the only Supabase import site)
  session_store.py   signed httpOnly cookie session and flash messages
  dependencies.py    FastAPI providers: settings, gateway, services, current user
  rendering.py       template rendering, error pages, login redirect helpers
  templating.py      Jinja2 environment and shared globals/filters
  errors.py          AppError hierarchy (422/401/403/404/409/502)
  models/            domain entities parsed from Supabase rows (incl. NDA gating)
  schemas/           Pydantic request validation
  services/          listing, offer, watchlist, message, auth, NDA business logic
  routers/           pages, auth, listings, seller, nda, offers, buyer, messages, dashboard
  templates/         Jinja2 + Tailwind (CDN) views
  static/            stylesheet and favicon
supabase/
  migrations/0001_initial_schema.sql   tables, constraints, indexes, RLS policies
  migrations/0002_nda_data_room.sql    NDA table, monthly metrics, revenue bands, RLS
  seed.sql                             demo accounts, listings, NDAs, offers, threads
tests/               suite + in-memory Supabase double (no credentials needed)
run.py               uvicorn entrypoint
```

## How the pieces fit

- **One integration seam.** Nothing outside `app/database.py` imports `supabase`. Services
  depend on the `Gateway`/`Query` protocols, so `tests/support/in_memory_gateway.py`
  replaces Postgres and Auth with an in-memory implementation that has the same
  filter, count, and representation-returning write semantics.
- **Auth.** Supabase Auth handles sign-up and sign-in. The resulting tokens are stored
  in a signed, `httpOnly`, `SameSite=Lax` session cookie. Browser JavaScript never
  sees a token, and every authenticated page resolves its identity from that cookie.
- **Authorization.** The server uses the service-role key for reads and writes, so
  ownership is enforced **in the service layer** (`find_owned`, participant checks on
  threads, `seller_id`/`buyer_id` predicates on updates) *and* by Row Level Security
  policies in the migration, which protect any direct anon-key client.
- **Blocking I/O off the loop.** `supabase-py` is synchronous; `run_query` and
  `run_in_thread` execute it on a worker thread so the event loop stays responsive.
- **Data-room gating lives in the model, not the templates.** `Listing` exposes every
  confidential value only through a property that returns `Members only` until the
  object is marked `data_room_unlocked`, so a new template cannot leak revenue by
  reading the wrong attribute. `NdaService.reveal_with()` is the single gate decision for
  the listing-detail page, and the seller's own listings are unlocked in
  `ListingService.find_owned()` / `list_for_seller()`.
- **State changes are conditional writes.** Every NDA and offer transition updates the
  row with the status it expects to find (`…eq("id", …).eq("seller_id", …).eq("status",
  "pending")`). If the row moved underneath the actor, the update matches nothing and
  the request fails with `409` instead of silently overwriting the other decision.

## Route map

| Method | Path | Access |
|---|---|---|
| GET | `/` | public — featured listings |
| GET | `/listings` | public — search, filter by industry/price/band, sort, paginate |
| GET | `/listings/{id}` | public detail — data room hidden until a signed NDA |
| GET/POST | `/auth/register`, `/auth/login`, `/auth/logout` | Supabase Auth |
| GET | `/seller/listings` | seller — own listings |
| GET/POST | `/listings/new` | seller — create listing (draft or publish) |
| GET/POST | `/seller/listings/{id}/edit` | seller — edit |
| POST | `/seller/listings/{id}/status`, `/delete` | seller — publish/unpublish/sold/delete |
| POST | `/listings/{id}/nda-request` | buyer — request data-room access |
| POST | `/nda/{id}/sign` | buyer — sign the NDA and unlock the room |
| POST | `/nda/{id}/approve`, `/decline` | seller — decide on a request |
| POST | `/nda/{id}/withdraw` | buyer — cancel an open request |
| GET | `/seller/data-room` | seller — inbound access requests |
| GET | `/buyer/access` | buyer — status of each request |
| POST | `/listings/{id}/offers` | buyer — place an offer or Letter of Intent |
| POST | `/offers/{id}/accept`, `/decline` | seller — decide |
| POST | `/offers/{id}/withdraw` | buyer — withdraw |
| GET/POST/DELETE | `/buyer/watchlist...` | buyer — saved listings |
| GET | `/buyer/offers` | buyer — own offers |
| GET | `/messages`, `/messages/{id}` + reply | participants |
| GET | `/dashboard` | member workspace — listings, offers, access requests |
| GET | `/healthz` | ops |

## What is public and what is in the data room

| Public to everyone | Data room only (signed NDA, or the seller) |
|---|---|
| Headline, one-liner, description | Exact legal business name |
| Industry, location, established year | Monthly revenue and net profit |
| Asking price | Annual revenue and annual profit |
| Coarse revenue band (`$250K–$1M / yr`) | Profit margin and revenue multiple |
| | Reason for selling |

The catalogue can be filtered by revenue *band* but never by an exact revenue
figure, because a numeric floor would let anyone bisect the gated number. The
revenue multiple is gated too: `asking price ÷ multiple` reconstructs revenue.

## Tests

```bash
python -m pytest
```

The suite runs with **no Supabase credentials and no network**: the environment fixture
removes `SUPABASE_*` and `SESSION_SECRET` before every test, so a green run is proof the
business logic and HTTP layer hold independently of the live project. Coverage follows the
acceptance criteria in `docs/plan/compbuy-spec.md` (AC-1…AC-10), including the authorization
edges: a signed-in member cannot edit, delete, decide, or read another member's resources,
and no confidential figure reaches the HTML of a visitor without a signed NDA.

## Configuration reference

| Variable | Purpose | Default |
|---|---|---|
| `SUPABASE_URL` | project endpoint | — |
| `SUPABASE_ANON_KEY` | auth client key | — |
| `SUPABASE_SERVICE_ROLE_KEY` | server-side data writes; optional but recommended | — |
| `SESSION_SECRET` | signs the session cookie (required in production) | — |
| `SESSION_MAX_AGE_SECONDS` | cookie lifetime | `604800` |
| `COOKIE_SECURE` | set `Secure` on the session cookie | `true` when `APP_ENV=production` |
| `LISTINGS_PER_PAGE` | catalogue page size | `12` |

## Deploying

### Vercel (zero-config FastAPI)

Vercel detects a FastAPI instance named `app` at a supported entrypoint, and
`app/main.py` already provides one — so no `vercel.json` and no build command are
required. Import the repo, and it builds the whole site as a single Python function.

Set these in **Project Settings → Environment Variables**:

| Variable | Value | Why |
|---|---|---|
| `SUPABASE_URL` | your project URL | required |
| `SUPABASE_ANON_KEY` | your anon key | required |
| `SUPABASE_SERVICE_ROLE_KEY` | your service-role key | required for writes |
| `SESSION_SECRET` | `python -c "import secrets; print(secrets.token_urlsafe(32))"` | **required** — see below |

`APP_ENV` does not need to be set: when `VERCEL_ENV` is `production` or `preview` the
app treats itself as deployed, which turns on `COOKIE_SECURE` and turns off debug.

`SESSION_SECRET` is not optional once deployed. The signed session cookie carries the
Supabase tokens, and a container is shared and short-lived: if the secret were generated
at boot, every cold start would invalidate everyone's session. The app therefore raises
`RuntimeError: SESSION_SECRET must be set in production` instead of starting with an
ephemeral key.

Vercel scopes variables per environment, and Production, Preview, and Development are
three separate lists. A URL like `compbuy-5w77.vercel.app` is a **Preview** deployment, so
saving a variable only under Production leaves preview without it. Tick every environment
you deploy to, then **Redeploy** — an existing deployment keeps the environment it was
created with.

To separate a boot failure from a request failure, open `/healthz`. If that returns `500`
too, the function never imported: the traceback under **View Logs** names the cause, and
for a missing secret it is the `RuntimeError` above.

Two platform notes worth knowing:

- **Static files stay in the function.** `app/static/` would normally be promoted to the
  CDN, but Vercel keeps mounted files inside the function when top-level middleware is
  present, and `SessionMiddleware` is one. Correct, just not CDN-cached.
- **Cold starts.** The first request after a period of inactivity pays Python import plus
  a Supabase round-trip. If listing pages time out under load, raise the function's
  `maxDuration` by adding:

  ```json
  { "functions": { "app/main.py": { "maxDuration": 30 } } }
  ```

### Any long-running host (Fly.io, Railway, Docker, a VPS)

```bash
pip install -r requirements.txt
python run.py --host 0.0.0.0 --port "$PORT"
```

This is the better fit if you need local disk, websocket updates, or no cold starts. Set
`APP_ENV=production` and `SESSION_SECRET` the same way.

### Before either deploy works

Apply the schema — the app cannot serve listings without it:

```bash
supabase link --project-ref <ref>
supabase db push          # 0001 then 0002
```

## Notes and limitations

- No payments or escrow: an accepted offer records intent, and the seller marks the
  listing sold.
- The NDA is a recorded agreement (status, signer name, timestamp), not a digitally
  signed document. There is no PDF generation, counterparty identity verification, or
  retention policy yet; export the signed record before relying on it legally.
- Column-level secrecy is enforced in Python, not Postgres: RLS restricts which listing
  *rows* a client can read but cannot mask individual columns, so `Listing` gates the
  values. If you expose the Supabase API directly to a browser, keep the confidential
  columns out of the anon-visible view or move them into a separate table.
- `listings.image_urls` exists in the schema but upload to Supabase Storage is not wired.
- Message threads load on request; Supabase Realtime is not used.
- Deploy behind HTTPS and set `COOKIE_SECURE=true`, since the session carries auth tokens.
