#!/usr/bin/env python3
"""Corrige somente o tempo CBO detalhado com a medida oficial do Power BI."""

import argparse
import os
from collections import defaultdict

import requests

from import_caged import (
    RA_MUNICIPALITIES, cnae_levels, group_name, municipality_code,
    powerbi_official_occupation_detail_tenure, pbi_context, supabase_request,
    yes_indicator,
)


def fetch_all(url, key, table, params):
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Range-Unit": "items"}
    rows, start = [], 0
    while True:
        response = requests.get(
            f"{url.rstrip('/')}/rest/v1/{table}", headers={**headers, "Range": f"{start}-{start + 999}"},
            params=params, timeout=180,
        )
        response.raise_for_status()
        page = response.json()
        rows.extend(page)
        if len(page) < 1000:
            return rows
        start += 1000


def month_value(competence):
    return f"{competence[:4]}-{competence[4:]}-01"


def next_month(competence):
    year, month = int(competence[:4]), int(competence[4:])
    return f"{year + 1:04d}01" if month == 12 else f"{year:04d}{month + 1:02d}"


def available_competences(url, key, initial, final):
    rows = fetch_all(
        url, key, "caged_occupation_worker_monthly",
        {"select": "competence", "competence": f"gte.{month_value(initial)}", "order": "competence"},
    )
    return sorted({
        str(row["competence"])[:7].replace("-", "")
        for row in rows
        if initial <= str(row["competence"])[:7].replace("-", "") <= final
    })


def key_from_official(row):
    code, subclass, occupation, apprentice, intermittent, temporary, foreigner, dismissals, tenure = row
    code = municipality_code(code)
    name = str(occupation or "").strip()
    section, division, cnae_group, cnae_class, cnae_subclass = cnae_levels(subclass)
    return (
        code, name, group_name(subclass), section, division, cnae_group,
        cnae_class, cnae_subclass, yes_indicator(apprentice),
        yes_indicator(intermittent), yes_indicator(temporary), yes_indicator(foreigner),
    ), int(dismissals or 0), tenure


def key_from_record(row):
    return (
        str(row["ibge_code"]), str(row["occupation_group"] or "").strip(),
        row["cnae_large_group"], row["cnae_section"], row["cnae_division"],
        row["cnae_group"], row["cnae_class"], row["cnae_subclass"],
        row["is_apprentice"], row["is_intermittent"], row["is_temporary"],
        row["is_foreigner"],
    )


def correct_month(url, key, competence):
    api, resource_key, model_id = pbi_context()
    expected = {}
    for city in RA_MUNICIPALITIES:
        for row in powerbi_official_occupation_detail_tenure(
            api, resource_key, model_id, competence, [city]
        ):
            item_key, dismissals, tenure = key_from_official(row)
            if item_key[0] not in RA_MUNICIPALITIES or not item_key[1] or tenure is None:
                continue
            expected[item_key] = (dismissals, float(tenure))

    records = fetch_all(
        url, key, "caged_occupation_worker_monthly",
        {"select": "*", "competence": f"eq.{month_value(competence)}"},
    )
    if not records:
        print(f"{competence}: sem dados; ignorado.")
        return

    actual = {key_from_record(row): row for row in records}
    missing = [item for item in expected if item not in actual]
    mismatched_flows = [
        item for item, (dismissals, _) in expected.items()
        if item in actual and int(actual[item]["dismissals"] or 0) != dismissals
    ]
    if missing or mismatched_flows:
        raise RuntimeError(
            f"{competence}: correção cancelada; {len(missing)} chaves ausentes e "
            f"{len(mismatched_flows)} desligamentos divergentes."
        )

    changed = 0
    for item, (_, tenure) in expected.items():
        record = actual[item]
        if record["average_dismissal_tenure"] is None or abs(float(record["average_dismissal_tenure"]) - tenure) > 0.0001:
            record["average_dismissal_tenure"] = tenure
            changed += 1

    supabase_request(
        "DELETE", "caged_occupation_worker_monthly", url, key,
        query=f"?competence=eq.{month_value(competence)}",
    )
    for index in range(0, len(records), 100):
        supabase_request(
            "POST", "caged_occupation_worker_monthly", url, key, records[index:index + 100],
            "?on_conflict=competence,ibge_code,occupation_group,cnae_large_group,cnae_section,cnae_division,cnae_group,cnae_class,cnae_subclass,is_apprentice,is_intermittent,is_temporary,is_foreigner",
        )

    # Confere o que foi realmente persistido antes de considerar o mês concluído.
    saved = {
        key_from_record(row): row for row in fetch_all(
            url, key, "caged_occupation_worker_monthly",
            {"select": "*", "competence": f"eq.{month_value(competence)}"},
        )
    }
    failed = [
        item for item, (_, tenure) in expected.items()
        if item not in saved
        or saved[item]["average_dismissal_tenure"] is None
        or abs(float(saved[item]["average_dismissal_tenure"]) - tenure) > 0.0001
    ]
    if failed:
        raise RuntimeError(f"{competence}: {len(failed)} tempos não foram gravados corretamente.")
    print(f"{competence}: {changed} tempos CBO corrigidos e conferidos ({len(records)} linhas preservadas).")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inicio", default="202001")
    parser.add_argument("--fim", default="202607")
    args = parser.parse_args()
    if not (args.inicio.isdigit() and args.fim.isdigit() and len(args.inicio) == len(args.fim) == 6):
        raise RuntimeError("Use início e fim no formato AAAAMM.")
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY são obrigatórios.")

    competences = available_competences(url, key, args.inicio, args.fim)
    if not competences:
        raise RuntimeError("Nenhuma competência importada no período informado.")
    print(f"Competências a corrigir: {', '.join(competences)}")
    for competence in competences:
        correct_month(url, key, competence)


if __name__ == "__main__":
    main()
