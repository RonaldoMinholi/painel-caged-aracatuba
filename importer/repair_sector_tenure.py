#!/usr/bin/env python3
"""Preenche somente Tempo de Emprego da página Setorial pela fonte oficial.

Não baixa CAGEDMOV nem altera admissões, desligamentos, saldo ou estoque.
Foi criado para corrigir lacunas históricas dos microdados, principalmente 2020.
"""

import argparse
import os
import re
import sys
import uuid
from collections import defaultdict
from datetime import date

import requests

from import_caged import (
    RA_MUNICIPALITIES, PBI_FACT, activity_name, cnae_levels, decode_pbi_rows,
    group_name, municipality_code, pbi_column, pbi_context, pbi_measure,
    pbi_where, powerbi_query,
)


def months_between(first, last):
    if not re.fullmatch(r"20\d{2}(0[1-9]|1[0-2])", first):
        raise ValueError("Mês inicial inválido: use AAAAMM.")
    if not re.fullmatch(r"20\d{2}(0[1-9]|1[0-2])", last):
        raise ValueError("Mês final inválido: use AAAAMM.")
    value, result = first, []
    while value <= last:
        result.append(value)
        year, month = int(value[:4]), int(value[4:])
        value = f"{year + (month == 12):04d}{1 if month == 12 else month + 1:02d}"
    return result


def official_sector_tenure(competence):
    """Lê a média oficial por subclasse em grupos de até seis municípios.

    A consulta é pequena (município + subclasse), portanto não sofre o corte
    público de 30 mil linhas que existe nas consultas detalhadas por trabalhador.
    """
    api, resource_key, model_id = pbi_context()
    data_source, measures_source = "d", "m"
    select = [
        pbi_column(data_source, "município"),
        pbi_column(data_source, "subclasse"),
        pbi_measure(measures_source, "Desligados"),
        pbi_measure(measures_source, "Tempo de Emprego (Desligados)"),
    ]
    groups = defaultdict(lambda: [0.0, 0])
    details = defaultdict(lambda: [0.0, 0])
    codes = list(RA_MUNICIPALITIES)

    for start in range(0, len(codes), 6):
        batch = codes[start:start + 6]
        command = {
            "SemanticQueryDataShapeCommand": {
                "Query": {
                    "Version": 2,
                    "From": [
                        {"Name": data_source, "Entity": PBI_FACT, "Type": 0},
                        {"Name": measures_source, "Entity": "Medidas", "Type": 0},
                    ],
                    "Select": select,
                    "Where": [
                        pbi_where(data_source, "competência", [competence]),
                        pbi_where(data_source, "município", batch),
                    ],
                },
                "Binding": {
                    "DataReduction": {"DataVolume": 6, "Primary": {"Window": {"Count": 10000}}},
                    "Primary": {"Groupings": [{"Projections": list(range(len(select)))}]},
                    "Version": 1,
                },
                "ExecutionMetricsKind": 1,
            }
        }
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-PowerBI-ResourceKey": resource_key,
            "ActivityId": str(uuid.uuid4()),
            "RequestId": str(uuid.uuid4()),
        }
        payload = {
            "version": "1.0.0",
            "queries": [{"Query": {"Commands": [command]}}],
            "modelId": model_id,
        }
        response = powerbi_query(api, headers, payload)
        data = response.json()["results"][0]["result"]["data"]
        dataset = data.get("dsr", {}).get("DS", [{}])[0]
        raw_rows = dataset.get("PH", [{}])[0].get("DM0", [])
        schema = raw_rows[0].get("S", []) if raw_rows else []
        dictionaries = {
            index: value["DN"] for index, value in enumerate(schema) if value.get("DN")
        }
        for city, subclass, dismissals, tenure in decode_pbi_rows(
            raw_rows, len(select), dataset.get("ValueDicts", {}), dictionaries
        ):
            code = municipality_code(city)
            if code not in RA_MUNICIPALITIES:
                continue
            dismissals = int(dismissals or 0)
            try:
                tenure = float(tenure)
            except (TypeError, ValueError):
                continue
            if not dismissals:
                continue
            group = group_name(subclass)
            section, *_ = cnae_levels(subclass)
            detail = activity_name(group, section)
            groups[(code, group)][0] += tenure * dismissals
            groups[(code, group)][1] += dismissals
            details[(code, group, detail)][0] += tenure * dismissals
            details[(code, group, detail)][1] += dismissals
    return groups, details


def apply_tenure(competence, groups, details):
    url = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    payload = {
        "p_competence": f"{competence[:4]}-{competence[4:]}-01",
        "p_groups": [
            {
                "ibge_code": code,
                "group_name": group,
                "dismissal_tenure_sum": values[0],
                "dismissal_tenure_count": values[1],
            }
            for (code, group), values in groups.items()
        ],
        "p_details": [
            {
                "ibge_code": code,
                "group_name": group,
                "activity_name": activity,
                "dismissal_tenure_sum": values[0],
                "dismissal_tenure_count": values[1],
            }
            for (code, group, activity), values in details.items()
        ],
    }
    response = requests.post(
        f"{url}/rest/v1/rpc/caged_group_apply_official_tenure",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=180,
    )
    response.raise_for_status()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--competencia-inicial", default="202001")
    parser.add_argument("--competencia-final", default=date.today().strftime("%Y%m"))
    args = parser.parse_args()
    try:
        competences = months_between(args.competencia_inicial, args.competencia_final)
    except ValueError as error:
        parser.error(str(error))

    for competence in competences:
        print(f"Tempo setorial oficial: {competence}")
        groups, details = official_sector_tenure(competence)
        apply_tenure(competence, groups, details)
        print(f"  grupos: {len(groups)}; detalhamentos: {len(details)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERRO: {error}", file=sys.stderr)
        raise
