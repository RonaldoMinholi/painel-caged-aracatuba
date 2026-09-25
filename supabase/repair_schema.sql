-- Execute este arquivo uma única vez no SQL Editor do Supabase.
-- Ele cria as tabelas auxiliares e as funções RPC usadas pelo painel.

create table if not exists public.caged_official_monthly (
  competence date not null,
  ibge_code text not null references public.municipalities(ibge_code),
  stock integer not null default 0,
  admissions integer not null default 0,
  dismissals integer not null default 0,
  balance integer not null default 0,
  source_url text,
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

create table if not exists public.caged_movement_cube (
  competence date not null,
  geography_level text not null check (geography_level in ('country', 'state', 'municipality')),
  geography_code text not null,
  cnae_section text not null default 'Não informado',
  sex text not null default 'Não informado',
  admissions integer not null default 0,
  dismissals integer not null default 0,
  balance integer not null default 0,
  primary key (competence, geography_level, geography_code, cnae_section, sex)
);

alter table public.caged_official_monthly enable row level security;
alter table public.caged_official_imports enable row level security;
alter table public.caged_movement_cube enable row level security;

drop policy if exists "public reads official monthly" on public.caged_official_monthly;
create policy "public reads official monthly"
  on public.caged_official_monthly for select using (true);

drop policy if exists "public reads official imports" on public.caged_official_imports;
create policy "public reads official imports"
  on public.caged_official_imports for select using (true);

drop policy if exists "public reads movement cube" on public.caged_movement_cube;
create policy "public reads movement cube"
  on public.caged_movement_cube for select using (true);

create or replace function public.caged_municipalities()
returns table (ibge_code text, name text, territory text, is_regional boolean)
language sql stable
as $$
  select m.ibge_code, m.name, m.territory, m.is_regional
  from public.municipalities m
  order by m.name;
$$;

create or replace function public.caged_official_series(
  p_ibge_codes text[] default null,
  p_uf_codes text[] default null
)
returns table (
  competence date,
  admissions bigint,
  dismissals bigint,
  balance bigint,
  stock bigint
)
language sql stable
as $$
  select
    o.competence,
    sum(o.admissions)::bigint,
    sum(o.dismissals)::bigint,
    sum(o.balance)::bigint,
    sum(o.stock)::bigint
  from public.caged_official_monthly o
  where
    (p_ibge_codes is null or o.ibge_code = any(p_ibge_codes))
    and
    (p_uf_codes is null or left(o.ibge_code, 2) = any(p_uf_codes))
  group by o.competence
  order by o.competence;
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

create or replace function public.caged_cube_series(
  p_geography_level text,
  p_geography_codes text[],
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
  from public.caged_movement_cube c
  where c.geography_level = p_geography_level
    and c.geography_code = any(p_geography_codes)
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
    left(o.ibge_code, 2) as uf_code,
    sum(o.balance)::bigint
  from public.caged_official_monthly o
  where
    (p_competences is null or o.competence = any(p_competences))
    and (p_ibge_codes is null or o.ibge_code = any(p_ibge_codes))
    and (p_uf_codes is null or left(o.ibge_code, 2) = any(p_uf_codes))
  group by left(o.ibge_code, 2);
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
    left(c.ibge_code, 2) as uf_code,
    sum(c.balance)::bigint
  from public.caged_monthly c
  where
    (p_competences is null or c.competence = any(p_competences))
    and (p_ibge_codes is null or c.ibge_code = any(p_ibge_codes))
    and (p_sections is null or c.cnae_section = any(p_sections))
    and (p_sexes is null or c.sex = any(p_sexes))
  group by left(c.ibge_code, 2);
$$;

create or replace function public.caged_cube_state_balance(
  p_competences date[] default null,
  p_ibge_codes text[] default null,
  p_uf_codes text[] default null,
  p_sections text[] default null,
  p_sexes text[] default null
)
returns table (uf_code text, balance bigint)
language sql stable
as $$
  select
    case
      when c.geography_level = 'state' then c.geography_code
      when c.geography_level = 'municipality' then left(c.geography_code, 2)
      else null
    end as uf_code,
    sum(c.balance)::bigint
  from public.caged_movement_cube c
  where
    c.geography_level in ('state', 'municipality')
    and (p_competences is null or c.competence = any(p_competences))
    and (
      p_ibge_codes is null
      or (c.geography_level = 'municipality' and c.geography_code = any(p_ibge_codes))
    )
    and (
      p_uf_codes is null
      or (
        c.geography_level = 'state' and c.geography_code = any(p_uf_codes)
      )
      or (
        c.geography_level = 'municipality' and left(c.geography_code, 2) = any(p_uf_codes)
      )
    )
    and (p_sections is null or c.cnae_section = any(p_sections))
    and (p_sexes is null or c.sex = any(p_sexes))
  group by 1;
$$;

create or replace function public.refresh_caged_official_national()
returns void
language plpgsql
as $$
begin
  -- A série nacional é calculada diretamente por caged_official_series.
  -- A função existe para compatibilidade com o importador.
  return;
end;
$$;

notify pgrst, 'reload schema';
