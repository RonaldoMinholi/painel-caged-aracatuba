-- Página 4: Grande Grupo Ocupacional (CBO 2002).
-- Execute UMA VEZ no SQL Editor do Supabase antes de reimportar os meses CAGEDMOV.

create table if not exists public.caged_occupation_monthly (
  competence date not null,
  ibge_code text not null references public.municipalities(ibge_code),
  occupation_group text not null,
  admissions integer not null default 0,
  dismissals integer not null default 0,
  balance integer not null default 0,
  dismissal_tenure_sum numeric not null default 0,
  dismissal_tenure_count integer not null default 0,
  primary key (competence, ibge_code, occupation_group)
);

alter table public.caged_occupation_monthly enable row level security;
drop policy if exists "public reads caged occupation monthly" on public.caged_occupation_monthly;
create policy "public reads caged occupation monthly"
  on public.caged_occupation_monthly for select using (true);

create or replace function public.caged_occupation_summary(
  p_competences date[] default null,
  p_ibge_codes text[] default null
)
returns table (
  occupation_group text,
  admissions bigint,
  dismissals bigint,
  balance bigint,
  average_dismissal_tenure numeric
)
language sql stable as $$
  select
    c.occupation_group,
    sum(c.admissions)::bigint,
    sum(c.dismissals)::bigint,
    sum(c.balance)::bigint,
    case when sum(c.dismissal_tenure_count) = 0 then null
      else round(sum(c.dismissal_tenure_sum) / sum(c.dismissal_tenure_count), 1)
    end
  from public.caged_occupation_monthly c
  where
    (p_competences is null or c.competence = any(p_competences))
    and (p_ibge_codes is null or c.ibge_code = any(p_ibge_codes))
  group by c.occupation_group
  order by c.occupation_group;
$$;

notify pgrst, 'reload schema';
