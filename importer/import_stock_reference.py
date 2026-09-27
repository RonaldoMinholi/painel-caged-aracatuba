#!/usr/bin/env python3
"""Importa o Estoque de Referência oficial por município e CNAE Subclasse."""

import argparse
import csv
import io
import os
import re
import zipfile
from collections import defaultdict
from pathlib import Path

import requests

RA_MUNICIPALITIES = {
    "350110", "350210", "350280", "350420", "350440", "350510", "350620",
    "350640", "350650", "350770", "350775", "350810", "351100", "351190",
    "351250", "351650", "351680", "351690", "351710", "351780", "351820",
    "351890", "352044", "352300", "352650", "352725", "352770", "353010",
    "353210", "353286", "353320", "353330", "353730", "353740", "353770",
    "354440", "354805", "354840", "354925", "355230", "355255", "355520",
    "355630",
}

def group_name(cnae_subclass):
    digits = re.sub(r"\D", "", str(cnae_subclass))
    if len(digits) < 2:
        return "Não identificado"
    # Subclasses CNAE iniciadas em zero chegam sem o zero à esquerda em parte dos arquivos.
    digits = digits.zfill(7)
    division = int(digits[:2])
    if 1 <= division <= 3:
        return "Agropecuária"
    if 5 <= division <= 39:
        return "Indústria"
    if 41 <= division <= 43:
        return "Construção"
    if 45 <= division <= 47:
        return "Comércio"
    if 49 <= division <= 99:
        return "Serviços"
    return "Não identificado"

def request(method, table, url, key, payload, query=""):
    response = requests.request(
        method, f"{url}/rest/v1/{table}{query}",
        headers={
            "apikey": key, "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates",
        },
        json=payload, timeout=180,
    )
    response.raise_for_status()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, help="ZIP oficial EstoquePAE2026CNAExMun")
    args = parser.parse_args()

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("Defina SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY.")

    with zipfile.ZipFile(Path(args.file)) as archive:
        name = next(item for item in archive.namelist() if item.lower().endswith(".txt"))
        with archive.open(name) as raw:
            reader = csv.DictReader(io.TextIOWrapper(raw, encoding="latin1"), delimiter=";")
            totals = defaultdict(int)
            for row in reader:
                code = re.sub(r"\D", "", row.get("codmun", ""))[:6]
                if code not in RA_MUNICIPALITIES:
                    continue
                try:
                    stock = int(float(row.get("estoqueref", "0")))
                except ValueError:
                    continue
                totals[(code, group_name(row.get("cnae20subclas")))] += stock

    records = [
        {"ibge_code": code, "group_name": group, "reference_stock": stock}
        for (code, group), stock in totals.items()
    ]
    request("DELETE", "caged_group_reference_stock", url, key, [], "?ibge_code=in.(" + ",".join(sorted(RA_MUNICIPALITIES)) + ")")
    for index in range(0, len(records), 100):
        request("POST", "caged_group_reference_stock", url, key, records[index:index + 100],
                "?on_conflict=ibge_code,group_name")
    print(f"Estoque de referência importado: {len(records)} linhas municipais.")

if __name__ == "__main__":
    main()
