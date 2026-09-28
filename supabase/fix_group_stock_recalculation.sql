-- Correção de desempenho para o recálculo do estoque setorial.
-- Execute UMA VEZ no Supabase > SQL Editor.

create or replace function public.caged_group_recalculate_stock()
returns void
language plpgsql
as $$
begin
  with balances as (
    select ibge_code, group_name, competence, sum(balance)::bigint as balance
    from public.caged_group_monthly
    group by ibge_code, group_name, competence
  ),
  running as (
    select
      ibge_code,
      group_name,
      competence,
      sum(balance) over (
        partition by ibge_code, group_name
        order by competence
        rows between unbounded preceding and current row
      ) as accumulated_balance
    from balances
  ),
  reference_point as (
    select
      ref.ibge_code,
      ref.group_name,
      ref.reference_stock,
      coalesce((
        select run.accumulated_balance
        from running run
        where run.ibge_code = ref.ibge_code
          and run.group_name = ref.group_name
          and run.competence <= ref.reference_competence
        order by run.competence desc
        limit 1
      ), 0) as accumulated_at_reference
    from public.caged_group_reference_stock ref
  )
  update public.caged_group_monthly target
  set stock = point.reference_stock
    + run.accumulated_balance
    - point.accumulated_at_reference
  from running run
  join reference_point point
    on point.ibge_code = run.ibge_code
   and point.group_name = run.group_name
  where target.ibge_code = run.ibge_code
    and target.group_name = run.group_name
    and target.competence = run.competence;

  with balances as (
    select ibge_code, group_name, activity_name, competence, sum(balance)::bigint as balance
    from public.caged_group_detail_monthly
    group by ibge_code, group_name, activity_name, competence
  ),
  running as (
    select
      ibge_code,
      group_name,
      activity_name,
      competence,
      sum(balance) over (
        partition by ibge_code, group_name, activity_name
        order by competence
        rows between unbounded preceding and current row
      ) as accumulated_balance
    from balances
  ),
  reference_point as (
    select
      ref.ibge_code,
      ref.group_name,
      ref.activity_name,
      ref.reference_stock,
      coalesce((
        select run.accumulated_balance
        from running run
        where run.ibge_code = ref.ibge_code
          and run.group_name = ref.group_name
          and run.activity_name = ref.activity_name
          and run.competence <= ref.reference_competence
        order by run.competence desc
        limit 1
      ), 0) as accumulated_at_reference
    from public.caged_group_detail_reference_stock ref
  )
  update public.caged_group_detail_monthly target
  set stock = point.reference_stock
    + run.accumulated_balance
    - point.accumulated_at_reference
  from running run
  join reference_point point
    on point.ibge_code = run.ibge_code
   and point.group_name = run.group_name
   and point.activity_name = run.activity_name
  where target.ibge_code = run.ibge_code
    and target.group_name = run.group_name
    and target.activity_name = run.activity_name
    and target.competence = run.competence;
end;
$$;

select public.caged_group_recalculate_stock();
notify pgrst, 'reload schema';
