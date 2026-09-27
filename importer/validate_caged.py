#!/usr/bin/env python3
"""Valida a página Características do Trabalhador contra o Power BI oficial."""

import argparse
import os
import sys
from collections import defaultdict

import requests

from import_caged import RA_MUNICIPALITIES, powerbi_worker_totals

FIELDS = (
    "ibge_code", "cnae_large_group", "cnae_section", "cnae_division",
    "cnae_group", "cnae_class", "cnae_subclass", "sex", "age_band",
    "education", "is_apprentice", "is_intermittent", "is_temporary",
    "is_foreigner",
)

def fetch_all(table, competence, columns):
    url = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Range-Unit": "items"}
    rows = []
    start, page_size = 0, 1000
    while True:
        response = requests.get(
            f"{url}/rest/v1/{table}",
            headers={**headers, "Range": f"{start}-{start + page_size - 1}"},
            params={"select": ",".join(columns), "competence": f"eq.{competence[:4]}-{competence[4:]}-01"},
            timeout=180,
        )
        response.raise_for_status()
        page = response.json()
        rows.extend(page)
        if len(page) < page_size:
            return rows
        start += page_size

def as_worker_key(row):
    return tuple(
        bool(row[field]) if field.startswith("is_") else str(row[field])
        for field in FIELDS
    )

def show_examples(title, values, limit=8):
    print(f"\n## {title}: {len(values)}")
    for item in values[:limit]:
        print(f"- {item}")

def validate_worker_cube(competence, expected):
    rows = fetch_all(
        "caged_worker_monthly", competence,
        (*FIELDS, "admissions", "dismissals", "balance"),
    )
    actual = {}
    duplicates = []
    for row in rows:
        key = as_worker_key(row)
        value = (int(row["admissions"]), int(row["dismissals"]), int(row["balance"]))
        if key in actual:
            duplicates.append(key)
        actual[key] = value

    expected_values = {
        key: (int(value[0]), int(value[1]), int(value[0] - value[1]))
        for key, value in expected.items()
    }
    missing = [key for key in expected_values if key not in actual]
    extra = [key for key in actual if key not in expected_values]
    different = [
        (key, expected_values[key], actual[key])
        for key in expected_values.keys() & actual.keys()
        if expected_values[key] != actual[key]
    ]
    show_examples("Cubo trabalhador — faltantes", missing)
    show_examples("Cubo trabalhador — extras", extra)
    show_examples("Cubo trabalhador — valores diferentes", different)
    show_examples("Cubo trabalhador — chaves duplicadas", duplicates)
    return not (missing or extra or different or duplicates)

def aggregate_occupation(rows):
    grouped = defaultdict(lambda: [0, 0, 0, 0.0])
    for key, admissions, dismissals, tenure_sum in rows:
        group = grouped[key]
        group[0] += int(admissions)
        group[1] += int(dismissals)
        group[2] += int(admissions) - int(dismissals)
        group[3] += float(tenure_sum)
    return {
        key: (value[0], value[1], value[2], value[3] / value[1] if value[1] else None)
        for key, value in grouped.items()
    }

def validate_occupation_table(competence, expected):
    source_rows = [
        ((key[0], key[1]), values[0], values[1], values[2])
        for key, values in expected.items()
    ]
    expected_values = aggregate_occupation(source_rows)
    rows = fetch_all(
        "caged_occupation_worker_monthly", competence,
        ("ibge_code", "occupation_group", "admissions", "dismissals", "balance", "average_dismissal_tenure"),
    )
    actual_rows = [
        ((str(row["ibge_code"]), row["occupation_group"]), row["admissions"], row["dismissals"],
         (float(row["average_dismissal_tenure"] or 0) * int(row["dismissals"] or 0)))
        for row in rows
    ]
    actual_values = aggregate_occupation(actual_rows)
    missing = [key for key in expected_values if key not in actual_values]
    extra = [key for key in actual_values if key not in expected_values]
    different = []
    for key in expected_values.keys() & actual_values.keys():
        expected_row, actual_row = expected_values[key], actual_values[key]
        if expected_row[:3] != actual_row[:3] or (
            expected_row[3] is not None and abs(expected_row[3] - actual_row[3]) > 0.05
        ):
            different.append((key, expected_row, actual_row))
    show_examples("Tabela CBO — faltantes", missing)
    show_examples("Tabela CBO — extras", extra)
    show_examples("Tabela CBO — valores diferentes", different)
    return not (missing or extra or different)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--competencia", required=True, help="AAAAMM")
    args = parser.parse_args()
    if not os.environ.get("SUPABASE_URL") or not os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
        raise RuntimeError("SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY são obrigatórios.")

    print(f"# Validação oficial Novo CAGED — {args.competencia}")
    print(f"Municípios conferidos: {len(RA_MUNICIPALITIES)}")
    official_worker, official_occupation = powerbi_worker_totals(args.competencia)
    worker_ok = validate_worker_cube(args.competencia, official_worker)
    occupation_ok = validate_occupation_table(args.competencia, official_occupation)
    if worker_ok and occupation_ok:
        print("\n## RESULTADO: APROVADO")
        print("Os dados atômicos da página 4 coincidem com o Power BI oficial.")
        return
    print("\n## RESULTADO: REPROVADO")
    print("O relatório acima indica as chaves e valores que precisam ser corrigidos.")
    sys.exit(1)

if __name__ == "__main__":
    main()
