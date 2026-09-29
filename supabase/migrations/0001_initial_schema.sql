-- Compbuy initial schema
-- Apply with:  supabase db push      (or paste into the SQL editor)
--
-- The application talks to Supabase with the service-role key (server-side
-- rendering holds no end-user JWT), so Row Level Security below is what protects
-- data when a browser or another client uses the anon key. Ownership is
-- additionally enforced in the Python service layer.

create extension if not exists "pgcrypto";

-- ------------------------------------------------------------------ enums

do $$ begin
  create type listing_status as enum ('draft', 'published', 'sold', 'archived');
exception
  when duplicate_object then null;
end $$;

do $$ begin
  create type offer_status as enum ('pending', 'accepted', 'declined', 'withdrawn');
exception
  when duplicate_object then null;
end $$;

-- ------------------------------------------------------------------ helper

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- ---------------------------------------------------------------- profiles

create table if not exists public.profiles (
  id          uuid primary key references auth.users (id) on delete cascade,
  email       text not null default '',
  display_name text not null default '',
  company_name text not null default '',
  location     text not null default '',
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create trigger profiles_set_updated_at
  before update on public.profiles
  for each row execute function public.set_updated_at();

-- Mirror new auth users into profiles so joins never miss a seller.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, email, display_name)
  values (new.id, coalesce(new.email, ''), split_part(coalesce(new.email, 'member'), '@', 1))
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ---------------------------------------------------------------- listings

create table if not exists public.listings (
  id               uuid primary key default gen_random_uuid(),
  seller_id        uuid not null references public.profiles (id) on delete cascade,
  title            text not null check (char_length(title) between 6 and 120),
  one_liner        text not null default '' check (char_length(one_liner) <= 160),
  description      text not null default '' check (char_length(description) <= 20000),
  category         text not null default 'other',
  asking_price     bigint not null check (asking_price > 0),
  annual_revenue   bigint not null default 0 check (annual_revenue >= 0),
  annual_profit    bigint check (annual_profit is null or annual_profit >= 0),
  currency         char(3) not null default 'USD',
  country          text not null default '',
  city             text not null default '',
  established_year int check (established_year is null or established_year between 1900 and 2100),
  status           listing_status not null default 'draft',
  image_urls       text[] not null default '{}',
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

create index if not exists listings_seller_idx on public.listings (seller_id, created_at desc);
create index if not exists listings_public_browse_idx on public.listings (status, created_at desc);
create index if not exists listings_category_idx on public.listings (category);
create index if not exists listings_price_idx on public.listings (asking_price);
create index if not exists listings_revenue_idx on public.listings (annual_revenue desc);

create trigger listings_set_updated_at
  before update on public.listings
  for each row execute function public.set_updated_at();

-- ------------------------------------------------------------------ offers

create table if not exists public.offers (
  id          uuid primary key default gen_random_uuid(),
  listing_id  uuid not null references public.listings (id) on delete cascade,
  buyer_id    uuid not null references public.profiles (id) on delete cascade,
  seller_id   uuid not null references public.profiles (id) on delete cascade,
  amount      bigint not null check (amount > 0),
  message     text not null default '' check (char_length(message) <= 2000),
  currency    char(3) not null default 'USD',
  status      offer_status not null default 'pending',
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  constraint offers_buyer_is_not_seller check (buyer_id <> seller_id)
);

create index if not exists offers_seller_status_idx on public.offers (seller_id, status, created_at desc);
create index if not exists offers_buyer_idx on public.offers (buyer_id, created_at desc);
create index if not exists offers_listing_idx on public.offers (listing_id, status);

-- At most one accepted offer per listing.
create unique index if not exists offers_one_accepted_per_listing
  on public.offers (listing_id)
  where status = 'accepted';

create trigger offers_set_updated_at
  before update on public.offers
  for each row execute function public.set_updated_at();

-- --------------------------------------------------------------- watchlist

create table if not exists public.watchlist (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references public.profiles (id) on delete cascade,
  listing_id uuid not null references public.listings (id) on delete cascade,
  created_at timestamptz not null default now(),
  constraint watchlist_unique_per_user unique (user_id, listing_id)
);

create index if not exists watchlist_user_idx on public.watchlist (user_id, created_at desc);

-- ----------------------------------------------------------- conversations

create table if not exists public.conversations (
  id         uuid primary key default gen_random_uuid(),
  listing_id uuid not null references public.listings (id) on delete cascade,
  buyer_id   uuid not null references public.profiles (id) on delete cascade,
  seller_id  uuid not null references public.profiles (id) on delete cascade,
  created_at timestamptz not null default now(),
  constraint conversations_unique_thread unique (listing_id, buyer_id),
  constraint conversations_participants_differ check (buyer_id <> seller_id)
);

create index if not exists conversations_buyer_idx on public.conversations (buyer_id);
create index if not exists conversations_seller_idx on public.conversations (seller_id);

-- ---------------------------------------------------------------- messages

create table if not exists public.messages (
  id               uuid primary key default gen_random_uuid(),
  conversation_id  uuid not null references public.conversations (id) on delete cascade,
  sender_id        uuid not null references public.profiles (id) on delete cascade,
  body             text not null check (char_length(body) between 1 and 4000),
  created_at       timestamptz not null default now()
);

create index if not exists messages_thread_idx on public.messages (conversation_id, created_at);

-- --------------------------------------------------------------------- RLS

alter table public.profiles enable row level security;
alter table public.listings enable row level security;
alter table public.offers enable row level security;
alter table public.watchlist enable row level security;
alter table public.conversations enable row level security;
alter table public.messages enable row level security;

-- profiles: participant identity is public because it is shown on listings.
drop policy if exists "profiles are readable" on public.profiles;
create policy "profiles are readable" on public.profiles
  for select using (true);

drop policy if exists "owners update their profile" on public.profiles;
create policy "owners update their profile" on public.profiles
  for update using (auth.uid() = id) with check (auth.uid() = id);

drop policy if exists "owners create their profile" on public.profiles;
create policy "owners create their profile" on public.profiles
  for insert with check (auth.uid() = id);

-- listings: published rows are world-readable, drafts only for the owner.
drop policy if exists "published listings are readable" on public.listings;
create policy "published listings are readable" on public.listings
  for select using (status = 'published' or seller_id = auth.uid());

drop policy if exists "sellers create their listings" on public.listings;
create policy "sellers create their listings" on public.listings
  for insert with check (auth.uid() = seller_id);

drop policy if exists "sellers update their listings" on public.listings;
create policy "sellers update their listings" on public.listings
  for update using (auth.uid() = seller_id) with check (auth.uid() = seller_id);

drop policy if exists "sellers delete their listings" on public.listings;
create policy "sellers delete their listings" on public.listings
  for delete using (auth.uid() = seller_id);

-- offers: visible to the two parties involved.
drop policy if exists "participants read offers" on public.offers;
create policy "participants read offers" on public.offers
  for select using (auth.uid() = buyer_id or auth.uid() = seller_id);

drop policy if exists "buyers create their offers" on public.offers;
create policy "buyers create their offers" on public.offers
  for insert with check (auth.uid() = buyer_id);

drop policy if exists "participants update offers" on public.offers;
create policy "participants update offers" on public.offers
  for update using (auth.uid() = buyer_id or auth.uid() = seller_id)
  with check (auth.uid() = buyer_id or auth.uid() = seller_id);

-- watchlist: strictly per user.
drop policy if exists "users manage their watchlist" on public.watchlist;
create policy "users manage their watchlist" on public.watchlist
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- conversations: only the buyer and the seller.
drop policy if exists "participants read conversations" on public.conversations;
create policy "participants read conversations" on public.conversations
  for select using (auth.uid() = buyer_id or auth.uid() = seller_id);

drop policy if exists "buyers start conversations" on public.conversations;
create policy "buyers start conversations" on public.conversations
  for insert with check (auth.uid() = buyer_id);

-- messages: sender must be a participant of the parent conversation.
drop policy if exists "participants read messages" on public.messages;
create policy "participants read messages" on public.messages
  for select using (
    exists (
      select 1 from public.conversations c
      where c.id = conversation_id and (c.buyer_id = auth.uid() or c.seller_id = auth.uid())
    )
  );

drop policy if exists "participants write messages" on public.messages;
create policy "participants write messages" on public.messages
  for insert with check (
    auth.uid() = sender_id and
    exists (
      select 1 from public.conversations c
      where c.id = conversation_id and (c.buyer_id = auth.uid() or c.seller_id = auth.uid())
    )
  );
