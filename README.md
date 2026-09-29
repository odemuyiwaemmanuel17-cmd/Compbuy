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
  db.py              Supabase gateway + Query protocol (the only Supabase import site)
  session_store.py   signed httpOnly cookie session and flash messages
  dependencies.py    FastAPI providers: settings, gateway, services, current user
  rendering.py       template rendering, error pages, login redirect helpers
  templating.py      Jinja2 environment and shared globals/filters
  errors.py          AppError hierarchy (422/401/403/404/409/502)
  models/            domain entities parsed from Supabase rows
  schemas/           Pydantic request validation
  services/          listing, offer, watchlist, message, auth business logic
  routers/           pages, auth, seller, offers, buyer, messages, dashboard
  templates/         Jinja2 + Tailwind (CDN) views
  static/            stylesheet and favicon
supabase/
  migrations/0001_initial_schema.sql   tables, constraints, indexes, RLS policies
  seed.sql                             demo accounts, listings, offers, threads
tests/               suite + in-memory Supabase double (no credentials needed)
run.py               uvicorn entrypoint
```

## How the pieces fit

- **One integration seam.** Nothing outside `app/db.py` imports `supabase`. Services
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

## Route map

| Method | Path | Access |
|---|---|---|
| GET | `/` | public — featured listings |
| GET | `/listings` | public — search, filter, sort, paginate |
| GET | `/listings/{id}` | public — detail |
| GET/POST | `/auth/register`, `/auth/login`, `/auth/logout` | Supabase Auth |
| GET | `/seller/listings` | seller — own listings |
| GET/POST | `/seller/listings/new` | seller — create |
| GET/POST | `/seller/listings/{id}/edit` | seller — edit |
| POST | `/seller/listings/{id}/status`, `/delete` | seller — publish/unpublish/sold/delete |
| POST | `/listings/{id}/offers` | buyer — place offer |
| POST | `/offers/{id}/accept`, `/decline` | seller — decide |
| POST | `/offers/{id}/withdraw` | buyer — withdraw |
| GET/POST/DELETE | `/buyer/watchlist...` | buyer — saved listings |
| GET | `/buyer/offers` | buyer — own offers |
| GET | `/messages`, `/messages/{id}` + reply | participants |
| GET | `/dashboard` | member workspace |
| GET | `/healthz` | ops |

## Tests

```bash
python -m pytest
```

The suite runs with **no Supabase credentials and no network**: the environment fixture
removes `SUPABASE_*` and `SESSION_SECRET` before every test, so a green run is proof the
business logic and HTTP layer hold independently of the live project. Coverage follows the
acceptance criteria in `docs/plan/compbuy-spec.md` (AC-1…AC-7), including the authorization
edges: a signed-in member cannot edit, delete, decide, or read another member's resources.

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

## Notes and limitations

- No payments or escrow: an accepted offer records intent, and the seller marks the
  listing sold.
- `listings.image_urls` exists in the schema but upload to Supabase Storage is not wired.
- Message threads load on request; Supabase Realtime is not used.
- Deploy behind HTTPS and set `COOKIE_SECURE=true`, since the session carries auth tokens.
