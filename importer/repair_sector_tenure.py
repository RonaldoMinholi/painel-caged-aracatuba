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
    RA_MUNICIPALITIES, municipality_code, official_sector_tenure,
    pbi_context, powerbi_official_occupation_tenure, powerbi_official_occupation_summaries,
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


def official_occupation_tenure(competence):
    """Lê a medida CBO publicada pelo Power BI, em lotes pequenos de cidades."""
    api, resource_key, model_id = pbi_context()
    results = {}
    codes = list(RA_MUNICIPALITIES)
    for start in range(0, len(codes), 6):
        for code, occupation_group, tenure in powerbi_official_occupation_tenure(
            api, resource_key, model_id, competence, codes[start:start + 6]
        ):
            code = municipality_code(code)
            if code not in RA_MUNICIPALITIES or not occupation_group:
                continue
            try:
                results[(code, occupation_group)] = float(tenure)
            except (TypeError, ValueError):
                continue
    return results


def official_occupation_summaries(competence):
    api, resource_key, model_id = pbi_context()
    results = []
    codes = list(RA_MUNICIPALITIES)
    for start in range(0, len(codes), 6):
        for code, group, admissions, dismissals, tenure in powerbi_official_occupation_summaries(api, resource_key, model_id, competence, codes[start:start + 6]):
            code = municipality_code(code)
            if code not in RA_MUNICIPALITIES or not group:
                continue
            try:
                results.append({"ibge_code": code, "occupation_group": group, "admissions": int(admissions or 0), "dismissals": int(dismissals or 0), "average_dismissal_tenure": float(tenure) if tenure is not None else 0})
            except (TypeError, ValueError):
                continue
    return results


def replace_occupation_summary(competence, occupations):
    url, key = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    response = requests.post(f"{url}/rest/v1/rpc/caged_occupation_replace_official_summary", headers={"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}, json={"p_competence": f"{competence[:4]}-{competence[4:]}-01", "p_occupations": occupations}, timeout=180)
    response.raise_for_status()


def apply_occupation_tenure(competence, occupations):
    url = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    payload = {
        "p_competence": f"{competence[:4]}-{competence[4:]}-01",
        "p_occupations": [
            {
                "ibge_code": code,
                "occupation_group": group,
                "average_dismissal_tenure": average,
            }
            for (code, group), average in occupations.items()
        ],
    }
    response = requests.post(
        f"{url}/rest/v1/rpc/caged_occupation_apply_official_tenure",
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
        occupations = official_occupation_tenure(competence)
        apply_occupation_tenure(competence, occupations)
        occupation_summary = official_occupation_summaries(competence)
        replace_occupation_summary(competence, occupation_summary)
        print(f"  grupos: {len(groups)}; detalhamentos: {len(details)}; ocupações: {len(occupation_summary)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERRO: {error}", file=sys.stderr)
        raise
