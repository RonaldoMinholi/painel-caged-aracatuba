# Painel Novo CAGED — Região Administrativa de Araçatuba

Painel web independente, baseado no Painel de Informações do Novo CAGED. O recorte contém os 43 municípios da Região Administrativa de Araçatuba.

## Onde cada parte fica

- **GitHub**: código e execução das importações em Actions.
- **Supabase**: banco de dados do painel.
- **Vercel**: publicação automática do site após cada alteração no GitHub.

## Atualização quando o Novo CAGED divulgar nova competência

Antes, no **Google Drive**, coloque os arquivos novos nestas pastas:

| O que enviar | Pasta do Google Drive | Nome aceito |
| --- | --- | --- |
| Microdados mensais | [Pasta de microdados CAGEDMOV](https://drive.google.com/drive/folders/12plsRjwzGWeR2Vscutdz5I0K94vjWfmA) | `CAGEDMOVAAAAMM.zip`, `.7z` ou `.txt`. Ex.: `CAGEDMOV202608.zip`. |
| Série oficial para cartões e estoque municipal | [Pasta das Tabelas 8.1](https://drive.google.com/drive/folders/1SLFCZ184KseNP8W9Xc6YMe6rCrHeuaiU?usp=drive_link) | Uma planilha `.xlsx` que tenha a aba **Tabela 8.1**. Ex.: `3-tabelas_Agosto de 2026.xlsx`. |

O arquivo `CAGEDFORAAAAMM` não é necessário para a atualização normal. Se estiver disponível, pode ficar na pasta de microdados, mas o painel atual usa o `CAGEDMOV`.

O GitHub importa dessas pastas; ele não busca automaticamente os arquivos no site do MTE.

No **GitHub**:

1. Abra o repositório e clique em **Actions**.
2. Abra **Importar CAGED — Região Administrativa de Araçatuba**.
3. Clique em **Run workflow**.
4. Marque `importar_tabela_oficial`.
5. Em `competencia`, informe o mês novo no formato `AAAAMM` — por exemplo, `202608`.
6. Deixe os outros campos desmarcados e clique em **Run workflow**.
7. Aguarde o resultado verde. Ao final, a própria importação executa a validação contra o Power BI oficial.

O painel no **Vercel** lê o banco diretamente. Portanto, após a execução verde, os dados aparecem no site sem publicar ou alterar nada no Vercel.

## Quando houver revisão de meses anteriores

O Novo CAGED pode revisar competências já divulgadas. No **GitHub**, rode o mesmo workflow e marque:

- `reimportar_ultimos_18_meses` e `importar_tabela_oficial` juntos para atualizar o período recente; ele pode demorar bastante. A Tabela 8.1 atualiza os cartões, o estoque municipal e a tela geográfica.

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
