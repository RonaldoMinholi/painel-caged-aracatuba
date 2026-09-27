-- Página 4: filtros Aprendiz, Intermitente, Temporário e Estrangeiro.
-- Execute UMA VEZ no SQL Editor do Supabase antes da próxima reimportação CAGEDMOV.

create table if not exists public.caged_worker_monthly (
  competence date not null,
  ibge_code text not null references public.municipalities(ibge_code),
  cnae_section text not null default 'Não informado',
  sex text not null default 'Não informado',
  age_band text not null default 'Não informado',
  education text not null default 'Não informado',
  is_apprentice boolean not null default false,
  is_intermittent boolean not null default false,
  is_temporary boolean not null default false,
  is_foreigner boolean not null default false,
  admissions integer not null default 0,
  dismissals integer not null default 0,
  balance integer not null default 0,
  primary key (
    competence, ibge_code, cnae_section, sex, age_band, education,
    is_apprentice, is_intermittent, is_temporary, is_foreigner
  )
);

alter table public.caged_worker_monthly enable row level security;
drop policy if exists "public reads caged worker monthly" on public.caged_worker_monthly;
create policy "public reads caged worker monthly"
  on public.caged_worker_monthly for select using (true);

notify pgrst, 'reload schema';
