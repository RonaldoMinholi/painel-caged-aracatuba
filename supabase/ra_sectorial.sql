-- Dados para a página Setorial, em nível de município e Grande Grupamento.
-- Execute este arquivo UMA VEZ no SQL Editor do Supabase.

create table if not exists public.caged_group_reference_stock (
  ibge_code text not null references public.municipalities(ibge_code),
  group_name text not null,
  reference_stock integer not null default 0,
  primary key (ibge_code, group_name)
);

create table if not exists public.caged_group_monthly (
  competence date not null,
  ibge_code text not null references public.municipalities(ibge_code),
  group_name text not null,
  admissions integer not null default 0,
  dismissals integer not null default 0,
  balance integer not null default 0,
  dismissal_tenure_sum numeric not null default 0,
  dismissal_tenure_count integer not null default 0,
  stock integer,
  primary key (competence, ibge_code, group_name)
);

alter table public.caged_group_reference_stock enable row level security;
alter table public.caged_group_monthly enable row level security;

drop policy if exists "public reads caged group reference stock" on public.caged_group_reference_stock;
create policy "public reads caged group reference stock"
  on public.caged_group_reference_stock for select using (true);

drop policy if exists "public reads caged group monthly" on public.caged_group_monthly;
create policy "public reads caged group monthly"
  on public.caged_group_monthly for select using (true);

-- O Estoque de Referência 2026 corresponde ao estoque no fim de dezembro de 2025.
-- A função reconstrói cada mês somando ou subtraindo os saldos mensais do Novo CAGED.
create or replace function public.caged_group_recalculate_stock()
returns void
language sql
as $$
  update public.caged_group_monthly target
  set stock = (
    select coalesce((
        select ref.reference_stock
        from public.caged_group_reference_stock ref
        where ref.ibge_code = target.ibge_code
          and ref.group_name = target.group_name
      ), 0) + coalesce(sum(
          case
            when movement.competence > date '2025-12-01'
             and movement.competence <= target.competence
              then movement.balance
            when movement.competence > target.competence
             and movement.competence <= date '2025-12-01'
              then -movement.balance
            else 0
          end
        ), 0)::integer
    from public.caged_group_monthly movement
    where movement.ibge_code = target.ibge_code
      and movement.group_name = target.group_name
  );
$$;

create or replace function public.caged_group_summary(
  p_competences date[] default null,
  p_ibge_codes text[] default null
)
returns table (
  group_name text,
  admissions bigint,
  dismissals bigint,
  balance bigint,
  average_dismissal_tenure numeric,
  stock bigint,
  relative_variation numeric
)
language sql stable
as $$
  with selected as (
    select *
    from public.caged_group_monthly c
    where
      (p_competences is null or c.competence = any(p_competences))
      and (p_ibge_codes is null or c.ibge_code = any(p_ibge_codes))
  ),
  latest as (
    select max(competence) as competence from selected
  )
  select
    s.group_name,
    sum(s.admissions)::bigint,
    sum(s.dismissals)::bigint,
    sum(s.balance)::bigint,
    case when sum(s.dismissal_tenure_count) = 0 then null
      else round(sum(s.dismissal_tenure_sum) / sum(s.dismissal_tenure_count), 1)
    end,
    sum(s.stock) filter (where s.competence = (select competence from latest))::bigint,
    case
      when sum(s.stock) filter (where s.competence = (select competence from latest)) = 0 then null
      else round(
        100.0 * sum(s.balance)
        / sum(s.stock) filter (where s.competence = (select competence from latest)),
        2
      )
    end
  from selected s
  group by s.group_name
  order by s.group_name;
$$;

notify pgrst, 'reload schema';
