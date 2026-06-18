-- Supabase migration for China game dashboard live genre edits.
-- This table stores only manual overrides. The dashboard keeps the full 1,000-row
-- dataset embedded/static, then applies these overrides in real time.

create table if not exists public.dashboard_genre_edits (
  app_id text primary key,
  game_name text,
  big text not null,
  sub text not null,
  big_ko text,
  sub_ko text,
  updated_by text,
  updated_at timestamptz not null default now()
);

alter table public.dashboard_genre_edits enable row level security;

drop policy if exists "dashboard_genre_edits_public_select" on public.dashboard_genre_edits;
create policy "dashboard_genre_edits_public_select"
  on public.dashboard_genre_edits
  for select
  to anon, authenticated
  using (true);

drop policy if exists "dashboard_genre_edits_public_insert" on public.dashboard_genre_edits;
create policy "dashboard_genre_edits_public_insert"
  on public.dashboard_genre_edits
  for insert
  to anon, authenticated
  with check (
    app_id is not null and length(app_id) > 0
    and big is not null and length(big) > 0
    and sub is not null and length(sub) > 0
  );

drop policy if exists "dashboard_genre_edits_public_update" on public.dashboard_genre_edits;
create policy "dashboard_genre_edits_public_update"
  on public.dashboard_genre_edits
  for update
  to anon, authenticated
  using (true)
  with check (
    app_id is not null and length(app_id) > 0
    and big is not null and length(big) > 0
    and sub is not null and length(sub) > 0
  );

create index if not exists dashboard_genre_edits_updated_at_idx
  on public.dashboard_genre_edits (updated_at desc);

do $$
begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    begin
      alter publication supabase_realtime add table public.dashboard_genre_edits;
    exception when duplicate_object then
      null;
    end;
  end if;
end $$;
