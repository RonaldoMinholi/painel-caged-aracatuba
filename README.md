# Painel Novo CAGED — Região Administrativa de Araçatuba

Painel próprio da Região Administrativa de Araçatuba, com dados do Novo CAGED armazenados no Supabase e conferidos contra o Power BI oficial.

## Onde fazer cada coisa

| Lugar | Para que serve |
|---|---|
| **Google Drive** | Guardar os arquivos oficiais mensais que serão importados. |
| **GitHub** | Rodar a atualização, o recálculo e a conferência automática. |
| **Supabase** | Banco de dados. Não é preciso rodar SQL na atualização normal. |
| **Vercel** | Site publicado. Atualiza sozinho depois que a Action do GitHub terminar verde. |

## Atualização mensal — sequência normal

Faça esta sequência quando o Novo CAGED publicar uma nova competência.

### 1. Google Drive — enviar os arquivos oficiais

1. Baixe do Ministério do Trabalho o arquivo mensal `CAGEDMOVAAAAMM` (por exemplo, `CAGEDMOV202608.zip`).
2. Envie-o para a [pasta de microdados](https://drive.google.com/drive/folders/12plsRjwzGWeR2Vscutdz5I0K94vjWfmA).
3. Baixe também a planilha oficial atualizada que contém a aba **Tabela 8.1**.
4. Envie essa planilha `.xlsx` para a [pasta de tabelas oficiais](https://drive.google.com/drive/folders/1SLFCZ184KseNP8W9Xc6YMe6rCrHeuaiU?usp=drive_link).

> O arquivo `CAGEDFOR` não é necessário para a atualização normal do painel.

### 2. GitHub — rodar a atualização

1. Abra o repositório e entre em **Actions**.
2. Abra **Atualizar ou importar CAGED**.
3. Clique em **Run workflow**.
4. Em **modo**, deixe **recentes**.
5. Deixe os dois campos de mês vazios.
6. Clique em **Run workflow**.

A Action atualiza a Tabela 8.1, reimporta os últimos 18 meses disponíveis, recalcula o estoque e valida os meses importados contra o Power BI oficial.

### 3. Resultado

- **Verde:** atualização concluída; abra ou atualize o painel na Vercel. Não há mais nada a fazer.
- **Vermelho:** não rode outra importação por cima. Abra a execução com erro e envie uma captura da etapa vermelha para análise.

## Importar um período específico — uso excepcional

Use apenas para preencher meses históricos que ainda não existem no banco.

**GitHub → Actions → Atualizar ou importar CAGED → Run workflow**

- Em **modo**, escolha **periodo**.
- Preencha **competencia_inicial** e **competencia_final** no formato `AAAAMM`.
- Exemplo: `202001` até `202012`.

Antes de rodar, confirme que os arquivos `CAGEDMOV` de todos os meses do período estão na pasta de microdados do Google Drive.

## Conferir somente um mês — sem alterar dados

Para conferir um mês sem importar nada:

**GitHub → Actions → Validar CAGED contra Power BI oficial → Run workflow**

Preencha a competência, por exemplo `202608`. Essa Action só confere; ela não muda o banco.

## Estoque setorial oficial — uma vez por ano

Quando o Ministério publicar um novo arquivo anual de **Estoque de Referência**:

**GitHub → Actions → Atualizar estoque setorial oficial → Run workflow**

Informe o ano do arquivo, por exemplo `2027`, e rode. Essa Action baixa o arquivo oficial por conta própria, importa apenas a Região Administrativa de Araçatuba e recalcula o estoque.

Não é necessário rodar essa Action a cada divulgação mensal do CAGED.

## Correção CBO e tempo de emprego — concluída

A correção histórica da tabela CBO e da coluna **Tempo de Emprego (Desligados)** foi concluída e validada contra o Power BI oficial em outubro de 2026. Não há uma etapa extra para rodar na rotina mensal.


## O que não precisa ser feito na rotina

- **Supabase:** não executar SQL manualmente.
- **Vercel:** não fazer novo deploy manual.
- **GitHub:** não há etapa extra de correção CBO/tempo; a validação ocorre dentro da atualização mensal.
- **Reimportar anos antigos:** não é necessário na atualização mensal, pois o modo **recentes** já cobre revisões dos últimos 18 meses.

## Arquivos e configurações técnicas

- Fluxo mensal/principal: `.github/workflows/caged-import.yml`
- Conferência de um mês: `.github/workflows/caged-validate.yml`
- Estoque setorial anual: `.github/workflows/sector-stock-refresh.yml`
- Importador: `importer/import_caged.py`
- Conferência: `importer/validate_caged.py`
- Recálculo de estoque: `importer/refresh_group_stock.py`

Os secrets do GitHub (`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` e `GOOGLE_SERVICE_ACCOUNT_JSON`) já devem permanecer configurados. Não há motivo para alterá-los durante a atualização normal.
