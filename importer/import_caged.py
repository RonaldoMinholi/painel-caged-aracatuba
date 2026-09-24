#!/usr/bin/env python3
"""Importa microdados CAGEDMOV/CAGEDFOR para cubos nacionais e RA Araçatuba."""

import argparse
import csv
import hashlib
import os
import re
import shutil
import tempfile
import time
import unicodedata
import zipfile
from collections import defaultdict
from pathlib import Path

import requests

try:
    import py7zr
except ImportError:
    py7zr = None


RA_ARACATUBA_CODES = {
    "350110", "350210", "350280", "350420", "350440", "350510",
    "350620", "350640", "350650", "350770", "350775", "350810",
    "351100", "351190", "351250", "351650", "351680", "351690",
    "351710", "351780", "351820", "351890", "352044", "352300",
    "352650", "352725", "352770", "353010", "353210", "353286",
    "353320", "353330", "353730", "353740", "353770", "354440",
    "354805", "354840", "354925", "355230", "355255", "355520",
    "355630",
}

SECTIONS = {
    "A": "Agropecuária",
    "B": "Indústrias extrativas",
    "C": "Indústrias de transformação",
    "D": "Eletricidade e gás",
    "E": "Água, esgoto e gestão de resíduos",
    "F": "Construção",
    "G": "Comércio",
    "H": "Transporte, armazenagem e correio",
    "I": "Alojamento e alimentação",
    "J": "Informação e comunicação",
    "K": "Atividades financeiras e seguros",
    "L": "Atividades imobiliárias",
    "M": "Atividades profissionais, científicas e técnicas",
    "N": "Atividades administrativas e serviços complementares",
    "O": "Administração pública, defesa e seguridade social",
    "P": "Educação",
    "Q": "Saúde humana e serviços sociais",
    "R": "Artes, cultura, esporte e recreação",
    "S": "Outras atividades de serviços",
    "T": "Serviços domésticos",
    "U": "Organismos internacionais",
}

SEXES = {
    "1": "Masculino",
    "2": "Feminino",
    "3": "Feminino",
    "9": "Não informado",
}

ALIASES = {
    "municipality": (
        "codigomunicipio",
        "codigoibgemunicipio",
        "ibgemunicipio",
        "municipio",
    ),
    "movement": ("saldomovimentacao",),
    "section": ("cnae20secao", "secao"),
    "sex": ("sexo",),
    "age": ("idade",),
    "education": ("graudeinstrucao",),
}


def clean(value):
    normalized = unicodedata.normalize("NFKD", str(value))
    normalized = "".join(
        char for char in normalized if not unicodedata.combining(char)
    )
    return re.sub(r"[^a-z0-9]", "", normalized.lower())


def pick(row, key):
    for alias in ALIASES[key]:
        value = row.get(alias)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def municipality_code(value):
    digits = re.sub(r"\D", "", str(value or "").split(".")[0])
    return digits[:6] if len(digits) >= 6 else ""


def valid_municipality_code(value):
    return bool(re.fullmatch(r"[1-5]\d{5}", value or ""))


def section_name(value):
    return SECTIONS.get(
        str(value or "").strip().upper(),
        "Não informado",
    )


def sex_name(value):
    raw = str(value or "").strip().upper()

    try:
        raw = str(int(float(raw)))
    except ValueError:
        pass

    names = {
        "M": "Masculino",
        "MASCULINO": "Masculino",
        "HOMEM": "Masculino",
        "F": "Feminino",
        "FEMININO": "Feminino",
        "MULHER": "Feminino",
    }

    return SEXES.get(raw, names.get(raw, "Não informado"))


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


def extracted_text_file(path, folder):
    """Retorna um TXT físico para arquivos TXT, ZIP ou 7Z."""
    if path.suffix.lower() == ".txt":
        return path

    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            names = [
                name for name in archive.namelist()
                if name.lower().endswith(".txt")
            ]

            if not names:
                raise RuntimeError(
                    "Nenhum TXT foi localizado dentro do ZIP."
                )

            name = max(
                names,
                key=lambda item: archive.getinfo(item).file_size,
            )
            destination = folder / Path(name).name

            with archive.open(name) as source, destination.open("wb") as output:
                shutil.copyfileobj(
                    source,
                    output,
                    length=1024 * 1024,
                )

            return destination

    if path.suffix.lower() == ".7z":
        if not py7zr:
            raise RuntimeError(
                "Arquivo .7z exige py7zr. "
                "Execute pip install -r importer/requirements.txt."
            )

        with py7zr.SevenZipFile(path, mode="r") as archive:
            archive.extractall(folder)

        candidates = list(folder.rglob("*.txt"))

        if not candidates:
            raise RuntimeError(
                "Nenhum TXT foi localizado dentro do .7z."
            )

        return max(candidates, key=lambda item: item.stat().st_size)

    raise RuntimeError(f"Extensão não suportada: {path.suffix}")


def detect_encoding(text_file):
    """Escolhe a codificação depois de validar o cabeçalho do CAGED."""
    sample = text_file.open("rb").read(131072)

    for encoding in ("utf-8-sig", "latin1"):
        try:
            header = sample.decode(encoding).splitlines()[0]
        except (UnicodeDecodeError, IndexError):
            continue

        fields = {clean(name) for name in header.split(";")}

        if {"municipio", "saldomovimentacao"}.issubset(fields):
            return encoding

    raise RuntimeError(
        "Não foi possível reconhecer a codificação. "
        "As colunas município e saldo movimentação não foram encontradas."
    )


def aggregate_file(path):
    temporary_folder = None

    if path.suffix.lower() == ".txt":
        text_file = path
    else:
        temporary_folder = Path(tempfile.mkdtemp(prefix="cagedmov-"))
        text_file = extracted_text_file(path, temporary_folder)

    try:
        encoding = detect_encoding(text_file)

        print(
            f"Arquivo de movimentação identificado: {text_file.name}; "
            f"codificação: {encoding}"
        )

        with text_file.open(
            "r",
            encoding=encoding,
            errors="strict",
            newline="",
        ) as stream:
            sample = stream.read(131072)
            stream.seek(0)

            try:
                delimiter = csv.Sniffer().sniff(
                    sample,
                    delimiters=";|,\t",
                ).delimiter
            except csv.Error:
                delimiter = ";"

            print(f"Delimitador identificado: {repr(delimiter)}")

            reader = csv.DictReader(stream, delimiter=delimiter)

            if not reader.fieldnames:
                raise RuntimeError(
                    "O TXT não possui cabeçalho legível."
                )

            headers = reader.fieldnames[:]
            reader.fieldnames = [clean(name) for name in reader.fieldnames]

            if not {"municipio", "saldomovimentacao"}.issubset(
                reader.fieldnames
            ):
                raise RuntimeError(
                    f"Faltam colunas necessárias. Cabeçalhos: {headers}"
                )

            regional_totals = defaultdict(lambda: [0, 0])
            municipal_totals = defaultdict(lambda: [0, 0])
            country_totals = defaultdict(lambda: [0, 0])

            matched = 0
            samples = []

            for raw in reader:
                row = {
                    clean(key): value
                    for key, value in raw.items()
                    if key is not None
                }

                raw_municipality = pick(row, "municipality")
                municipality = municipality_code(raw_municipality)

                if len(samples) < 12:
                    samples.append(
                        f"{raw_municipality or 'vazio'} -> "
                        f"{municipality or 'vazio'}"
                    )

                try:
                    movement = int(float(pick(row, "movement")))
                except ValueError:
                    continue

                section = section_name(pick(row, "section"))
                sex = sex_name(pick(row, "sex"))

                if movement > 0:
                    country_totals[(section, sex)][0] += 1
                elif movement < 0:
                    country_totals[(section, sex)][1] += 1
                else:
                    continue

                if not valid_municipality_code(municipality):
                    continue

                cube_key = (municipality, section, sex)

                if movement > 0:
                    municipal_totals[cube_key][0] += 1
                else:
                    municipal_totals[cube_key][1] += 1

                if municipality in RA_ARACATUBA_CODES:
                    regional_key = (
                        municipality,
                        section,
                        sex,
                        age_band(pick(row, "age")),
                        pick(row, "education") or "Não informado",
                    )

                    if movement > 0:
                        regional_totals[regional_key][0] += 1
                    else:
                        regional_totals[regional_key][1] += 1

                matched += 1

        return (
            regional_totals,
            municipal_totals,
            country_totals,
            matched,
            headers,
            samples,
        )

    finally:
        if temporary_folder:
            shutil.rmtree(temporary_folder, ignore_errors=True)


def supabase_request(method, table, url, key, payload=None, query=""):
    """
    Executa uma chamada ao Supabase com repetição automática para
    429, 500, 502, 503, 504, falha de conexão e timeout.
    """
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }

    endpoint = f"{url}/rest/v1/{table}{query}"
    transient_statuses = {429, 500, 502, 503, 504}
    last_error = None

    for attempt in range(1, 8):
        try:
            response = requests.request(
                method,
                endpoint,
                headers=headers,
                json=payload,
                timeout=180,
            )

            if response.status_code not in transient_statuses:
                response.raise_for_status()
                return

            last_error = requests.HTTPError(
                f"{response.status_code} ao acessar {table}: "
                f"{response.text[:500]}",
                response=response,
            )

            retry_after = response.headers.get("Retry-After")

            wait = (
                int(retry_after)
                if retry_after and retry_after.isdigit()
                else min(60, 2 ** attempt)
            )

            print(
                f"Supabase respondeu {response.status_code} em {table}; "
                f"nova tentativa {attempt}/7 em {wait}s."
            )

        except (requests.Timeout, requests.ConnectionError) as error:
            last_error = error
            wait = min(60, 2 ** attempt)

            print(
                f"Falha temporária ao acessar {table}: {error}; "
                f"nova tentativa {attempt}/7 em {wait}s."
            )

        if attempt < 7:
            time.sleep(wait)

    raise RuntimeError(
        f"Supabase não respondeu após 7 tentativas em {table}: "
        f"{last_error}"
    ) from last_error


def aggregate(files):
    regional = defaultdict(lambda: [0, 0])
    municipal = defaultdict(lambda: [0, 0])
    country = defaultdict(lambda: [0, 0])
    matched = 0

    for source_file in files:
        (
            regional_file,
            municipal_file,
            country_file,
            count,
            _,
            _,
        ) = aggregate_file(source_file)

        for key, values in regional_file.items():
            regional[key][0] += values[0]
            regional[key][1] += values[1]

        for key, values in municipal_file.items():
            municipal[key][0] += values[0]
            municipal[key][1] += values[1]

        for key, values in country_file.items():
            country[key][0] += values[0]
            country[key][1] += values[1]

        matched += count

    return regional, municipal, country, matched


def cube_records(month, municipal_totals, country_totals):
    """Gera agregados por Brasil, UF e município."""
    states = defaultdict(lambda: [0, 0])
    records = []

    for (municipality, section, sex), values in municipal_totals.items():
        records.append(
            {
                "competence": month,
                "geography_level": "municipality",
                "geography_code": municipality,
                "cnae_section": section,
                "sex": sex,
                "admissions": values[0],
                "dismissals": values[1],
                "balance": values[0] - values[1],
            }
        )

        states[(municipality[:2], section, sex)][0] += values[0]
        states[(municipality[:2], section, sex)][1] += values[1]

    for (section, sex), values in country_totals.items():
        records.append(
            {
                "competence": month,
                "geography_level": "country",
                "geography_code": "BR",
                "cnae_section": section,
                "sex": sex,
                "admissions": values[0],
                "dismissals": values[1],
                "balance": values[0] - values[1],
            }
        )

    for (uf, section, sex), values in states.items():
        records.append(
            {
                "competence": month,
                "geography_level": "state",
                "geography_code": uf,
                "cnae_section": section,
                "sex": sex,
                "admissions": values[0],
                "dismissals": values[1],
                "balance": values[0] - values[1],
            }
        )

    return records


def hash_files(source_files):
    """Calcula o hash sem carregar arquivos grandes inteiros na memória."""
    digest = hashlib.sha256()

    for source_file in source_files:
        with source_file.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)

    return digest.hexdigest()


def import_data(
    competence,
    source_files,
    source_url,
    regional_totals,
    municipal_totals,
    country_totals,
    matched,
):
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not url or not key:
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
        for (
            municipality,
            section,
            sex,
            age,
            education,
        ), values in regional_totals.items()
    ]

    national_records = cube_records(
        month,
        municipal_totals,
        country_totals,
    )

    supabase_request(
        "DELETE",
        "caged_monthly",
        url,
        key,
        query=f"?competence=eq.{month}",
    )

    for index in range(0, len(records), 100):
        supabase_request(
            "POST",
            "caged_monthly",
            url,
            key,
            records[index:index + 100],
            "?on_conflict="
            "competence,ibge_code,cnae_section,sex,age_band,education",
        )

    supabase_request(
        "DELETE",
        "caged_movement_cube",
        url,
        key,
        query=f"?competence=eq.{month}",
    )

    for index in range(0, len(national_records), 100):
        supabase_request(
            "POST",
            "caged_movement_cube",
            url,
            key,
            national_records[index:index + 100],
            "?on_conflict="
            "competence,geography_level,geography_code,cnae_section,sex",
        )

    metadata = {
        "competence": month,
        "source_url": source_url,
        "source_sha256": hash_files(source_files),
        "rows_processed": matched,
        "status": "completed",
    }

    supabase_request(
        "POST",
        "caged_imports",
        url,
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
    parser.add_argument(
        "--file",
        required=True,
        action="append",
        help=(
            "Arquivo CAGEDMOV ou CAGEDFOR .zip, .7z ou .txt. "
            "Repita para combinar os dois."
        ),
    )
    parser.add_argument(
        "--source-url",
        help="URL pública da fonte.",
    )

    args = parser.parse_args()

    if not re.fullmatch(r"20\d{2}(0[1-9]|1[0-2])", args.competencia):
        parser.error("Use AAAAMM, por exemplo 202607.")

    source_files = [Path(value) for value in args.file]

    for source_file in source_files:
        if not source_file.is_file():
            parser.error(f"Arquivo não encontrado: {source_file}")

    (
        regional_totals,
        municipal_totals,
        country_totals,
        matched,
    ) = aggregate(source_files)

    if not matched:
        print(
            f"PULADO: {args.competencia}; "
            "nenhum registro válido foi encontrado."
        )
        return

    import_data(
        args.competencia,
        source_files,
        args.source_url or ", ".join(map(str, source_files)),
        regional_totals,
        municipal_totals,
        country_totals,
        matched,
    )

    print(
        f"Importação concluída: {args.competencia}; "
        f"{matched} movimentos; "
        f"{len(regional_totals)} agregados regionais; "
        f"{len(municipal_totals)} agregados municipais; "
        f"{len(country_totals)} agregados nacionais."
    )


if __name__ == "__main__":
    main()
