#!/usr/bin/env python3
"""Baixa, agrega e importa os microdados oficiais do Novo CAGED no Supabase."""

import argparse
import csv
import hashlib
import io
import os
import re
import shutil
import tempfile
import time
import unicodedata
from collections import defaultdict
from ftplib import FTP, all_errors
from pathlib import Path
from urllib.parse import unquote, urlparse

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
    "municipality": (
        "codigomunicipio",
        "codigo_municipio",
        "municipio",
        "nome_municipio",
        "municipioempregador",
    ),
    "movement": (
        "saldomovimentacao",
        "saldo_movimentacao",
        "saldo",
    ),
    "section": (
        "cnae20secao",
        "cnae_2_0_secao",
        "secao",
    ),
    "sex": ("sexo",),
    "age": ("idade",),
    "education": (
        "graudeinstrucao",
        "grau_de_instrucao",
    ),
}


def clean(value):
    value = unicodedata.normalize("NFKD", str(value))
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]", "", value.lower())


def normalize_name(value):
    value = unicodedata.normalize("NFKD", str(value))
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def pick(row, key):
    for alias in ALIASES[key]:
        value = row.get(alias)
        if value not in (None, ""):
            return str(value).strip()
    return "Não informado"


def municipality_code(value):
    """Converte código ou nome do município em código IBGE."""
    text = str(value).strip()

    code_match = re.search(r"\b(\d{7})\b", text)
    if code_match and code_match.group(1) in MUNICIPALITIES:
        return code_match.group(1)

    normalized_value = normalize_name(text)

    for code, name in MUNICIPALITIES.items():
        normalized_name = normalize_name(name)

        if normalized_value == normalized_name:
            return code

        if normalized_name in normalized_value:
            return code

    return None


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
    """Monta as URLs reais: ano/competência/arquivo."""
    year = competence[:4]
    filename = f"CAGEDMOV{competence}"
    extensions = (".7z", ".zip", ".txt")

    ftp_base = (
        f"ftp://ftp.mtps.gov.br/pdet/microdados/"
        f"NOVO%20CAGED/{year}/{competence}"
    )
    https_base = (
        f"https://ftp.mtps.gov.br/pdet/microdados/"
        f"NOVO%20CAGED/{year}/{competence}"
    )

    configured = (os.getenv("CAGED_SOURCE_BASE_URL") or "").format(
        year=year,
        competencia=competence,
    ).rstrip("/")

    bases = [ftp_base, https_base]

    if configured and configured not in bases:
        bases.append(configured)

    return [
        f"{base}/{filename}{extension}"
        for base in bases
        for extension in extensions
    ]


def download_by_ftp(url, destination):
    parsed = urlparse(url)
    directory, filename = os.path.split(unquote(parsed.path))

    ftp = FTP()
    ftp.connect(parsed.hostname, parsed.port or 21, timeout=45)
    ftp.login()
    ftp.set_pasv(True)

    with destination.open("wb") as output:
        ftp.retrbinary(
            f"RETR {directory}/{filename}",
            output.write,
            blocksize=1024 * 1024,
        )

    ftp.quit()


def download(competence):
    for url in candidate_urls(competence):
        for attempt in range(1, 4):
            destination = None

            try:
                suffix = Path(urlparse(url).path).suffix
                destination = Path(tempfile.mkdtemp()) / f"caged{suffix}"

                if url.startswith("ftp://"):
                    download_by_ftp(url, destination)
                    return destination, url

                response = requests.get(url, stream=True, timeout=(30, 600))

                if response.status_code != 200:
                    print(f"Fonte indisponível ({response.status_code}): {url}")
                    shutil.rmtree(destination.parent, ignore_errors=True)
                    break

                with destination.open("wb") as output:
                    for part in response.iter_content(1024 * 1024):
                        if part:
                            output.write(part)

                return destination, url

            except all_errors + (requests.RequestException, OSError) as error:
                print(f"Tentativa {attempt}/3 falhou para {url}: {error}")

                if destination:
                    shutil.rmtree(destination.parent, ignore_errors=True)

                if attempt < 3:
                    time.sleep(attempt * 20)

    raise FileNotFoundError(
        f"Competência {competence} ainda não encontrada na fonte oficial."
    )


def text_stream(path):
    if path.suffix.lower() == ".txt":
        return io.TextIOWrapper(
            path.open("rb"),
            encoding="latin1",
            errors="replace",
        )

    if path.suffix.lower() == ".zip":
        import zipfile

        archive = zipfile.ZipFile(path)
        name = next(
            name for name in archive.namelist()
            if name.lower().endswith(".txt")
        )

        return io.TextIOWrapper(
            archive.open(name),
            encoding="latin1",
            errors="replace",
        )

    if path.suffix.lower() == ".7z":
        if not py7zr:
            raise RuntimeError(
                "Arquivo .7z exige py7zr. "
                "Verifique importer/requirements.txt."
            )

        folder = path.parent / "extract"

        with py7zr.SevenZipFile(path, mode="r") as archive:
            archive.extractall(folder)

        text_file = next(folder.rglob("*.txt"))

        return io.TextIOWrapper(
            text_file.open("rb"),
            encoding="latin1",
            errors="replace",
        )

    raise RuntimeError(f"Formato não suportado: {path.suffix}")


def aggregate(path):
    stream = text_stream(path)

    sample = stream.read(10000)
    stream.seek(0)

    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,|")
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = ";"

    reader = csv.DictReader(stream, dialect=dialect)
    reader.fieldnames = [clean(name) for name in reader.fieldnames]

    print(f"Delimitador identificado: {repr(dialect.delimiter)}")
    print(f"Cabeçalhos encontrados: {reader.fieldnames}")

    totals = defaultdict(lambda: [0, 0])
    matched = 0

    for raw in reader:
        row = {clean(key): value for key, value in raw.items()}

        municipality = municipality_code(pick(row, "municipality"))

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
        "Prefer": "resolution=merge-duplicates",
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

    supabase_request(
        "POST",
        "caged_imports",
        supabase_url,
        key,
        {
            "competence": month,
            "source_url": source_url,
            "source_sha256": digest,
            "rows_processed": matched,
            "status": "completed",
        },
        "?on_conflict=competence",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--competencia",
        required=True,
        help="AAAAMM, por exemplo 202606",
    )
    arguments = parser.parse_args()

    if not re.fullmatch(r"20\d{2}(0[1-9]|1[0-2])", arguments.competencia):
        parser.error("Use AAAAMM, por exemplo 202606.")

    source_file, source_url = download(arguments.competencia)

    try:
        totals, matched = aggregate(source_file)

        if not matched:
            raise RuntimeError(
                "Nenhum registro dos 13 municípios encontrado; "
                "verifique os cabeçalhos impressos acima no log."
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
