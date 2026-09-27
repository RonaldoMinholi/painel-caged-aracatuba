-- Página 4: tabela ocupacional filtrada por Aprendiz, Intermitente, Temporário e Estrangeiro.
-- Execute UMA VEZ no SQL Editor do SUPABASE antes da próxima reimportação.

create table if not exists public.caged_occupation_worker_monthly (
  competence date not null,
  ibge_code text not null references public.municipalities(ibge_code),
  occupation_group text not null,
  is_apprentice boolean not null default false,
  is_intermittent boolean not null default false,
  is_temporary boolean not null default false,
  is_foreigner boolean not null default false,
  admissions integer not null default 0,
  dismissals integer not null default 0,
  balance integer not null default 0,
  primary key (
    competence, ibge_code, occupation_group,
    is_apprentice, is_intermittent, is_temporary, is_foreigner
  )
);

alter table public.caged_occupation_worker_monthly enable row level security;
drop policy if exists "public reads filtered occupations" on public.caged_occupation_worker_monthly;
create policy "public reads filtered occupations"
  on public.caged_occupation_worker_monthly for select using (true);

notify pgrst, 'reload schema';
