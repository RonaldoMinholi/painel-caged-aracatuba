# Painel Novo CAGED — Região Administrativa de Araçatuba

Painel web independente, baseado no Painel de Informações do Novo CAGED. O recorte contém os 43 municípios da Região Administrativa de Araçatuba.

## Onde cada parte fica

- **GitHub**: código e execução das importações em Actions.
- **Supabase**: banco de dados do painel.
- **Vercel**: publicação automática do site após cada alteração no GitHub.

## Atualização quando o Novo CAGED divulgar nova competência

No **GitHub**:

1. Abra o repositório e clique em **Actions**.
2. Abra **Importar CAGED — Região Administrativa de Araçatuba**.
3. Clique em **Run workflow**.
4. Em `competencia`, informe o mês novo no formato `AAAAMM` — por exemplo, `202608`.
5. Deixe os outros campos desmarcados e clique em **Run workflow**.
6. Aguarde o resultado verde. Ao final, a própria importação executa a validação contra o Power BI oficial.

O painel no **Vercel** lê o banco diretamente. Portanto, após a execução verde, os dados aparecem no site sem publicar ou alterar nada no Vercel.

## Quando houver revisão de meses anteriores

O Novo CAGED pode revisar competências já divulgadas. No **GitHub**, rode o mesmo workflow e marque:

- `reimportar_ultimos_18_meses` para atualizar o período recente; ele pode demorar bastante.
- `importar_tabela_oficial` quando houver uma nova Tabela 8.1 revisada disponível na pasta oficial. Essa tabela atualiza os cartões e o estoque municipal.

Não marque `importar_todos_os_microdados` no uso normal. Ele serve apenas para uma carga histórica completa e pode levar horas.

## Validação independente

No **GitHub**, a ação **Validar CAGED contra Power BI oficial** confere uma competência já importada. Informe `AAAAMM` e aguarde o resultado verde.

A validação compara:
- cartões municipais de admissões, desligamentos e saldo;
- Página 2, por grande grupamento e agrupamento;
- Página 4, incluindo cubo de características e tabela CBO;
- listas e rótulos dos filtros CNAE.

O estoque municipal vem da Tabela 8.1 oficial revisada. A medida pública de estoque da API do Power BI não pode ser usada como comparação porque ela retorna o total nacional mesmo ao filtrar um município.

## Configuração necessária no GitHub

Em **Settings → Secrets and variables → Actions**, o repositório precisa ter:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `GOOGLE_SERVICE_ACCOUNT_JSON`

## Banco

No **Supabase**, o schema e as migrações da pasta `supabase/` criam as tabelas usadas pelo painel.
