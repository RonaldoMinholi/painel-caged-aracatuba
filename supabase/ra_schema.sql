-- Banco leve: somente Região Administrativa de Araçatuba.
-- Execute uma vez no SQL Editor do novo projeto Supabase.

create table if not exists public.municipalities (
  ibge_code text primary key,
  name text not null,
  territory text not null default 'Região Administrativa de Araçatuba',
  is_regional boolean not null default true
);

create table if not exists public.caged_monthly (
  competence date not null,
  ibge_code text not null references public.municipalities(ibge_code),
  cnae_section text not null default 'Não informado',
  sex text not null default 'Não informado',
  age_band text not null default 'Não informado',
  education text not null default 'Não informado',
  admissions integer not null default 0,
  dismissals integer not null default 0,
  balance integer not null default 0,
  primary key (competence, ibge_code, cnae_section, sex, age_band, education)
);

create table if not exists public.caged_imports (
  competence date primary key,
  source_url text not null,
  source_sha256 text not null,
  imported_at timestamptz not null default now(),
  rows_processed integer not null,
  status text not null default 'completed'
);

alter table public.municipalities enable row level security;
alter table public.caged_monthly enable row level security;
alter table public.caged_imports enable row level security;

drop policy if exists "public reads municipalities" on public.municipalities;
create policy "public reads municipalities"
  on public.municipalities for select using (true);

drop policy if exists "public reads caged monthly" on public.caged_monthly;
create policy "public reads caged monthly"
  on public.caged_monthly for select using (true);

drop policy if exists "public reads caged imports" on public.caged_imports;
create policy "public reads caged imports"
  on public.caged_imports for select using (true);

create or replace function public.caged_municipalities()
returns table (ibge_code text, name text, territory text, is_regional boolean)
language sql stable
as $$
  select m.ibge_code, m.name, m.territory, m.is_regional
  from public.municipalities m
  where m.is_regional
  order by m.name;
$$;

create or replace function public.caged_detail_series(
  p_ibge_codes text[] default null,
  p_sections text[] default null,
  p_sexes text[] default null
)
returns table (
  competence date,
  admissions bigint,
  dismissals bigint,
  balance bigint
)
language sql stable
as $$
  select
    c.competence,
    sum(c.admissions)::bigint,
    sum(c.dismissals)::bigint,
    sum(c.balance)::bigint
  from public.caged_monthly c
  where
    (p_ibge_codes is null or c.ibge_code = any(p_ibge_codes))
    and (p_sections is null or c.cnae_section = any(p_sections))
    and (p_sexes is null or c.sex = any(p_sexes))
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
  from public.caged_monthly c
  where
    (p_competences is null or c.competence = any(p_competences))
    and (p_ibge_codes is null or c.ibge_code = any(p_ibge_codes))
    and (p_uf_codes is null or '35' = any(p_uf_codes));
$$;

create or replace function public.caged_detail_state_balance(
  p_competences date[] default null,
  p_ibge_codes text[] default null,
  p_sections text[] default null,
  p_sexes text[] default null
)
returns table (uf_code text, balance bigint)
language sql stable
as $$
  select
    '35'::text as uf_code,
    sum(c.balance)::bigint as balance
  from public.caged_monthly c
  where
    (p_competences is null or c.competence = any(p_competences))
    and (p_ibge_codes is null or c.ibge_code = any(p_ibge_codes))
    and (p_sections is null or c.cnae_section = any(p_sections))
    and (p_sexes is null or c.sex = any(p_sexes));
$$;

notify pgrst, 'reload schema';
