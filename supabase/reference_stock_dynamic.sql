-- Executar uma única vez no SQL Editor do Supabase.
-- Guarda a competência de referência de cada arquivo de estoque e elimina
-- a âncora fixa em dezembro de 2025.

alter table public.caged_group_reference_stock
  add column if not exists reference_competence date;
alter table public.caged_group_detail_reference_stock
  add column if not exists reference_competence date;

update public.caged_group_reference_stock
set reference_competence = date '2025-12-01'
where reference_competence is null;
update public.caged_group_detail_reference_stock
set reference_competence = date '2025-12-01'
where reference_competence is null;

alter table public.caged_group_reference_stock
  alter column reference_competence set not null,
  alter column reference_competence set default date '2025-12-01';
alter table public.caged_group_detail_reference_stock
  alter column reference_competence set not null,
  alter column reference_competence set default date '2025-12-01';

create or replace function public.caged_group_recalculate_stock()
returns void language plpgsql as $$
begin
  update public.caged_group_monthly target
  set stock = ref.reference_stock + coalesce((
    select sum(case
      when movement.competence > ref.reference_competence
       and movement.competence <= target.competence then movement.balance
      when movement.competence > target.competence
       and movement.competence <= ref.reference_competence then -movement.balance
      else 0 end)::integer
    from public.caged_group_monthly movement
    where movement.ibge_code = target.ibge_code
      and movement.group_name = target.group_name
  ), 0)
  from public.caged_group_reference_stock ref
  where ref.ibge_code = target.ibge_code
    and ref.group_name = target.group_name;

  update public.caged_group_detail_monthly target
  set stock = ref.reference_stock + coalesce((
    select sum(case
      when movement.competence > ref.reference_competence
       and movement.competence <= target.competence then movement.balance
      when movement.competence > target.competence
       and movement.competence <= ref.reference_competence then -movement.balance
      else 0 end)::integer
    from public.caged_group_detail_monthly movement
    where movement.ibge_code = target.ibge_code
      and movement.group_name = target.group_name
      and movement.activity_name = target.activity_name
  ), 0)
  from public.caged_group_detail_reference_stock ref
  where ref.ibge_code = target.ibge_code
    and ref.group_name = target.group_name
    and ref.activity_name = target.activity_name;
end;
$$;

select public.caged_group_recalculate_stock();
notify pgrst, 'reload schema';
