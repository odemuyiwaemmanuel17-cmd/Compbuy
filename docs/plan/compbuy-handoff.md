# Handoff: Compbuy implementation

**Spec:** `docs/plan/compbuy-spec.md`
**Complexity:** Large · **Acceptance criteria:** 10 (AC-1…AC-10) → test-plan floor = 10 scenarios minimum, one per AC, plus adjacent error/edge coverage.

## Contracts fixed before implementation

### Gateway protocol (`app/database.py`)
```
SupabaseGateway
  .table(name: str) -> QueryBuilder
  .auth -> AuthGateway
QueryBuilder (chainable, terminal .execute() -> ApiResponse[data, count])
  .select(cols, count=None) .insert(row) .update(row) .delete() .upsert(row, on_conflict=None)
  .eq(col, val) .neq(col, val) .in_(col, vals) .gte(col, val) .lte(col, val)
  .ilike(col, pattern) .or_ilike(cols, pattern) .order(col, desc=False) .limit(n) .range(lo, hi)
```
Production impl wraps `supabase.create_client`. Test impl is an in-memory store with the same chain.
Writes return the affected representation, so a conditional update that matches nothing yields an
empty result — the basis for the `409` conflict checks in every state machine.

### Route table
| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/` | anon | home + featured |
| GET | `/listings` | anon | search / industry / price band / revenue band / paginate |
| GET | `/listings/{id}` | anon | detail with data room gated on a signed NDA |
| GET/POST | `/listings/new` | user | create listing (draft or publish) |
| GET/POST | `/auth/register`, `/auth/login` | anon | Supabase auth |
| POST | `/auth/logout` | user | clear session |
| GET | `/seller/listings` | seller | own listings |
| GET/POST | `/seller/listings/{id}/edit` | seller | edit |
| POST | `/seller/listings/{id}/status`, `/delete` | seller | state changes, delete |
| POST | `/listings/{id}/nda-request` | user | request data-room access |
| POST | `/nda/{id}/approve`, `/decline` | seller | decide a request |
| POST | `/nda/{id}/sign` | user | countersign and unlock |
| POST | `/nda/{id}/withdraw` | user | cancel an open request |
| GET | `/seller/data-room` | seller | inbound access requests |
| GET | `/buyer/access` | user | status of each request |
| POST | `/listings/{id}/offers` | user | submit offer or LOI (`kind`) |
| POST | `/offers/{id}/accept`, `/decline` | seller | offer decision |
| POST/DELETE | `/buyer/watchlist/{id}` | user | toggle favourite |
| GET | `/messages`, `/messages/{id}` | user | threads |
| GET | `/dashboard` | user | aggregate |

### Domain enums
`listing_status = draft | published | sold | archived`
`offer_status  = pending | accepted | declined | withdrawn`
`offer_kind    = offer | loi`
`nda_status    = pending | approved | signed | rejected | withdrawn` (only `signed` unlocks)
`revenue_band  = undisclosed | under_250k | 250k_to_1m | 1m_to_5m | over_5m` (public)

### Gated listing fields (data room, never public HTML)
`business_name`, `monthly_revenue`, `net_profit`, `annual_revenue`, `annual_profit`,
derived `profit_margin` / `revenue_multiple`, `reason_for_selling`.
Sellers submit monthly figures; `annual_revenue = monthly_revenue × 12` and `revenue_band`
are derived server-side so the public band can never contradict a gated number.

## Order of work
migration → config/gateway/fake → auth slice → listing write → catalogue read → offers/watchlist → messaging/dashboard → tests → validation → review → docs.

Second increment: gateway rename → `0002` migration → model masking → NDA state machine → route split → NDA/dashboard surfaces → re-baseline tests → AC-8/9/10.

## Next skill
`/testing-strategy` — feed AC-1…AC-10 into the coverage plan.
