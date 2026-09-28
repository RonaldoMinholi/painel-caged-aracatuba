-- Correção de exibição da página Setorial.
-- Execute UMA VEZ no Supabase > SQL Editor, depois de 1º de outubro.
-- Não reimporta arquivos e não recalcula estoque: apenas substitui as consultas
-- usadas pelo painel para aplicar a fórmula oficial de variação relativa.

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
  ),
  aggregated as (
    select
      s.group_name,
      sum(s.admissions)::bigint as admissions,
      sum(s.dismissals)::bigint as dismissals,
      sum(s.balance)::bigint as balance,
      case when sum(s.dismissal_tenure_count) = 0 then null
        else round(sum(s.dismissal_tenure_sum) / sum(s.dismissal_tenure_count), 1)
      end as average_dismissal_tenure,
      sum(s.stock) filter (where s.competence = (select competence from latest))::bigint as stock
    from selected s
    group by s.group_name
  )
  select
    a.group_name, a.admissions, a.dismissals, a.balance,
    a.average_dismissal_tenure, a.stock,
    case when coalesce(a.stock - a.balance, 0) = 0 then null
      else round(100.0 * a.balance / (a.stock - a.balance), 2)
    end
  from aggregated a
  order by a.group_name;
$$;

create or replace function public.caged_group_detail_summary(
  p_competences date[] default null,
  p_ibge_codes text[] default null
)
returns table (
  group_name text,
  activity_name text,
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
    from public.caged_group_detail_monthly c
    where
      (p_competences is null or c.competence = any(p_competences))
      and (p_ibge_codes is null or c.ibge_code = any(p_ibge_codes))
  ),
  latest as (
    select max(competence) as competence from selected
  ),
  aggregated as (
    select
      s.group_name,
      s.activity_name,
      sum(s.admissions)::bigint as admissions,
      sum(s.dismissals)::bigint as dismissals,
      sum(s.balance)::bigint as balance,
      case when sum(s.dismissal_tenure_count) = 0 then null
        else round(sum(s.dismissal_tenure_sum) / sum(s.dismissal_tenure_count), 1)
      end as average_dismissal_tenure,
      sum(s.stock) filter (where s.competence = (select competence from latest))::bigint as stock
    from selected s
    group by s.group_name, s.activity_name
  )
  select
    a.group_name, a.activity_name, a.admissions, a.dismissals, a.balance,
    a.average_dismissal_tenure, a.stock,
    case when coalesce(a.stock - a.balance, 0) = 0 then null
      else round(100.0 * a.balance / (a.stock - a.balance), 2)
    end
  from aggregated a
  order by a.group_name, a.activity_name;
$$;

notify pgrst, 'reload schema';
