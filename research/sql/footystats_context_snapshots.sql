-- Research-only durable context snapshot table.
-- Apply explicitly to the intended Supabase project before enabling CONTEXT_SNAPSHOT_STORE=SUPABASE.

create table if not exists public.footystats_context_snapshots (
    record_sha256 text primary key,
    record_id text not null,
    match_id bigint not null,
    captured_at_utc timestamptz not null,
    kickoff_at_utc timestamptz not null,
    home_team text not null,
    away_team text not null,
    current_context_sha256 text not null,
    five_file_manifest_sha256 text not null,
    snapshot jsonb not null,
    inserted_at timestamptz not null default now()
);

create index if not exists footystats_context_snapshots_match_id_idx
    on public.footystats_context_snapshots(match_id);

create index if not exists footystats_context_snapshots_captured_at_idx
    on public.footystats_context_snapshots(captured_at_utc);

alter table public.footystats_context_snapshots enable row level security;

-- No public RLS policy is created. The research server uses a server-side
-- service-role key only when explicitly configured. Never expose that key to
-- the browser or iPhone shortcut.
