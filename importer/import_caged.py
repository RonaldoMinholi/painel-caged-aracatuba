#!/usr/bin/env python3
"""Download, aggregate and import official Novo CAGED files into Supabase."""
import argparse
import csv
import hashlib
import io
import os
import re
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path

import requests

try:
    import py7zr
except ImportError:
    py7zr = None

MUNICIPALITIES = {
    "3506402": "Bilac",
    "3506501": "Birigui",
    "3507707": "Braúna",
    "3508101": "Buritama",
    "3512509": "Clementina",
    "3515601": "Coroados",
    "3516500": "Gabriel Monteiro",
    "3517102": "Glicério",
    "3527259": "Lourdes",
    "3527705": "Luiziânia",
    "3537407": "Piacatu",
    "3548404": "Santópolis do Aguapeí",
    "3555201": "Turiúba",
}

ALIASES = {
    "municipality": ("codigomunicipio", "codigo_municipio", "municipio"),
    "movement": ("saldomovimentacao", "saldo_movimentacao"),
    "section": ("cnae20secao", "cnae_2_0_secao", "secao"),
    "sex": ("sexo",),
    "age": ("idade",),
    "education": ("graudeinstrucao", "grau_de_instrucao"),
}


def clean(value):
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def pick(row, key):
    for alias in ALIASES[key]:
        value = row.get(alias)
        if value not in (None, ""):
            return str(value).strip()
    return "Não informado"


def age_band(value):
    try:
        age = int(float(value))
    except (TypeError, ValueError):
        return "Não informado"

    if age <= 17:
        return "Até 17 anos"
    if age <= 24:
        return "18 a 24 anos"
    if age <= 29:
        return "25 a 29 anos"
    if age <= 39:
        return "30 a 39 anos"
    if age <= 49:
        return "40 a 49 anos"
    if age <= 64:
        return "50 a 64 anos"
    return "65 anos ou mais"


def candidate_urls(competence):
    year = competence[:4]

    source_base = (
        os.getenv("CAGED_SOURCE_BASE_URL")
        or "https://ftp.mtps.gov.br/pdet/microdados/NOVO%20CAGED/{year}"
    )
    base = source_base.format(year=year).rstrip("/")

    filename = f"CAGEDMOV{competence}"

    return [
        f"{base}/{filename}.zip",
        f"{base}/{filename}.7z",
        f"{base}/{filename}.txt",
    ]


def download(competence):
    for url in candidate_urls(competence):
        response = requests.get(url, stream=True, timeout=90)

        if response.status_code != 200:
            continue

        suffix = Path(url).suffix
        destination = Path(tempfile.mkdtemp()) / f"caged{suffix}"

        with destination.open("wb") as output:
            for part in response.iter_content(1024 * 1024):
                output.write(part)

        return destination, url

    raise FileNotFoundError(
        f"Competência {competence} ainda não encontrada na fonte oficial."
    )


def text_stream(path):
    if path.suffix == ".txt":
        return io.TextIOWrapper(
            path.open("rb"),
            encoding="latin1",
            errors="replace",
        )

    if path.suffix == ".zip":
        import zipfile

        archive = zipfile.ZipFile(path)
        name = next(
            item for item in archive.namelist()
            if item.lower().endswith(".txt")
        )

        return io.TextIOWrapper(
            archive.open(name),
            encoding="latin1",
            errors="replace",
        )

    if path.suffix == ".7z" and py7zr:
        folder = path.parent / "extract"

        with py7zr.SevenZipFile(path, mode="r") as archive:
            archive.extractall(folder)

        return io.TextIOWrapper(
            next(folder.rglob("*.txt")).open("rb"),
            encoding="latin1",
            errors="replace",
        )

    raise RuntimeError(
        "Arquivo .7z exige py7zr. Execute pip install -r importer/requirements.txt."
    )


def aggregate(path):
    stream = text_stream(path)
    reader = csv.DictReader(stream, delimiter=";")
    reader.fieldnames = [clean(name) for name in reader.fieldnames]

    totals = defaultdict(lambda: [0, 0])
    matched = 0

    for raw in reader:
        row = {clean(key): value for key, value in raw.items()}
        municipality = pick(row, "municipality").zfill(7)

        if municipality not in MUNICIPALITIES:
            continue

        try:
            movement = int(float(pick(row, "movement")))
        except ValueError:
            continue

        key = (
            municipality,
            pick(row, "section"),
            pick(row, "sex"),
            age_band(pick(row, "age")),
            pick(row, "education"),
        )

        if movement > 0:
            totals[key][0] += 1
        elif movement < 0:
            totals[key][1] += 1

        matched += 1

    return totals, matched


def supabase_request(method, table, url, key, payload=None, query=""):
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    response = requests.request(
        method,
        f"{url}/rest/v1/{table}{query}",
        headers=headers,
        json=payload,
        timeout=120,
    )

    response.raise_for_status()


def import_data(competence, source_file, source_url, totals, matched):
    supabase_url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not supabase_url or not key:
        raise RuntimeError(
            "Defina SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY."
        )

    month = f"{competence[:4]}-{competence[4:]}-01"

    records = [
        {
            "competence": month,
            "ibge_code": municipality,
            "cnae_section": section,
            "sex": sex,
            "age_band": age,
            "education": education,
            "admissions": values[0],
            "dismissals": values[1],
            "balance": values[0] - values[1],
        }
        for (municipality, section, sex, age, education), values
        in totals.items()
    ]

    supabase_request(
        "DELETE",
        "caged_monthly",
        supabase_url,
        key,
        query=f"?competence=eq.{month}",
    )

    for index in range(0, len(records), 500):
        supabase_request(
            "POST",
            "caged_monthly",
            supabase_url,
            key,
            records[index:index + 500],
            "?on_conflict=competence,ibge_code,cnae_section,sex,age_band,education",
        )

    digest = hashlib.sha256(source_file.read_bytes()).hexdigest()

    metadata = {
        "competence": month,
        "source_url": source_url,
        "source_sha256": digest,
        "rows_processed": matched,
        "status": "completed",
    }

    supabase_request(
        "POST",
        "caged_imports",
        supabase_url,
        key,
        metadata,
        "?on_conflict=competence",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--competencia",
        required=True,
        help="AAAAMM",
    )
    arguments = parser.parse_args()

    if not re.fullmatch(r"20\d{2}(0[1-9]|1[0-2])", arguments.competencia):
        parser.error("Use AAAAMM, por exemplo 202607.")

    source_file, source_url = download(arguments.competencia)

    try:
        totals, matched = aggregate(source_file)

        if not matched:
            raise RuntimeError(
                "Nenhum registro dos 13 municípios encontrado; "
                "verifique o layout do arquivo."
            )

        import_data(
            arguments.competencia,
            source_file,
            source_url,
            totals,
            matched,
        )

        print(
            f"Importação concluída: {arguments.competencia}; "
            f"{matched} movimentos; {len(totals)} agregados."
        )

    finally:
        shutil.rmtree(source_file.parent, ignore_errors=True)


if __name__ == "__main__":
    main()
