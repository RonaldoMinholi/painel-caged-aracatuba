#!/usr/bin/env python3
"""Valida Tempo de Emprego setorial contra o Power BI oficial."""

import argparse
import os
import sys
from collections import defaultdict

import requests

from repair_sector_tenure import months_between, official_sector_tenure, official_occupation_summaries


def fetch_all(table, competence, columns):
    url = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    rows, start = [], 0
    while True:
        response = requests.get(
            f"{url}/rest/v1/{table}",
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Range-Unit": "items",
                "Range": f"{start}-{start + 999}",
            },
            params={
                "select": ",".join(columns),
                "competence": f"eq.{competence[:4]}-{competence[4:]}-01",
            },
            timeout=180,
        )
        response.raise_for_status()
        page = response.json()
        rows.extend(page)
        if len(page) < 1000:
            return rows
        start += 1000


def compare(title, expected, actual):
    missing, different = [], []
    for key, values in expected.items():
        expected_average = values[0] / values[1] if values[1] else None
        received = actual.get(key)
        actual_average = (received[0] / received[1]) if received and received[1] else None
        if expected_average is not None and actual_average is None:
            missing.append(key)
        elif expected_average is not None and abs(expected_average - actual_average) > 0.05:
            different.append((key, round(expected_average, 2), round(actual_average, 2)))
    print(f"{title}: faltantes={len(missing)}; diferentes={len(different)}")
    for value in (missing[:5] + different[:5]):
        print(" -", value)
    return not (missing or different)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--competencia-inicial", default="202001")
    parser.add_argument("--competencia-final", required=True)
    args = parser.parse_args()
    ok = True
    for competence in months_between(args.competencia_inicial, args.competencia_final):
        print(f"# Conferindo tempo setorial {competence}")
        expected_groups, expected_details = official_sector_tenure(competence)
        group_rows = fetch_all(
            "caged_group_monthly", competence,
            ("ibge_code", "group_name", "dismissal_tenure_sum", "dismissal_tenure_count"),
        )
        detail_rows = fetch_all(
            "caged_group_detail_monthly", competence,
            ("ibge_code", "group_name", "activity_name", "dismissal_tenure_sum", "dismissal_tenure_count"),
        )
        actual_groups = {
            (str(row["ibge_code"]), row["group_name"]):
            (float(row["dismissal_tenure_sum"] or 0), int(row["dismissal_tenure_count"] or 0))
            for row in group_rows
        }
        actual_details = {
            (str(row["ibge_code"]), row["group_name"], row["activity_name"]):
            (float(row["dismissal_tenure_sum"] or 0), int(row["dismissal_tenure_count"] or 0))
            for row in detail_rows
        }
        ok = compare("Grande grupamento", expected_groups, actual_groups) and ok
        ok = compare("Detalhamento", expected_details, actual_details) and ok

        expected_occupations = {(str(row["ibge_code"]), row["occupation_group"]): (float(row["average_dismissal_tenure"]) * int(row["dismissals"]), int(row["dismissals"])) for row in official_occupation_summaries(competence) if row["dismissals"]}
        occupation_rows = fetch_all("caged_occupation_monthly", competence, ("ibge_code", "occupation_group", "dismissal_tenure_sum", "dismissal_tenure_count"))
        actual_occupations = {(str(row["ibge_code"]), row["occupation_group"]): (float(row["dismissal_tenure_sum"] or 0), int(row["dismissal_tenure_count"] or 0)) for row in occupation_rows}
        ok = compare("Grande grupo ocupacional (tela 4)", expected_occupations, actual_occupations) and ok
    if not ok:
        raise RuntimeError("Tempo de emprego setorial ou ocupacional não coincide com o Power BI oficial.")
    print("RESULTADO: APROVADO")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERRO: {error}", file=sys.stderr)
        raise
