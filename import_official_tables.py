#!/usr/bin/env python3
"""Importa a Tabela 8.1 oficial do Novo CAGED (série com ajustes)."""

import argparse
import hashlib
import os
import re
from datetime import date
from pathlib import Path

import openpyxl

MUNICIPALITIES = {
    '350640': '3506402', '350650': '3506501', '350770': '3507707',
    '350810': '3508101', '351250': '3512509', '351560': '3515601',
    '351650': '3516500', '351710': '3517102', '352725': '3527259',
    '352770': '3527705', '353740': '3537407', '354840': '3548404',
    '355520': '3555201',
}

MONTHS = {
    'janeiro': 1,
    'fevereiro': 2,
    'março': 3,
    'abril': 4,
    'maio': 5,
    'junho': 6,
    'julho': 7,
    'agosto': 8,
    'setembro': 9,
    'outubro': 10,
    'novembro': 11,
    'dezembro': 12,
}


def integer(value):
    return 0 if value in (None, '') else int(round(float(value)))


def competence_from_header(value):
    match = re.fullmatch(r'\s*([A-Za-zçÇãÃ]+)/(20\d{2})\s*', str(value or ''))

    if not match or match.group(1).lower() not in MONTHS:
        return None

    return date(
        int(match.group(2)),
        MONTHS[match.group(1).lower()],
        1,
    )


def extract_records(workbook_path, source_url):
    workbook = openpyxl.load_workbook(
        workbook_path,
        read_only=True,
        data_only=True,
    )

    if 'Tabela 8.1' not in workbook.sheetnames:
        raise RuntimeError('A planilha não possui a aba "Tabela 8.1".')

    sheet = workbook['Tabela 8.1']

    headers = list(
        next(
            sheet.iter_rows(
                min_row=5,
                max_row=5,
                values_only=True,
            )
        )
    )

    month_columns = [
        (index, competence_from_header(value))
        for index, value in enumerate(headers)
        if competence_from_header(value)
    ]

    if not month_columns:
        raise RuntimeError(
            'Não foi possível localizar as competências da Tabela 8.1.'
        )

    records = []
    found = set()

    for row in sheet.iter_rows(min_row=7, values_only=True):
        code_six_digits = str(row[2] or '').split('.')[0].zfill(6)
        ibge_code = MUNICIPALITIES.get(code_six_digits)

        if not ibge_code:
            continue

        found.add(ibge_code)

        for start, competence in month_columns:
            records.append(
                {
                    'competence': competence.isoformat(),
                    'ibge_code': ibge_code,
                    'stock': integer(row[start]),
                    'admissions': integer(row[start + 1]),
                    'dismissals': integer(row[start + 2]),
                    'balance': integer(row[start + 3]),
                    'source_url': source_url,
                }
            )

    missing = sorted(set(MUNICIPALITIES.values()) - found)

    if missing:
        raise RuntimeError(
            f'Municípios ausentes na Tabela 8.1: {", ".join(missing)}.'
        )

    return records


def supabase_request(method, table, url, key, payload=None, query=''):
    import requests

    headers = {
        'apikey': key,
        'Authorization': f'Bearer {key}',
        'Content-Type': 'application/json',
    }

    response = requests.request(
        method,
        f'{url}/rest/v1/{table}{query}',
        headers=headers,
        json=payload,
        timeout=120,
    )

    response.raise_for_status()


def save(records, workbook_path, source_url):
    url = os.getenv('SUPABASE_URL')
    key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

    if not url or not key:
        raise RuntimeError(
            'Defina SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY.'
        )

    for start in range(0, len(records), 500):
        supabase_request(
            'POST',
            'caged_official_monthly',
            url,
            key,
            records[start:start + 500],
            '?on_conflict=competence,ibge_code',
        )

    dates = sorted(row['competence'] for row in records)

    metadata = {
        'source_url': source_url,
        'source_sha256': hashlib.sha256(
            workbook_path.read_bytes()
        ).hexdigest(),
        'competence_start': dates[0],
        'competence_end': dates[-1],
        'rows_imported': len(records),
    }

    supabase_request(
        'POST',
        'caged_official_imports',
        url,
        key,
        metadata,
        '?on_conflict=source_url',
    )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument('--file', required=True)
    parser.add_argument('--source-url', required=True)
    parser.add_argument('--dry-run', action='store_true')

    args = parser.parse_args()

    workbook_path = Path(args.file)

    if not workbook_path.is_file():
        parser.error(f'Arquivo não encontrado: {workbook_path}')

    records = extract_records(workbook_path, args.source_url)

    birigui = next(
        row
        for row in records
        if row['ibge_code'] == '3506501'
        and row['competence'] == '2026-06-01'
    )

    print(
        'Validação Birigui 2026-06: '
        f'estoque {birigui["stock"]}; '
        f'admissões {birigui["admissions"]}; '
        f'desligamentos {birigui["dismissals"]}; '
        f'saldo {birigui["balance"]}.'
    )

    if args.dry_run:
        print(f'Validação concluída: {len(records)} registros.')
        return

    save(records, workbook_path, args.source_url)

    print(
        f'Importação oficial concluída: {len(records)} registros, '
        f'de {records[0]["competence"]} a {records[-1]["competence"]}.'
    )


if __name__ == '__main__':
    main()
