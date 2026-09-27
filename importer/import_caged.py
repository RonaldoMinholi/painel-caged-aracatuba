#!/usr/bin/env python3
"""Importa somente os microdados da Região Administrativa de Araçatuba."""

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

RA_MUNICIPALITIES = {
    "350110": "Alto Alegre", "350210": "Andradina", "350280": "Araçatuba",
    "350420": "Auriflama", "350440": "Avanhandava", "350510": "Barbosa",
    "350620": "Bento de Abreu", "350640": "Bilac", "350650": "Birigui",
    "350770": "Braúna", "350775": "Brejo Alegre", "350810": "Buritama",
    "351100": "Castilho", "351190": "Clementina", "351250": "Coroados",
    "351650": "Gabriel Monteiro", "351680": "Gastão Vidigal",
    "351690": "General Salgado", "351710": "Glicério", "351780": "Guaraçaí",
    "351820": "Guararapes", "351890": "Guzolândia", "352044": "Ilha Solteira",
    "352300": "Itapura", "352650": "Lavínia", "352725": "Lourdes",
    "352770": "Luiziânia", "353010": "Mirandópolis", "353210": "Murutinga do Sul",
    "353286": "Nova Castilho", "353320": "Nova Independência",
    "353330": "Nova Luzitânia", "353730": "Penápolis",
    "353740": "Pereira Barreto", "353770": "Piacatu", "354440": "Rubiácea",
    "354805": "Santo Antônio do Aracanguá", "354840": "Santópolis do Aguapeí",
    "354925": "São João de Iracema", "355230": "Sud Mennucci",
    "355255": "Suzanápolis", "355520": "Turiúba", "355630": "Valparaíso",
}

SECTIONS = {
    "A": "Agropecuária", "B": "Indústrias extrativas",
    "C": "Indústrias de transformação", "D": "Eletricidade e gás",
    "E": "Água, esgoto e gestão de resíduos", "F": "Construção",
    "G": "Comércio", "H": "Transporte, armazenagem e correio",
    "I": "Alojamento e alimentação", "J": "Informação e comunicação",
    "K": "Atividades financeiras e seguros", "L": "Atividades imobiliárias",
    "M": "Atividades profissionais, científicas e técnicas",
    "N": "Atividades administrativas e serviços complementares",
    "O": "Administração pública, defesa e seguridade social", "P": "Educação",
    "Q": "Saúde humana e serviços sociais", "R": "Artes, cultura, esporte e recreação",
    "S": "Outras atividades de serviços", "T": "Serviços domésticos",
    "U": "Organismos internacionais",
}
SEXES = {"1": "Masculino", "2": "Feminino", "3": "Feminino", "9": "Não informado"}
ALIASES = {
    "municipality": ("codigomunicipio", "codigoibgemunicipio", "ibgemunicipio", "municipio"),
    "movement": ("saldomovimentacao",),
    "section": ("cnae20secao", "secao"),
    "sex": ("sexo",),
    "age": ("idade",),
    "education": ("graudeinstrucao",),
    "subclass": ("subclasse", "cnae20subclasse", "cnae20subclas", "cnaesubclasse"),
    "tenure": ("tempoemprego", "tempoemprego"),
    "occupation": ("cbo2002ocupacao", "cbo2002", "ocupacao", "cboocupacao"),
}


def clean(value):
    normalized = unicodedata.normalize("NFKD", str(value))
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
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


def section_name(value):
    return SECTIONS.get(str(value or "").strip().upper(), "Não informado")


def group_name(value):
    digits = re.sub(r"\\D", "", str(value or ""))
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


def activity_name(group, section):
    if group == "Agropecuária":
        return "Agricultura, pecuária, produção florestal, pesca e aquicultura"
    if group == "Indústria":
        return "Indústria geral"
    if group == "Construção":
        return "Construção"
    if group == "Comércio":
        return "Comércio, reparação de veículos automotores e motocicletas"
    groups = {
        "H": "Transporte, armazenagem e correio",
        "I": "Alojamento e alimentação",
        "O": "Administração pública, defesa, seguridade social, educação, saúde humana e serviços sociais",
        "P": "Administração pública, defesa, seguridade social, educação, saúde humana e serviços sociais",
        "Q": "Administração pública, defesa, seguridade social, educação, saúde humana e serviços sociais",
        "J": "Informação, comunicação e atividades financeiras, imobiliárias, profissionais e administrativas",
        "K": "Informação, comunicação e atividades financeiras, imobiliárias, profissionais e administrativas",
        "L": "Informação, comunicação e atividades financeiras, imobiliárias, profissionais e administrativas",
        "M": "Informação, comunicação e atividades financeiras, imobiliárias, profissionais e administrativas",
        "N": "Informação, comunicação e atividades financeiras, imobiliárias, profissionais e administrativas",
    }
    return groups.get(str(section or "").strip().upper(), "Outros serviços")


def tenure_value(value):
    try:
        return float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def sex_name(value):
    raw = str(value or "").strip().upper()
    try:
        raw = str(int(float(raw)))
    except ValueError:
        pass
    names = {"M": "Masculino", "MASCULINO": "Masculino", "HOMEM": "Masculino",
             "F": "Feminino", "FEMININO": "Feminino", "MULHER": "Feminino"}
    return SEXES.get(raw, names.get(raw, "Não informado"))


def occupation_group(value):
    digits = re.sub(r"\\D", "", str(value or ""))
    labels = {
        "0": "Forças armadas, policiais e bombeiros militares",
        "1": "Membros superiores do poder público, dirigentes de organizações de interesse público e de empresas",
        "2": "Profissionais das ciências e das artes",
        "3": "Técnicos de nível médio",
        "4": "Trabalhadores de serviços administrativos",
        "5": "Trabalhadores dos serviços, vendedores do comércio em lojas e mercados",
        "6": "Trabalhadores agropecuários, florestais e da pesca",
        "7": "Trabalhadores da produção de bens e serviços industriais",
        "8": "Trabalhadores da produção de bens e serviços industriais",
        "9": "Trabalhadores em serviços de reparação e manutenção",
    }
    return labels.get(digits[:1]) if digits else None


def age_band(value):
    try:
        age = int(float(value))
    except (TypeError, ValueError):
        return "Não informado"
    if age <= 17: return "Até 17 anos"
    if age <= 24: return "18 a 24 anos"
    if age <= 29: return "25 a 29 anos"
    if age <= 39: return "30 a 39 anos"
    if age <= 49: return "40 a 49 anos"
    if age <= 64: return "50 a 64 anos"
    return "65 anos ou mais"


def extracted_text_file(path, folder):
    if path.suffix.lower() == ".txt":
        return path
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist() if name.lower().endswith(".txt")]
            if not names:
                raise RuntimeError("Nenhum TXT foi localizado dentro do ZIP.")
            name = max(names, key=lambda item: archive.getinfo(item).file_size)
            destination = folder / Path(name).name
            with archive.open(name) as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            return destination
    if path.suffix.lower() == ".7z":
        if not py7zr:
            raise RuntimeError("Arquivo .7z exige py7zr.")
        with py7zr.SevenZipFile(path, mode="r") as archive:
            archive.extractall(folder)
        candidates = list(folder.rglob("*.txt"))
        if not candidates:
            raise RuntimeError("Nenhum TXT foi localizado dentro do .7z.")
        return max(candidates, key=lambda item: item.stat().st_size)
    raise RuntimeError(f"Extensão não suportada: {path.suffix}")


def detect_encoding(text_file):
    sample = text_file.open("rb").read(131072)
    for encoding in ("utf-8-sig", "latin1"):
        try:
            header = sample.decode(encoding).splitlines()[0]
        except (UnicodeDecodeError, IndexError):
            continue
        fields = {clean(name) for name in header.split(";")}
        if {"municipio", "saldomovimentacao"}.issubset(fields):
            return encoding
    raise RuntimeError("Não foi possível reconhecer o cabeçalho do CAGED.")


def aggregate_file(path):
    folder = None
    if path.suffix.lower() == ".txt":
        text_file = path
    else:
        folder = Path(tempfile.mkdtemp(prefix="cagedmov-"))
        text_file = extracted_text_file(path, folder)
    try:
        with text_file.open("r", encoding=detect_encoding(text_file), newline="") as stream:
            sample = stream.read(131072)
            stream.seek(0)
            try:
                delimiter = csv.Sniffer().sniff(sample, delimiters=";|,\\t").delimiter
            except csv.Error:
                delimiter = ";"
            reader = csv.DictReader(stream, delimiter=delimiter)
            if not reader.fieldnames:
                raise RuntimeError("O TXT não possui cabeçalho legível.")
            reader.fieldnames = [clean(name) for name in reader.fieldnames]
            if not {"municipio", "saldomovimentacao"}.issubset(reader.fieldnames):
                raise RuntimeError("Faltam as colunas município e saldo movimentação.")
            totals = defaultdict(lambda: [0, 0])
            group_totals = defaultdict(lambda: [0, 0, 0.0, 0])
            detail_totals = defaultdict(lambda: [0, 0, 0.0, 0])
            occupation_totals = defaultdict(lambda: [0, 0, 0.0, 0])
            matched = 0
            for raw in reader:
                row = {clean(key): value for key, value in raw.items() if key is not None}
                code = municipality_code(pick(row, "municipality"))
                if code not in RA_MUNICIPALITIES:
                    continue
                try:
                    movement = int(float(pick(row, "movement")))
                except ValueError:
                    continue
                if movement == 0:
                    continue
                key = (code, section_name(pick(row, "section")), sex_name(pick(row, "sex")),
                       age_band(pick(row, "age")), pick(row, "education") or "Não informado")
                group = group_name(pick(row, "subclass"))
                group_key = (code, group)
                detail_key = (code, group, activity_name(group, pick(row, "section")))
                occupation = occupation_group(pick(row, "occupation"))
                occupation_key = (code, occupation) if occupation else None
                if movement > 0:
                    totals[key][0] += 1
                    group_totals[group_key][0] += 1
                    detail_totals[detail_key][0] += 1
                    if occupation_key: occupation_totals[occupation_key][0] += 1
                else:
                    totals[key][1] += 1
                    group_totals[group_key][1] += 1
                    detail_totals[detail_key][1] += 1
                    if occupation_key: occupation_totals[occupation_key][1] += 1
                    tenure = tenure_value(pick(row, "tenure"))
                    if tenure is not None and tenure >= 0:
                        group_totals[group_key][2] += tenure
                        group_totals[group_key][3] += 1
                        detail_totals[detail_key][2] += tenure
                        detail_totals[detail_key][3] += 1
                        if occupation_key:
                            occupation_totals[occupation_key][2] += tenure
                            occupation_totals[occupation_key][3] += 1
                matched += 1
        return totals, group_totals, detail_totals, occupation_totals, matched
    finally:
        if folder:
            shutil.rmtree(folder, ignore_errors=True)


def supabase_request(method, table, url, key, payload=None, query=""):
    headers = {"apikey": key, "Authorization": f"Bearer {key}",
               "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates"}
    endpoint = f"{url}/rest/v1/{table}{query}"
    last_error = None
    for attempt in range(1, 8):
        try:
            response = requests.request(method, endpoint, headers=headers, json=payload, timeout=180)
            if response.status_code not in {429, 500, 502, 503, 504}:
                response.raise_for_status()
                return
            last_error = RuntimeError(f"{response.status_code}: {response.text[:500]}")
        except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as error:
            last_error = error
        if attempt < 7:
            wait = min(60, 2 ** attempt)
            print(f"Falha temporária em {table}; nova tentativa em {wait}s.")
            time.sleep(wait)
    raise RuntimeError(f"Supabase não respondeu em {table}: {last_error}")


def hash_files(files):
    digest = hashlib.sha256()
    for source_file in files:
        with source_file.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    return digest.hexdigest()


def import_data(competence, source_files, source_url, totals, group_totals, detail_totals, occupation_totals, matched):
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("Defina SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY.")
    month = f"{competence[:4]}-{competence[4:]}-01"
    municipalities = [{"ibge_code": code, "name": name,
                       "territory": "Região Administrativa de Araçatuba", "is_regional": True}
                      for code, name in RA_MUNICIPALITIES.items()]
    supabase_request("POST", "municipalities", url, key, municipalities, "?on_conflict=ibge_code")
    supabase_request("DELETE", "caged_monthly", url, key, query=f"?competence=eq.{month}")
    records = [{"competence": month, "ibge_code": code, "cnae_section": section, "sex": sex,
                "age_band": age, "education": education, "admissions": values[0],
                "dismissals": values[1], "balance": values[0] - values[1]}
               for (code, section, sex, age, education), values in totals.items()]
    for index in range(0, len(records), 100):
        supabase_request("POST", "caged_monthly", url, key, records[index:index + 100],
                         "?on_conflict=competence,ibge_code,cnae_section,sex,age_band,education")
    supabase_request("DELETE", "caged_group_monthly", url, key, query=f"?competence=eq.{month}")
    group_records = [
        {"competence": month, "ibge_code": code, "group_name": group,
         "admissions": values[0], "dismissals": values[1],
         "balance": values[0] - values[1],
         "dismissal_tenure_sum": values[2],
         "dismissal_tenure_count": values[3]}
        for (code, group), values in group_totals.items()
    ]
    for index in range(0, len(group_records), 100):
        supabase_request("POST", "caged_group_monthly", url, key, group_records[index:index + 100],
                         "?on_conflict=competence,ibge_code,group_name")
    supabase_request("DELETE", "caged_group_detail_monthly", url, key, query=f"?competence=eq.{month}")
    detail_records = [
        {"competence": month, "ibge_code": code, "group_name": group, "activity_name": activity,
         "admissions": values[0], "dismissals": values[1], "balance": values[0] - values[1],
         "dismissal_tenure_sum": values[2], "dismissal_tenure_count": values[3]}
        for (code, group, activity), values in detail_totals.items()
    ]
    for index in range(0, len(detail_records), 100):
        supabase_request("POST", "caged_group_detail_monthly", url, key, detail_records[index:index + 100],
                         "?on_conflict=competence,ibge_code,group_name,activity_name")
    supabase_request("DELETE", "caged_occupation_monthly", url, key, query=f"?competence=eq.{month}")
    occupation_records = [
        {"competence": month, "ibge_code": code, "occupation_group": group,
         "admissions": values[0], "dismissals": values[1], "balance": values[0] - values[1],
         "dismissal_tenure_sum": values[2], "dismissal_tenure_count": values[3]}
        for (code, group), values in occupation_totals.items()
    ]
    for index in range(0, len(occupation_records), 100):
        supabase_request("POST", "caged_occupation_monthly", url, key, occupation_records[index:index + 100],
                         "?on_conflict=competence,ibge_code,occupation_group")
    metadata = {"competence": month, "source_url": source_url,
                "source_sha256": hash_files(source_files), "rows_processed": matched, "status": "completed"}
    supabase_request("POST", "caged_imports", url, key, metadata, "?on_conflict=competence")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--competencia", required=True, help="AAAAMM")
    parser.add_argument("--file", required=True, action="append",
                        help="Arquivo CAGEDMOV ou CAGEDFOR .zip, .7z ou .txt.")
    parser.add_argument("--source-url", help="URL pública da fonte.")
    args = parser.parse_args()
    if not re.fullmatch(r"20\d{2}(0[1-9]|1[0-2])", args.competencia):
        parser.error("Use AAAAMM, por exemplo 202607.")
    files = [Path(value) for value in args.file]
    for source_file in files:
        if not source_file.is_file():
            parser.error(f"Arquivo não encontrado: {source_file}")
    totals = defaultdict(lambda: [0, 0])
    group_totals = defaultdict(lambda: [0, 0, 0.0, 0])
    detail_totals = defaultdict(lambda: [0, 0, 0.0, 0])
    occupation_totals = defaultdict(lambda: [0, 0, 0.0, 0])
    matched = 0
    movement_files = [file for file in files if "CAGEDFOR" not in file.name.upper()]
    skipped = len(files) - len(movement_files)
    if skipped:
        print(f"Ignorando {skipped} arquivo(s) CAGEDFOR: a página setorial segue a série mensal sem ajustes do CAGED.")
    for source_file in movement_files:
        partial, partial_groups, partial_details, partial_occupations, count = aggregate_file(source_file)
        for item, values in partial.items():
            totals[item][0] += values[0]
            totals[item][1] += values[1]
        for item, values in partial_groups.items():
            group_totals[item][0] += values[0]
            group_totals[item][1] += values[1]
            group_totals[item][2] += values[2]
            group_totals[item][3] += values[3]
        for item, values in partial_details.items():
            detail_totals[item][0] += values[0]
            detail_totals[item][1] += values[1]
            detail_totals[item][2] += values[2]
            detail_totals[item][3] += values[3]
        for item, values in partial_occupations.items():
            occupation_totals[item][0] += values[0]
            occupation_totals[item][1] += values[1]
            occupation_totals[item][2] += values[2]
            occupation_totals[item][3] += values[3]
        matched += count
    if not matched:
        print(f"PULADO: {args.competencia}; nenhum movimento regional foi encontrado.")
        return
    import_data(args.competencia, movement_files, args.source_url or ", ".join(map(str, movement_files)), totals, group_totals, detail_totals, occupation_totals, matched)
    print(f"Importação regional concluída: {args.competencia}; {matched} movimentos; {len(totals)} agregados.")


if __name__ == "__main__":
    main()
