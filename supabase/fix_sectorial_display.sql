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


-- Recebe um lote mensal do Power BI oficial e atualiza exclusivamente
-- a coluna Tempo de Emprego. As outras métricas permanecem intactas.
create or replace function public.caged_group_apply_official_tenure(
  p_competence date,
  p_groups jsonb,
  p_details jsonb
)
returns void
language plpgsql
as $body$
begin
  update public.caged_group_monthly target
  set
    dismissal_tenure_sum = source.dismissal_tenure_sum,
    dismissal_tenure_count = source.dismissal_tenure_count
  from jsonb_to_recordset(coalesce(p_groups, '[]'::jsonb)) as source(
    ibge_code text,
    group_name text,
    dismissal_tenure_sum numeric,
    dismissal_tenure_count integer
  )
  where target.competence = p_competence
    and target.ibge_code = source.ibge_code
    and target.group_name = source.group_name;

  update public.caged_group_detail_monthly target
  set
    dismissal_tenure_sum = source.dismissal_tenure_sum,
    dismissal_tenure_count = source.dismissal_tenure_count
  from jsonb_to_recordset(coalesce(p_details, '[]'::jsonb)) as source(
    ibge_code text,
    group_name text,
    activity_name text,
    dismissal_tenure_sum numeric,
    dismissal_tenure_count integer
  )
  where target.competence = p_competence
    and target.ibge_code = source.ibge_code
    and target.group_name = source.group_name
    and target.activity_name = source.activity_name;
end;
$body$;


-- Correção equivalente para a página Características do Trabalhador (CBO).
-- A média é a medida publicada pelo Power BI oficial; fluxos não são alterados.
create or replace function public.caged_occupation_apply_official_tenure(
  p_competence date,
  p_occupations jsonb
)
returns void
language plpgsql
as $body$
begin
  update public.caged_occupation_monthly target
  set
    dismissal_tenure_sum = source.average_dismissal_tenure * target.dismissals,
    dismissal_tenure_count = target.dismissals
  from jsonb_to_recordset(coalesce(p_occupations, '[]'::jsonb)) as source(
    ibge_code text,
    occupation_group text,
    average_dismissal_tenure numeric
  )
  where target.competence = p_competence
    and target.ibge_code = source.ibge_code
    and target.occupation_group = source.occupation_group
    and target.dismissals > 0;

  update public.caged_occupation_worker_monthly target
  set average_dismissal_tenure = source.average_dismissal_tenure
  from jsonb_to_recordset(coalesce(p_occupations, '[]'::jsonb)) as source(
    ibge_code text,
    occupation_group text,
    average_dismissal_tenure numeric
  )
  where target.competence = p_competence
    and target.ibge_code = source.ibge_code
    and target.occupation_group = source.occupation_group;
end;
$body$;

notify pgrst, 'reload schema';


create or replace function public.caged_occupation_summary(p_competences date[] default null,p_ibge_codes text[] default null)
returns table (occupation_group text,admissions bigint,dismissals bigint,balance bigint,average_dismissal_tenure numeric)
language sql stable as $body$
 select c.occupation_group,sum(c.admissions)::bigint,sum(c.dismissals)::bigint,sum(c.balance)::bigint,
 case when sum(c.dismissal_tenure_count)=0 then null else round(sum(c.dismissal_tenure_sum)/sum(c.dismissal_tenure_count),1) end
 from public.caged_occupation_monthly c
 where (p_competences is null or c.competence=any(p_competences)) and (p_ibge_codes is null or c.ibge_code=any(p_ibge_codes))
 group by c.occupation_group order by c.occupation_group;
$body$;

create or replace function public.caged_occupation_replace_official_summary(p_competence date,p_occupations jsonb)
returns void language plpgsql as $body$
begin
 delete from public.caged_occupation_monthly where competence=p_competence;
 insert into public.caged_occupation_monthly (competence,ibge_code,occupation_group,admissions,dismissals,balance,dismissal_tenure_sum,dismissal_tenure_count)
 select p_competence,source.ibge_code,source.occupation_group,source.admissions,source.dismissals,source.admissions-source.dismissals,source.average_dismissal_tenure*source.dismissals,source.dismissals
 from jsonb_to_recordset(coalesce(p_occupations,'[]'::jsonb)) as source(ibge_code text,occupation_group text,admissions integer,dismissals integer,average_dismissal_tenure numeric);
end;
$body$;
notify pgrst, 'reload schema';
