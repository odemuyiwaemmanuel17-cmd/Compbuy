# Handoff: Compbuy implementation

**Spec:** `docs/plan/compbuy-spec.md`
**Complexity:** Large · **Acceptance criteria:** 7 (AC-1…AC-7) → test-plan floor = 7 scenarios minimum, one per AC, plus adjacent error/edge coverage.

## Contracts fixed before implementation

### Gateway protocol (`app/db.py`)
```
SupabaseGateway
  .table(name: str) -> QueryBuilder
  .auth -> AuthGateway
QueryBuilder (chainable, terminal .execute() -> ApiResponse[data, count])
  .select(cols, count=None) .insert(row) .update(row) .delete()
  .eq(col, val) .neq(col, val) .in_(col, vals) .gte(col, val) .lte(col, val)
  .ilike(col, pattern) .order(col, desc=False) .limit(n) .range(lo, hi)
```
Production impl wraps `supabase.create_client`. Test impl is an in-memory store with the same chain.

### Route table
| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/` | anon | home + featured |
| GET | `/listings` | anon | search/filter/paginate |
| GET | `/listings/{id}` | anon | detail |
| GET/POST | `/auth/register`, `/auth/login` | anon | Supabase auth |
| POST | `/auth/logout` | user | clear session |
| GET/POST | `/seller/listings[/new,/edit,/delete]` | user | listing CRUD |
| POST | `/listings/{id}/offers` | user | submit offer |
| POST | `/offers/{id}/accept`, `/decline` | seller | offer decision |
| POST/DELETE | `/buyer/watchlist/{id}` | user | toggle favourite |
| GET | `/messages`, `/messages/{id}` | user | threads |
| GET | `/dashboard` | user | aggregate |

### Domain enums
`listing_status = draft | published | sold | archived`
`offer_status  = pending | accepted | declined | withdrawn`

## Order of work
migration → config/gateway/fake → auth slice → listing write → catalogue read → offers/watchlist → messaging/dashboard → tests → validation → review → docs.

## Next skill
`/testing-strategy` — feed AC-1…AC-7 into the coverage plan.
