-- Correção definitiva do Tempo de Emprego (Desligados) da página 4.
-- Execute UMA VEZ no SQL Editor do SUPABASE antes de rodar a reconstrução CBO.
-- O bucket bruto de tempo precisa fazer parte da chave para que médias
-- não-aditivas do Power BI permaneçam exatas em períodos com vários meses.

alter table public.caged_occupation_worker_monthly
  add column if not exists tenure_bucket text not null default '';

alter table public.caged_occupation_worker_monthly
  drop constraint if exists caged_occupation_worker_monthly_pkey;

alter table public.caged_occupation_worker_monthly
  add primary key (
    competence, ibge_code, occupation_group,
    cnae_large_group, cnae_section, cnae_division, cnae_group, cnae_class, cnae_subclass,
    is_apprentice, is_intermittent, is_temporary, is_foreigner, tenure_bucket
  );

create index if not exists caged_occupation_worker_tenure_idx
  on public.caged_occupation_worker_monthly (
    competence, ibge_code, cnae_large_group, cnae_section, cnae_division,
    cnae_group, cnae_class, cnae_subclass, occupation_group
  );

notify pgrst, 'reload schema';
