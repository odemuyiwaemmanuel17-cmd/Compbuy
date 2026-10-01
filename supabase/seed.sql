-- Compbuy demo data
-- Run after 0002_nda_data_room.sql:  supabase db reset  (applies every migration, then this)
--
-- Creates three sign-in-able demo accounts:
--   seller@compbuy.demo      / demo-password
--   buyer@compbuy.demo       / demo-password
--   other@compbuy.demo       / demo-password
--
-- The demo data deliberately covers each data-room state: one signed NDA (buyer
-- can read listing 1 in full), one approved-and-awaiting-signature, and one
-- pending request waiting on the seller.

insert into auth.users (
  instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
  created_at, updated_at, confirmation_sent_at
)
values
  ('00000000-0000-0000-0000-000000000000', '11111111-1111-4111-8111-111111111111', 'authenticated', 'authenticated',
   'seller@compbuy.demo', crypt('demo-password', gen_salt('bf')), now(), now(), now(), now()),
  ('00000000-0000-0000-0000-000000000000', '22222222-2222-4222-8222-222222222222', 'authenticated', 'authenticated',
   'buyer@compbuy.demo', crypt('demo-password', gen_salt('bf')), now(), now(), now(), now()),
  ('00000000-0000-0000-0000-000000000000', '33333333-3333-4333-8333-333333333333', 'authenticated', 'authenticated',
   'other@compbuy.demo', crypt('demo-password', gen_salt('bf')), now(), now(), now(), now())
on conflict (id) do nothing;

insert into public.profiles (id, email, display_name, company_name, location)
values
  ('11111111-1111-4111-8111-111111111111', 'seller@compbuy.demo', 'Priya Nair', 'Ledgerly', 'Lisbon, Portugal'),
  ('22222222-2222-4222-8222-222222222222', 'buyer@compbuy.demo', 'Marco Silva', '', 'Berlin, Germany'),
  ('33333333-3333-4333-8333-333333333333', 'other@compbuy.demo', 'Dana White', 'Northwind Labs', 'Austin, USA')
on conflict (id) do nothing;

-- monthly_revenue x 12 and annual_revenue stay consistent by construction:
-- the app derives the annual figure from the monthly one, never the reverse.
insert into public.listings (
  id, seller_id, title, business_name, one_liner, description, reason_for_selling,
  category, asking_price, monthly_revenue, net_profit, annual_revenue, annual_profit,
  revenue_band, currency, country, city, established_year, status
)
values
  ('a1000000-0000-4000-8000-000000000001', '11111111-1111-4111-8111-111111111111',
   'Ledgerly — bookkeeping SaaS for freelancers',
   'Ledgerly Software Unipessoal Lda.',
   'Bootstrap-built accounting tool with 480 paying customers and 91% gross retention.',
   'Ledgerly is a self-serve bookkeeping platform for freelancers and one-person agencies. '
   'The product is feature complete, the stack is Rails plus Sidekiq, and support takes under two hours on average. '
   'Selling to focus on a new venture; the full codebase, domain, customer list and twelve months of financials transfer.',
   'I am moving to a full-time role at another company and cannot run this properly on the side.',
   'saas', 780000, 20000, 8000, 240000, 96000, 'under_250k', 'USD', 'Portugal', 'Lisbon', 2019, 'published'),

  ('a1000000-0000-4000-8000-000000000002', '11111111-1111-4111-8111-111111111111',
   'Shopfuse — Shopify theme marketplace',
   'Shopfuse Commerce Lda.',
   'Digital product marketplace with 12k creators and no inventory risk.',
   'Shopfuse sells premium Shopify themes through a creator revenue-share model. Traffic is almost entirely organic, '
   'and the marketplace takes a 25% commission on every sale. Includes the marketplace codebase and creator agreements.',
   'Two co-founders split and neither wants to run the marketplace alone.',
   'marketplace', 420000, 13333, 4333, 160000, 52000, 'under_250k', 'USD', 'Portugal', 'Lisbon', 2020, 'published'),

  ('a1000000-0000-4000-8000-000000000003', '33333333-3333-4333-8333-333333333333',
   'Northwind Content — niche publishing portfolio',
   'Northwind Media LLC',
   'Three content sites earning on display ads with 78% margin.',
   'A portfolio of three programmatic-adjacent content sites in the travel and home categories. '
   'Ad revenue is diversified across Mediavine and direct sponsors. Two of the three sites rank on page one for their core terms.',
   'Portfolio is too large to edit well; buying a smaller set of sites instead.',
   'content', 265000, 9833, 7667, 118000, 92000, 'under_250k', 'USD', 'United States', 'Austin', 2018, 'published'),

  ('a1000000-0000-4000-8000-000000000004', '33333333-3333-4333-8333-333333333333',
   'RetainIQ — churn analytics for subscription boxes',
   'RetainIQ Data Labs LLC',
   'Vertical analytics tool with 62 subscribers and founder-led support.',
   'RetainIQ connects to Shopify and Recharge to flag at-risk subscription customers. '
   'The codebase is Django plus HTMX. Ideal for a buyer in the commerce-tools space who wants an existing integration surface.',
   'I want to go back to full-time engineering and this has sat unbilled for a year.',
   'saas', 180000, 5333, 1750, 64000, 21000, 'under_250k', 'USD', 'United States', 'Austin', 2021, 'published'),

  ('a1000000-0000-4000-8000-000000000005', '11111111-1111-4111-8111-111111111111',
   'Brightline Studio — brand agency with recurring retainers',
   'Brightline Studio Unipessoal Lda.',
   'Nine clients on monthly retainers, 60% of revenue is recurring.',
   'A twelve-person brand studio. Work is design systems and packaging for consumer startups. '
   'Selling includes client relationships, the studio SOP library, and a six-month pipeline.',
   'Relocating to Portugal makes the Portuguese client base harder to serve in person.',
   'agency', 540000, 25000, 7000, 300000, 84000, '250k_to_1m', 'EUR', 'Portugal', 'Porto', 2016, 'published'),

  ('a1000000-0000-4000-8000-000000000006', '33333333-3333-4333-8333-333333333333',
   'Kettle & Co — specialty coffee ecommerce',
   'Kettle and Company Roasters LLC',
   'Subscription-led coffee roaster with its own roastery contract.',
   'Kettle & Co sells single-origin coffee through one-time and subscription orders. '
   'Includes the brand, Shopify store, email list of 22k subscribers, and a transferable roasting contract.',
   'Margin compressed after the roastery contract renewed and I cannot fund inventory.',
   'ecommerce', 310000, 12083, 2750, 145000, 33000, 'under_250k', 'USD', 'United States', 'Denver', 2017, 'published'),

  ('a1000000-0000-4000-8000-000000000007', '11111111-1111-4111-8111-111111111111',
   'Draft: unpublished ops playbook site',
   'Ledgerly Playbooks Unipessoal Lda.',
   'Being prepared for sale once a year of financials is available.',
   'This listing is intentionally left as a draft so the marketplace has unpublished data to filter out. '
   'It must never appear in public browse or search results.',
   'Not decided yet — testing whether a playbook product has a market.',
   'content', 90000, 2500, 1000, 30000, 12000, 'under_250k', 'USD', 'Portugal', 'Lisbon', 2023, 'draft')
on conflict (id) do nothing;

insert into public.watchlist (user_id, listing_id)
values
  ('22222222-2222-4222-8222-222222222222', 'a1000000-0000-4000-8000-000000000001'),
  ('22222222-2222-4222-8222-222222222222', 'a1000000-0000-4000-8000-000000000003')
on conflict (user_id, listing_id) do nothing;

insert into public.offers (listing_id, buyer_id, seller_id, amount, message, currency, status, kind)
values
  ('a1000000-0000-4000-8000-000000000001', '22222222-2222-4222-8222-222222222222', '11111111-1111-4111-8111-111111111111',
   700000, 'Cash close within 45 days, would like three months of escrow.', 'USD', 'pending', 'offer'),
  ('a1000000-0000-4000-8000-000000000003', '22222222-2222-4222-8222-222222222222', '33333333-3333-4333-8333-333333333333',
   240000, 'I run two similar portfolios and can absorb these sites quickly.', 'USD', 'pending', 'loi')
on conflict do nothing;

-- One signed, one approved (awaiting signature), one pending, one declined.
insert into public.nda_requests (listing_id, buyer_id, seller_id, status, message, signed_name, signed_at)
values
  ('a1000000-0000-4000-8000-000000000001', '22222222-2222-4222-8222-222222222222', '11111111-1111-4111-8111-111111111111',
   'signed', 'Solo buyer, funds in place, can close in 45 days.', 'Marco Silva', now() - interval '3 days'),
  ('a1000000-0000-4000-8000-000000000002', '33333333-3333-4333-8333-333333333333', '11111111-1111-4111-8111-111111111111',
   'approved', 'I run a theme shop myself and can bring creators across.', '', null),
  ('a1000000-0000-4000-8000-000000000003', '22222222-2222-4222-8222-222222222222', '33333333-3333-4333-8333-333333333333',
   'pending', 'Operator with two similar portfolios, would like to review the financials.', '', null),
  ('a1000000-0000-4000-8000-000000000006', '22222222-2222-4222-8222-222222222222', '33333333-3333-4333-8333-333333333333',
   'rejected', 'Just curious what the numbers look like.', '', null)
on conflict (listing_id, buyer_id) do nothing;

insert into public.conversations (listing_id, buyer_id, seller_id)
values
  ('a1000000-0000-4000-8000-000000000001', '22222222-2222-4222-8222-222222222222', '11111111-1111-4111-8111-111111111111'),
  ('a1000000-0000-4000-8000-000000000003', '22222222-2222-4222-8222-222222222222', '33333333-3333-4333-8333-333333333333')
on conflict (listing_id, buyer_id) do nothing;

insert into public.messages (conversation_id, sender_id, body)
select
  c.id,
  c.buyer_id,
  'Thanks for the look — happy to share the financials under NDA.'
from public.conversations c
where c.listing_id = 'a1000000-0000-4000-8000-000000000001'
  and not exists (select 1 from public.messages m where m.conversation_id = c.id);
