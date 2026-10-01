#!/usr/bin/env python3
"""Reconstrói a tabela CBO detalhada a partir do Power BI oficial."""

import argparse
import os
import uuid

import requests

from import_caged import (
    PBI_FACT, RA_MUNICIPALITIES, cnae_levels, decode_pbi_rows, group_name,
    municipality_code, pbi_column, pbi_context, pbi_hierarchy_level, pbi_measure,
    pbi_sum, pbi_where, pbi_where_expression, powerbi_query, supabase_request,
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


def official_records(competence, occupation_groups):
    """Consulta a mesma medida e as mesmas dimensões da tabela CBO oficial."""
    api, resource_key, model_id = pbi_context()
    d, o, m = "d", "o", "m"
    occupation_hierarchy = pbi_hierarchy_level(
        "Ocupacional", "Hierarquia Ocupacional", "Grande Grupo"
    )
    select = [
        pbi_column(d, "município"),
        pbi_column(d, "subclasse"),
        occupation_hierarchy,
        pbi_column(d, "indicadoraprendiz"),
        pbi_column(d, "indtrabintermitente"),
        pbi_column(d, "indtrabtemp"),
        pbi_column(d, "indestrangeiro"),
        pbi_sum(d, "Admitidos"),
        pbi_sum(d, "Desligados"),
        pbi_measure(m, "Tempo de Emprego (Desligados)"),
    ]
    records = []
    # A API pública corta respostas grandes em 30 mil linhas. Dividir também
    # por Grande Grupo Ocupacional evita a perda silenciosa de registros.
    for city in RA_MUNICIPALITIES:
        for occupation_filter in occupation_groups:
            command = {
            "SemanticQueryDataShapeCommand": {
                "Query": {
                    "Version": 2,
                    "From": [
                        {"Name": d, "Entity": PBI_FACT, "Type": 0},
                        {"Name": o, "Entity": "Ocupacional", "Type": 0},
                        {"Name": m, "Entity": "Medidas", "Type": 0},
                    ],
                    "Select": select,
                    "Where": [
                        pbi_where(d, "competência", [competence]),
                        pbi_where(d, "município", [city]),
                        pbi_where_expression(occupation_hierarchy, [occupation_filter]),
                    ],
                },
                "Binding": {
                    "DataReduction": {"DataVolume": 6, "Primary": {"Window": {"Count": 30000}}},
                    "Primary": {"Groupings": [{"Projections": list(range(len(select)))}]},
                    "Version": 1,
                },
                "ExecutionMetricsKind": 1,
            }
        }
            headers = {
                "Accept": "application/json", "Content-Type": "application/json",
                "X-PowerBI-ResourceKey": resource_key,
                "ActivityId": str(uuid.uuid4()), "RequestId": str(uuid.uuid4()),
            }
            response = powerbi_query(
                api, headers,
                {"version": "1.0.0", "queries": [{"Query": {"Commands": [command]}}], "modelId": model_id},
            )
            dataset = response.json()["results"][0]["result"]["data"].get("dsr", {}).get("DS", [{}])[0]
            raw_rows = dataset.get("PH", [{}])[0].get("DM0", [])
            schema = raw_rows[0].get("S", []) if raw_rows else []
            dictionaries = {index: column["DN"] for index, column in enumerate(schema) if column.get("DN")}
            for row in decode_pbi_rows(raw_rows, len(select), dataset.get("ValueDicts", {}), dictionaries):
                code, subclass, occupation, apprentice, intermittent, temporary, foreigner, admissions, dismissals, tenure = row
                code = municipality_code(code)
                occupation = str(occupation or "").strip()
                if code not in RA_MUNICIPALITIES or not occupation:
                    continue
                section, division, cnae_group, cnae_class, cnae_subclass = cnae_levels(subclass)
                admissions, dismissals = int(admissions or 0), int(dismissals or 0)
                records.append({
                    "competence": month_value(competence), "ibge_code": code,
                    "occupation_group": occupation, "cnae_large_group": group_name(subclass),
                    "cnae_section": section, "cnae_division": division, "cnae_group": cnae_group,
                    "cnae_class": cnae_class, "cnae_subclass": cnae_subclass,
                    "is_apprentice": yes_indicator(apprentice),
                    "is_intermittent": yes_indicator(intermittent),
                    "is_temporary": yes_indicator(temporary),
                    "is_foreigner": yes_indicator(foreigner),
                    "admissions": admissions, "dismissals": dismissals,
                    "balance": admissions - dismissals,
                    "average_dismissal_tenure": float(tenure) if dismissals and tenure is not None else None,
                })
    return records


def key_from_record(row):
    return (
        str(row["ibge_code"]), row["occupation_group"], row["cnae_large_group"],
        row["cnae_section"], row["cnae_division"], row["cnae_group"], row["cnae_class"],
        row["cnae_subclass"], row["is_apprentice"], row["is_intermittent"],
        row["is_temporary"], row["is_foreigner"],
    )


def correct_month(url, key, competence):
    existing = fetch_all(
        url, key, "caged_occupation_worker_monthly",
        {"select": "*", "competence": f"eq.{month_value(competence)}"},
    )
    occupation_groups = sorted({
        str(row["occupation_group"] or "").strip() for row in existing
        if str(row["occupation_group"] or "").strip()
    })
    official = official_records(competence, occupation_groups)
    if not official:
        raise RuntimeError(f"{competence}: Power BI oficial não retornou registros CBO.")

    # Trava contra uma resposta parcial: os fluxos globais precisam coincidir
    # antes da substituição. O tempo é a única medida que esta rotina corrige.
    existing_flows = (
        sum(int(row["admissions"] or 0) for row in existing),
        sum(int(row["dismissals"] or 0) for row in existing),
    )
    official_flows = (
        sum(row["admissions"] for row in official),
        sum(row["dismissals"] for row in official),
    )
    if existing and existing_flows != official_flows:
        raise RuntimeError(
            f"{competence}: correção cancelada; fluxos existentes {existing_flows} "
            f"não coincidem com Power BI {official_flows}."
        )

    keys = [key_from_record(row) for row in official]
    if len(keys) != len(set(keys)):
        raise RuntimeError(f"{competence}: Power BI retornou chaves CBO duplicadas.")

    supabase_request(
        "DELETE", "caged_occupation_worker_monthly", url, key,
        query=f"?competence=eq.{month_value(competence)}",
    )
    for index in range(0, len(official), 100):
        supabase_request(
            "POST", "caged_occupation_worker_monthly", url, key, official[index:index + 100],
            "?on_conflict=competence,ibge_code,occupation_group,cnae_large_group,cnae_section,cnae_division,cnae_group,cnae_class,cnae_subclass,is_apprentice,is_intermittent,is_temporary,is_foreigner",
        )

    saved = fetch_all(
        url, key, "caged_occupation_worker_monthly",
        {"select": "*", "competence": f"eq.{month_value(competence)}"},
    )
    saved_by_key = {key_from_record(row): row for row in saved}
    missing = [row for row in official if key_from_record(row) not in saved_by_key]
    changed_tenure = [
        row for row in official
        if row["dismissals"] and (
            saved_by_key[key_from_record(row)]["average_dismissal_tenure"] is None
            or abs(float(saved_by_key[key_from_record(row)]["average_dismissal_tenure"])
                   - float(row["average_dismissal_tenure"])) > 0.0001
        )
    ]
    if len(saved) != len(official) or missing or changed_tenure:
        raise RuntimeError(
            f"{competence}: persistência inválida; {len(saved)}/{len(official)} linhas, "
            f"{len(missing)} ausentes e {len(changed_tenure)} tempos divergentes."
        )
    print(f"{competence}: tabela CBO reconstruída e conferida ({len(official)} linhas).")


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
