-- Série oficial revisada da Tabela 8.1, limitada à Região Administrativa de Araçatuba.
-- Execute uma vez no SQL Editor do novo projeto Supabase.

create table if not exists public.caged_official_monthly (
  competence date not null,
  ibge_code text not null references public.municipalities(ibge_code),
  stock integer not null default 0,
  admissions integer not null default 0,
  dismissals integer not null default 0,
  balance integer not null default 0,
  primary key (competence, ibge_code)
);

create table if not exists public.caged_official_imports (
  source_url text primary key,
  source_sha256 text not null,
  competence_start date not null,
  competence_end date not null,
  rows_imported integer not null,
  imported_at timestamptz not null default now()
);

alter table public.caged_official_monthly enable row level security;
alter table public.caged_official_imports enable row level security;

drop policy if exists "public reads official monthly" on public.caged_official_monthly;
create policy "public reads official monthly"
  on public.caged_official_monthly for select using (true);

drop policy if exists "public reads official imports" on public.caged_official_imports;
create policy "public reads official imports"
  on public.caged_official_imports for select using (true);

create or replace function public.caged_official_series(
  p_ibge_codes text[] default null
)
returns table (
  competence date,
  stock bigint,
  admissions bigint,
  dismissals bigint,
  balance bigint
)
language sql stable
as $$
  select
    c.competence,
    sum(c.stock)::bigint,
    sum(c.admissions)::bigint,
    sum(c.dismissals)::bigint,
    sum(c.balance)::bigint
  from public.caged_official_monthly c
  where p_ibge_codes is null or c.ibge_code = any(p_ibge_codes)
  group by c.competence
  order by c.competence;
$$;

create or replace function public.caged_state_balance(
  p_competences date[] default null,
  p_ibge_codes text[] default null,
  p_uf_codes text[] default null
)
returns table (uf_code text, balance bigint)
language sql stable
as $$
  select
    '35'::text as uf_code,
    sum(c.balance)::bigint as balance
  from public.caged_official_monthly c
  where
    (p_competences is null or c.competence = any(p_competences))
    and (p_ibge_codes is null or c.ibge_code = any(p_ibge_codes))
    and (p_uf_codes is null or '35' = any(p_uf_codes));
$$;

notify pgrst, 'reload schema';
