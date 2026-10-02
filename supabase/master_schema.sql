-- TABELAS E FUNÇÕES COMPLETAS DO PAINEL NOVO CAGED (RA ARAÇATUBA)

CREATE TABLE IF NOT EXISTS public.municipalities (
  ibge_code text PRIMARY KEY,
  name text NOT NULL,
  territory text NOT NULL DEFAULT 'Região Administrativa de Araçatuba',
  is_regional boolean NOT NULL DEFAULT true
);

ALTER TABLE public.municipalities ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "public reads municipalities" ON public.municipalities;
CREATE POLICY "public reads municipalities" ON public.municipalities FOR SELECT USING (true);

CREATE OR REPLACE FUNCTION public.caged_municipalities()
RETURNS TABLE (ibge_code text, name text, territory text, is_regional boolean)
LANGUAGE sql STABLE AS $$
  SELECT m.ibge_code, m.name, m.territory, m.is_regional
  FROM public.municipalities m
  WHERE m.is_regional
  ORDER BY m.name;
$$;

CREATE TABLE IF NOT EXISTS public.caged_official_monthly (
  competence date NOT NULL,
  ibge_code text NOT NULL REFERENCES public.municipalities(ibge_code),
  stock integer NOT NULL DEFAULT 0,
  admissions integer NOT NULL DEFAULT 0,
  dismissals integer NOT NULL DEFAULT 0,
  balance integer NOT NULL DEFAULT 0,
  PRIMARY KEY (competence, ibge_code)
);

CREATE TABLE IF NOT EXISTS public.caged_official_imports (
  source_url text PRIMARY KEY,
  source_sha256 text NOT NULL,
  competence_start date NOT NULL,
  competence_end date NOT NULL,
  rows_imported integer NOT NULL,
  imported_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.caged_official_monthly ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.caged_official_imports ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "public reads official monthly" ON public.caged_official_monthly;
CREATE POLICY "public reads official monthly" ON public.caged_official_monthly FOR SELECT USING (true);

DROP POLICY IF EXISTS "public reads official imports" ON public.caged_official_imports;
CREATE POLICY "public reads official imports" ON public.caged_official_imports FOR SELECT USING (true);

CREATE OR REPLACE FUNCTION public.caged_official_series(
  p_ibge_codes text[] DEFAULT NULL
)
RETURNS TABLE (
  competence date,
  stock bigint,
  admissions bigint,
  dismissals bigint,
  balance bigint
)
LANGUAGE sql STABLE AS $$
  SELECT
    c.competence,
    sum(c.stock)::bigint,
    sum(c.admissions)::bigint,
    sum(c.dismissals)::bigint,
    sum(c.balance)::bigint
  FROM public.caged_official_monthly c
  WHERE p_ibge_codes IS NULL OR c.ibge_code = ANY(p_ibge_codes)
  GROUP BY c.competence
  ORDER BY c.competence;
$$;

CREATE OR REPLACE FUNCTION public.caged_state_balance(
  p_competences date[] DEFAULT NULL,
  p_ibge_codes text[] DEFAULT NULL,
  p_uf_codes text[] DEFAULT NULL
)
RETURNS TABLE (uf_code text, balance bigint)
LANGUAGE sql STABLE AS $$
  SELECT
    '35'::text AS uf_code,
    sum(c.balance)::bigint AS balance
  FROM public.caged_official_monthly c
  WHERE
    (p_competences IS NULL OR c.competence = ANY(p_competences))
    AND (p_ibge_codes IS NULL OR c.ibge_code = ANY(p_ibge_codes))
    AND (p_uf_codes IS NULL OR '35' = ANY(p_uf_codes));
$$;

NOTIFY pgrst, 'reload schema';
