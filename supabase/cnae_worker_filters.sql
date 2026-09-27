-- Página 4: filtros CNAE 2.0 reais (Seção, Divisão, Grupo, Classe e Subclasse).
-- Execute UMA VEZ no SQL Editor do SUPABASE antes de reimportar as competências.

alter table public.caged_worker_monthly
  add column if not exists cnae_large_group text not null default 'Não identificado',
  add column if not exists cnae_division text not null default 'Não informado',
  add column if not exists cnae_group text not null default 'Não informado',
  add column if not exists cnae_class text not null default 'Não informado',
  add column if not exists cnae_subclass text not null default 'Não informado';

alter table public.caged_worker_monthly
  drop constraint if exists caged_worker_monthly_pkey;

alter table public.caged_worker_monthly
  add primary key (
    competence, ibge_code, cnae_large_group, cnae_section, cnae_division, cnae_group,
    cnae_class, cnae_subclass, sex, age_band, education,
    is_apprentice, is_intermittent, is_temporary, is_foreigner
  );

alter table public.caged_occupation_worker_monthly
  add column if not exists cnae_large_group text not null default 'Não identificado',
  add column if not exists cnae_section text not null default 'Não informado',
  add column if not exists cnae_division text not null default 'Não informado',
  add column if not exists cnae_group text not null default 'Não informado',
  add column if not exists cnae_class text not null default 'Não informado',
  add column if not exists cnae_subclass text not null default 'Não informado';

alter table public.caged_occupation_worker_monthly
  drop constraint if exists caged_occupation_worker_monthly_pkey;

alter table public.caged_occupation_worker_monthly
  add primary key (
    competence, ibge_code, occupation_group,
    cnae_large_group, cnae_section, cnae_division, cnae_group, cnae_class, cnae_subclass,
    is_apprentice, is_intermittent, is_temporary, is_foreigner
  );

create index if not exists caged_worker_monthly_cnae_idx
  on public.caged_worker_monthly (competence, ibge_code, cnae_large_group, cnae_section, cnae_division, cnae_group, cnae_class, cnae_subclass);

create index if not exists caged_occupation_worker_monthly_cnae_idx
  on public.caged_occupation_worker_monthly (competence, ibge_code, cnae_section, cnae_division, cnae_group, cnae_class, cnae_subclass);

notify pgrst, 'reload schema';
