#!/usr/bin/env python3
"""Valida a página Características do Trabalhador contra o Power BI oficial."""

import argparse
import os
import sys
from collections import defaultdict

import requests

from import_caged import (
    RA_MUNICIPALITIES, activity_name, load_cnae_labels, powerbi_worker_totals,
)

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

def compare_rows(title, expected, actual, tolerance=0.0):
    missing = [key for key in expected if key not in actual]
    extra = [key for key in actual if key not in expected]
    different = []
    for key in expected.keys() & actual.keys():
        expected_value, actual_value = expected[key], actual[key]
        if len(expected_value) != len(actual_value) or any(
            abs(float(left) - float(right)) > tolerance
            for left, right in zip(expected_value, actual_value)
        ):
            different.append((key, expected_value, actual_value))
    show_examples(f"{title} — faltantes", missing)
    show_examples(f"{title} — extras", extra)
    show_examples(f"{title} — valores diferentes", different)
    return not (missing or extra or different)

def worker_city_totals(worker):
    grouped = defaultdict(lambda: [0, 0, 0])
    for key, values in worker.items():
        group = grouped[key[0]]
        group[0] += int(values[0]); group[1] += int(values[1]); group[2] += int(values[0]) - int(values[1])
    return dict(grouped)

def validate_pages_one_and_three(competence, worker):
    rows = fetch_all(
        "caged_official_monthly", competence,
        ("ibge_code", "admissions", "dismissals", "balance"),
    )
    actual = {
        str(row["ibge_code"]): (int(row["admissions"]), int(row["dismissals"]), int(row["balance"]))
        for row in rows
    }
    return compare_rows("Páginas 1 e 3 — município", worker_city_totals(worker), actual)

def aggregate_sectorial(worker):
    groups = defaultdict(lambda: [0, 0, 0])
    details = defaultdict(lambda: [0, 0, 0])
    for key, values in worker.items():
        code, group, section = key[:3]
        admissions, dismissals = int(values[0]), int(values[1])
        for bucket, group_key in (
            (groups, (code, group)),
            (details, (code, group, activity_name(group, section))),
        ):
            row = bucket[group_key]
            row[0] += admissions; row[1] += dismissals; row[2] += admissions - dismissals
    return dict(groups), dict(details)

def validate_page_two(competence, worker):
    expected_groups, expected_details = aggregate_sectorial(worker)
    rows = fetch_all(
        "caged_group_monthly", competence,
        ("ibge_code", "group_name", "admissions", "dismissals", "balance"),
    )
    actual_groups = {
        (str(row["ibge_code"]), row["group_name"]):
        (int(row["admissions"]), int(row["dismissals"]), int(row["balance"]))
        for row in rows
    }
    group_ok = compare_rows("Página 2 — grande grupamento", expected_groups, actual_groups)
    rows = fetch_all(
        "caged_group_detail_monthly", competence,
        ("ibge_code", "group_name", "activity_name", "admissions", "dismissals", "balance"),
    )
    actual_details = {
        (str(row["ibge_code"]), row["group_name"], row["activity_name"]):
        (int(row["admissions"]), int(row["dismissals"]), int(row["balance"]))
        for row in rows
    }
    detail_ok = compare_rows("Página 2 — grupamento", expected_details, actual_details)
    return group_ok and detail_ok

def validate_cnae_reference():
    _, reference_rows = load_cnae_labels()
    expected = {(row["level"], row["code"]): row["label"] for row in reference_rows}
    url = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    response = requests.get(
        f"{url}/rest/v1/cnae_reference", headers={"apikey": key, "Authorization": f"Bearer {key}"},
        params={"select": "level,code,label"}, timeout=180,
    )
    response.raise_for_status()
    actual = {(row["level"], row["code"]): row["label"] for row in response.json()}
    missing = [key for key in expected if key not in actual]
    extra = [key for key in actual if key not in expected]
    different = [(key, expected[key], actual[key]) for key in expected.keys() & actual.keys() if expected[key] != actual[key]]
    show_examples("Filtros CNAE — itens faltantes", missing)
    show_examples("Filtros CNAE — itens extras", extra)
    show_examples("Filtros CNAE — rótulos diferentes", different)
    return not (missing or extra or different)

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
    page_one_three_ok = validate_pages_one_and_three(args.competencia, official_worker)
    page_two_ok = validate_page_two(args.competencia, official_worker)
    worker_ok = validate_worker_cube(args.competencia, official_worker)
    occupation_ok = validate_occupation_table(args.competencia, official_occupation)
    cnae_ok = validate_cnae_reference()
    if page_one_three_ok and page_two_ok and worker_ok and occupation_ok and cnae_ok:
        print("\n## RESULTADO: APROVADO")
        print("Páginas 1 a 4 e os filtros CNAE coincidem com as fontes oficiais consultadas.")
        return
    print("\n## RESULTADO: REPROVADO")
    print("O relatório acima indica as chaves e valores que precisam ser corrigidos.")
    sys.exit(1)

if __name__ == "__main__":
    main()
