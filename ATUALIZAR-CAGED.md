# Atualização do Painel Novo CAGED

O painel lê o Supabase. Depois de uma importação concluída no GitHub, basta atualizar a página do painel no Vercel; não existe publicação manual no Vercel.

## 1. Novo mês divulgado

Antes, no **Google Drive**, coloque os arquivos novos nestas pastas:

| O que enviar | Pasta do Google Drive | Nome aceito |
| --- | --- | --- |
| Microdados mensais | [Pasta de microdados CAGEDMOV](https://drive.google.com/drive/folders/12plsRjwzGWeR2Vscutdz5I0K94vjWfmA) | `CAGEDMOVAAAAMM.zip`, `.7z` ou `.txt`. Ex.: `CAGEDMOV202608.zip`. |
| Série oficial para cartões e estoque municipal | [Pasta das Tabelas 8.1](https://drive.google.com/drive/folders/1SLFCZ184KseNP8W9Xc6YMe6rCrHeuaiU?usp=drive_link) | Uma planilha `.xlsx` que tenha a aba **Tabela 8.1**. Ex.: `3-tabelas_Agosto de 2026.xlsx`. |

O arquivo `CAGEDFORAAAAMM` não é necessário para a atualização normal. Se estiver disponível, pode ficar na pasta de microdados, mas o painel atual usa o `CAGEDMOV`.

O GitHub importa dessas pastas; ele não busca automaticamente os arquivos no site do MTE.

**Onde: GitHub → RonaldoMinholi/painel-caged-birigui → Actions → Importar CAGED — Região Administrativa de Araçatuba → Run workflow**

1. Marque **Atualizar a Tabela 8.1 oficial revisada**.
2. Não marque as opções de lote.
3. Em `competencia`, informe o mês no formato AAAAMM, por exemplo `202608`.
4. Clique em **Run workflow**.
5. Espere a execução ficar verde.
6. No Vercel, apenas atualize a página do painel.

Essa é a atualização completa: a Tabela 8.1 mantém cartões, estoque e tela geográfica; os microdados atualizam as telas Setorial e Características do Trabalhador. O workflow escolhe automaticamente a Tabela 8.1 mais recente existente na pasta oficial.

## 2. Revisão recente do CAGED

Use quando a publicação informa correção de dados dos meses recentes.

**Onde: GitHub → Actions → Importar CAGED — Região Administrativa de Araçatuba → Run workflow**

1. Marque **Atualizar a Tabela 8.1 oficial revisada** e **Reimportar os últimos 18 meses**.
2. Deixe `competencia`, `competencia_inicial` e `competencia_final` vazios.
3. Clique em **Run workflow**.

Essa rotina baixa os arquivos disponíveis no Google Drive dos últimos 18 meses e substitui os agregados no Supabase. Pode levar bastante tempo; não inicie outra execução enquanto ela estiver rodando.

## 3. Revisão de meses específicos ou antigos

Se o CAGED mencionar competências específicas, reimporte somente elas. É mais seguro e rápido que refazer todo o histórico.

1. Marque **Importar todos os meses disponíveis**.
2. Preencha `competencia_inicial` e `competencia_final`, por exemplo `202401` e `202406`.
3. Execute.
4. Para períodos longos, divida em blocos de no máximo 12 meses.

## Regras importantes

- **GitHub** executa a importação.
- **Supabase** recebe os dados; não é necessário rodar SQL para uma atualização normal.
- **Vercel** não precisa de novo deploy; apenas recarregue a página depois do GitHub ficar verde.
- Não use duas importações ao mesmo tempo.
- O período 2020–2026 completo deve ser reimportado em blocos; uma execução única pode ultrapassar o limite de seis horas do GitHub Actions.
