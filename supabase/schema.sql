create table if not exists public.municipalities (
  ibge_code text primary key,
  name text not null,
  territory text not null default 'Região de Governo de Birigui',
  is_regional boolean not null default true
);

insert into public.municipalities (ibge_code, name) values
  ('3506402', 'Bilac'), ('3506501', 'Birigui'), ('3507707', 'Braúna'),
  ('3508101', 'Buritama'), ('3512509', 'Clementina'), ('3515601', 'Coroados'),
  ('3516500', 'Gabriel Monteiro'), ('3517102', 'Glicério'), ('3527259', 'Lourdes'),
  ('3527705', 'Luiziânia'), ('3537407', 'Piacatu'), ('3548404', 'Santópolis do Aguapeí'),
  ('3555201', 'Turiúba')
on conflict (ibge_code) do update set name = excluded.name;

create table if not exists public.caged_monthly (
  competence date not null,
  ibge_code text not null references public.municipalities(ibge_code),
  cnae_section text not null default 'Não informado',
  sex text not null default 'Não informado',
  age_band text not null default 'Não informado',
  education text not null default 'Não informado',
  admissions integer not null default 0,
  dismissals integer not null default 0,
  balance integer not null default 0,
  primary key (competence, ibge_code, cnae_section, sex, age_band, education)
);

create table if not exists public.caged_imports (
  competence date primary key,
  source_url text not null,
  source_sha256 text not null,
  imported_at timestamptz not null default now(),
  rows_processed integer not null,
  status text not null default 'completed'
);

alter table public.municipalities enable row level security;
alter table public.caged_monthly enable row level security;
alter table public.caged_imports enable row level security;

create policy "public reads municipalities" on public.municipalities for select using (true);
create policy "public reads aggregated caged" on public.caged_monthly for select using (true);
create policy "public reads imports" on public.caged_imports for select using (true);
