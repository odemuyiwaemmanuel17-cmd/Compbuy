-- Compbuy: NDA-secured data room, monthly metrics, and LOI offers
-- Apply after 0001_initial_schema.sql.
--
-- Sensitivity model introduced here:
--   PUBLIC      headline, industry, location, asking price, established year,
--               public description, and a coarse revenue BAND.
--   DATA ROOM   exact business name, monthly revenue, annual revenue, net profit,
--               annual profit, margin/multiple, and the seller's reason for selling.
--
-- The exact asking price stays public because browse filters on it. The revenue
-- multiple is deliberately NOT public: asking_price / multiple would let anyone
-- reconstruct the gated annual revenue, so only a coarse band is exposed until a
-- buyer's NDA is signed.

do $$ begin
  create type nda_status as enum ('pending', 'approved', 'signed', 'rejected', 'withdrawn');
exception
  when duplicate_object then null;
end $$;

-- A listing is transacted on with either a firm offer or a non-binding letter of intent.
do $$ begin
  create type offer_kind as enum ('offer', 'loi');
exception
  when duplicate_object then null;
end $$;

-- ------------------------------------------------------------ listing columns

alter table public.listings
  add column if not exists business_name    text not null default '',
  add column if not exists monthly_revenue  bigint check (monthly_revenue is null or monthly_revenue > 0),
  add column if not exists net_profit       bigint check (net_profit is null or net_profit >= 0),
  add column if not exists reason_for_selling text not null default '',
  add column if not exists revenue_band     text not null default 'undisclosed'
    check (revenue_band in ('undisclosed', 'under_250k', '250k_to_1m', '1m_to_5m', 'over_5m'));

-- Backfill annual_revenue-derived bands for rows created before this migration.
update public.listings
set revenue_band = case
  when annual_revenue is null or annual_revenue <= 0 then 'undisclosed'
  when annual_revenue <  250000  then 'under_250k'
  when annual_revenue <  1000000  then '250k_to_1m'
  when annual_revenue <  5000000  then '1m_to_5m'
  else 'over_5m'
end
where revenue_band = 'undisclosed';

-- ------------------------------------------------------------------ offers.kind

alter table public.offers
  add column if not exists kind offer_kind not null default 'offer';

create index if not exists offers_seller_kind_idx on public.offers (seller_id, kind, created_at desc);

-- --------------------------------------------------------------- nda_requests

create table if not exists public.nda_requests (
  id          uuid primary key default gen_random_uuid(),
  listing_id  uuid not null references public.listings (id) on delete cascade,
  buyer_id    uuid not null references public.profiles (id) on delete cascade,
  seller_id   uuid not null references public.profiles (id) on delete cascade,
  status      nda_status not null default 'pending',
  message     text not null default '' check (char_length(message) <= 2000),
  signed_name text not null default '',
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  signed_at   timestamptz,
  constraint nda_requests_participants_differ check (buyer_id <> seller_id)
);

-- One live NDA thread per buyer/listing pair.
create unique index if not exists nda_requests_unique_pair
  on public.nda_requests (listing_id, buyer_id);

create index if not exists nda_requests_seller_status_idx
  on public.nda_requests (seller_id, status, created_at desc);
create index if not exists nda_requests_buyer_idx
  on public.nda_requests (buyer_id, status);

create trigger nda_requests_set_updated_at
  before update on public.nda_requests
  for each row execute function public.set_updated_at();

-- A signed NDA must carry the signer's name and timestamp, and vice versa.
create or replace function public.assert_nda_signature_integrity()
returns trigger
language plpgsql
as $$
begin
  if new.status = 'signed' and (new.signed_at is null or btrim(new.signed_name) = '') then
    raise exception 'a signed NDA requires a signer name and timestamp';
  end if;
  if new.status <> 'signed' and new.signed_at is not null and tg_op = 'INSERT' then
    raise exception 'signed_at may only be set when signing';
  end if;
  return new;
end;
$$;

create trigger nda_requests_signature_integrity
  before insert or update on public.nda_requests
  for each row execute function public.assert_nda_signature_integrity();

-- ------------------------------------------------------------------- RLS

alter table public.nda_requests enable row level security;

drop policy if exists "participants read nda requests" on public.nda_requests;
create policy "participants read nda requests" on public.nda_requests
  for select using (auth.uid() = buyer_id or auth.uid() = seller_id);

drop policy if exists "buyers request nda access" on public.nda_requests;
create policy "buyers request nda access" on public.nda_requests
  for insert with check (auth.uid() = buyer_id);

drop policy if exists "nda parties update their requests" on public.nda_requests;
create policy "nda parties update their requests" on public.nda_requests
  for update using (auth.uid() = buyer_id or auth.uid() = seller_id)
  with check (auth.uid() = buyer_id or auth.uid() = seller_id);

-- The gated columns live on listings; the public policy above already restricts
-- which listing rows are readable. Column-level secrecy is enforced in the
-- service layer (Listing.data_room) because RLS cannot mask individual columns.
