-- Correção definitiva de desempenho para o recálculo do estoque setorial.
-- Execute este arquivo uma única vez no Supabase > SQL Editor.
-- Ele substitui a versão anterior, que tinha subconsultas correlacionadas e
-- estourava o limite de tempo da API quando havia muitos meses importados.

create index if not exists caged_group_monthly_stock_calc_idx
  on public.caged_group_monthly (ibge_code, group_name, competence);

create index if not exists caged_group_detail_monthly_stock_calc_idx
  on public.caged_group_detail_monthly (ibge_code, group_name, activity_name, competence);

create index if not exists caged_group_reference_stock_calc_idx
  on public.caged_group_reference_stock (ibge_code, group_name, reference_competence);

create index if not exists caged_group_detail_reference_stock_calc_idx
  on public.caged_group_detail_reference_stock (ibge_code, group_name, activity_name, reference_competence);

create or replace function public.caged_group_recalculate_stock()
returns void
language sql
as $$
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
      coalesce(sum(balance.balance) filter (
        where balance.competence <= ref.reference_competence
      ), 0) as accumulated_at_reference
    from public.caged_group_reference_stock ref
    left join balances balance
      on balance.ibge_code = ref.ibge_code
     and balance.group_name = ref.group_name
    group by
      ref.ibge_code, ref.group_name, ref.reference_stock, ref.reference_competence
  )
  update public.caged_group_monthly target
  set stock = point.reference_stock + run.accumulated_balance - point.accumulated_at_reference
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
      coalesce(sum(balance.balance) filter (
        where balance.competence <= ref.reference_competence
      ), 0) as accumulated_at_reference
    from public.caged_group_detail_reference_stock ref
    left join balances balance
      on balance.ibge_code = ref.ibge_code
     and balance.group_name = ref.group_name
     and balance.activity_name = ref.activity_name
    group by
      ref.ibge_code, ref.group_name, ref.activity_name,
      ref.reference_stock, ref.reference_competence
  )
  update public.caged_group_detail_monthly target
  set stock = point.reference_stock + run.accumulated_balance - point.accumulated_at_reference
  from running run
  join reference_point point
    on point.ibge_code = run.ibge_code
   and point.group_name = run.group_name
   and point.activity_name = run.activity_name
  where target.ibge_code = run.ibge_code
    and target.group_name = run.group_name
    and target.activity_name = run.activity_name
    and target.competence = run.competence;
$$;

select public.caged_group_recalculate_stock();
notify pgrst, 'reload schema';
