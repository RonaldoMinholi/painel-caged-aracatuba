# Painel do Mercado de Trabalho — Região de Governo de Birigui

Projeto independente do painel de obras. Mostra indicadores do Novo CAGED para a Região de Governo de Birigui, seus 13 municípios e comparações com São Paulo.

## Como atualiza

O workflow `caged-import.yml` roda todos os dias. Ele procura novas competências no repositório oficial do MTE, baixa o arquivo temporariamente, consolida somente os municípios de interesse e grava os resultados no Supabase. O arquivo bruto não é enviado ao GitHub nem armazenado pelo site.

Para o workflow funcionar, configurar estes *secrets* no novo repositório:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `CAGED_SOURCE_BASE_URL` (opcional; só se o MTE alterar o endereço padrão)

O processo pode ser disparado manualmente em **Actions → Importar Novo CAGED → Run workflow**. O dashboard consulta o Supabase; por isso novos dados aparecem sem precisar publicar novamente no Vercel.

## Banco

Execute `supabase/schema.sql` uma única vez no SQL Editor do novo projeto Supabase. Ele cria as tabelas agregadas e a lista oficial de municípios do recorte.

## Desenvolvimento local

```bash
cp .env.example .env
npm install
npm run dev
```

Para importar uma competência manualmente:

```bash
python3 importer/import_caged.py --competencia 202607
```

O importador aceita `.zip`, `.7z` e arquivo texto do MTE. Ele salva apenas agregados; não persiste vínculos individuais.
