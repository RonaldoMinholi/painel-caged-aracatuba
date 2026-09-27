# Atualização do Painel Novo CAGED

O painel lê o Supabase. Depois de uma importação concluída no GitHub, basta atualizar a página do painel no Vercel; não existe publicação manual no Vercel.

## 1. Novo mês divulgado

**Onde: GitHub → RonaldoMinholi/painel-caged-birigui → Actions → Importar CAGED — Região Administrativa de Araçatuba → Run workflow**

1. Não marque as opções de lote.
2. Em `competencia`, informe o mês no formato AAAAMM, por exemplo `202608`.
3. Clique em **Run workflow**.
4. Espere a execução ficar verde.
5. No Vercel, apenas atualize a página do painel.

Essa é a opção rápida. Ela importa só o mês novo e recalcula o estoque setorial.

## 2. Revisão recente do CAGED

Use quando a publicação informa correção de dados dos meses recentes.

**Onde: GitHub → Actions → Importar CAGED — Região Administrativa de Araçatuba → Run workflow**

1. Marque somente **Reimportar os últimos 18 meses**.
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
