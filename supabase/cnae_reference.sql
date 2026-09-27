-- Referência canônica CNAE 2.0 usada pelos cinco filtros da página 4.
-- Os rótulos são enviados pelo importador a partir da estrutura oficial do IBGE.

create table if not exists public.cnae_reference (
  level text not null check (level in ('section', 'division', 'group', 'class', 'subclass')),
  code text not null,
  label text not null,
  primary key (level, code)
);

alter table public.cnae_reference enable row level security;

drop policy if exists "Leitura pública da referência CNAE" on public.cnae_reference;
create policy "Leitura pública da referência CNAE"
  on public.cnae_reference for select
  using (true);

grant select on public.cnae_reference to anon, authenticated;
