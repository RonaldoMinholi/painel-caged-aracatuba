#!/usr/bin/env python3
"""Importa somente os microdados da Região Administrativa de Araçatuba."""

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import unicodedata
import uuid
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
    "apprentice": ("indicadoraprendiz", "indicadortrabalhadoraprendiz", "aprendiz"),
    "intermittent": ("indicadortrabalhadorintermitente", "indicadortrabalhointermitente", "indtrabintermitente", "trabalhointermitente"),
    "temporary": ("indicadortrabalhadortemporario", "indicadortrabalhotemporario", "indtrabtemporario", "trabalhotemporario"),
    "foreigner_indicator": ("indicadortrabalhadoresestrangeiros", "indicadortrabalhadoresestrangeiro", "indicadortrabalhadoresestrangeira", "indicadortrabalhadoresestrang", "indicadortrabalhadoresestrangeiros"),
    "nationality": ("nacionalidade", "nacionalidadeimigrante"),
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


def yes_indicator(value):
    raw = clean(value)
    return raw in {"1", "s", "sim", "true", "yes"}


def foreigner(value):
    raw = clean(value)
    if not raw:
        return False
    if raw.isdigit():
        return raw not in {"10", "20"}
    return not any(term in raw for term in ("brasileir", "brasil"))


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
        "0": "Membros das forças armadas, policiais e bombeiros militares",
        "1": "Membros superiores do poder público, dirigentes de organizações de interesse público e de empresas",
        "2": "Profissionais das ciências e das artes",
        "3": "Técnicos de nível médio",
        "4": "Trabalhadores de serviços administrativos",
        "5": "Trabalhadores dos serviços, vendedores do comércio em lojas e mercados",
        "6": "Trabalhadores agropecuários, florestais e da pesca",
        "7": "Trabalhadores da produção de bens e serviços industriais (7)",
        "8": "Trabalhadores da produção de bens e serviços industriais (8)",
        "9": "Trabalhadores de manutenção e reparação",
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


def worker_header_fields(path):
    folder = None
    if path.suffix.lower() == ".txt":
        text_file = path
    else:
        folder = Path(tempfile.mkdtemp(prefix="cagedfor-"))
        text_file = extracted_text_file(path, folder)
    try:
        header = []
        for encoding in ("utf-8-sig", "latin1"):
            try:
                with text_file.open("r", encoding=encoding, newline="") as stream:
                    header = next(csv.reader(stream, delimiter=";"), [])
                break
            except UnicodeDecodeError:
                continue
        fields = [clean(name) for name in header]
        return [name for name in fields if any(term in name for term in ("estrang", "imigr", "nacion", "aprendiz", "intermit", "tempor"))]
    finally:
        if folder:
            shutil.rmtree(folder, ignore_errors=True)


PBI_REPORT_URL = "https://app.powerbi.com/view?r=eyJrIjoiNWI5NWI0ODEtYmZiYy00Mjg3LTkzNWUtY2UyYjIwMDE1YWI2IiwidCI6IjNlYzkyOTY5LTVhNTEtNGYxOC04YWM5LWVmOThmYmFmYTk3OCJ9"
PBI_FACT = "Dados - Movimentações"


def section_from_subclass(value):
    digits = re.sub(r"\D", "", str(value or "")).zfill(7)
    try:
        division = int(digits[:2])
    except ValueError:
        return "Não informado"
    ranges = (
        (1, 3, "A"), (5, 9, "B"), (10, 33, "C"), (35, 35, "D"),
        (36, 39, "E"), (41, 43, "F"), (45, 47, "G"), (49, 53, "H"),
        (55, 56, "I"), (58, 63, "J"), (64, 66, "K"), (68, 68, "L"),
        (69, 75, "M"), (77, 82, "N"), (84, 84, "O"), (85, 85, "P"),
        (86, 88, "Q"), (90, 93, "R"), (94, 96, "S"), (97, 98, "T"),
        (99, 99, "U"),
    )
    for start, end, section in ranges:
        if start <= division <= end:
            return section_name(section)
    return "Não informado"


def pbi_context():
    response = requests.get(PBI_REPORT_URL, timeout=60)
    response.raise_for_status()
    descriptor = re.search(r'resourceDescriptor = JSON\.parse\(\'([^\']+)\'\)', response.text)
    cluster = re.search(r"resolvedClusterUri = '([^']+)'", response.text)
    if not descriptor or not cluster:
        raise RuntimeError("Não foi possível identificar a base pública do Painel Novo Caged.")
    resource = json.loads(descriptor.group(1).replace(r'\"', '"'))
    api = cluster.group(1).replace("-redirect", "-api")
    headers = {
        "Accept": "application/json",
        "X-PowerBI-ResourceKey": resource["k"],
        "ActivityId": str(uuid.uuid4()),
        "RequestId": str(uuid.uuid4()),
    }
    models = requests.get(
        f"{api}public/reports/{resource['k']}/modelsAndExploration?preferReadOnlySession=true",
        headers=headers, timeout=90,
    )
    models.raise_for_status()
    model_id = models.json()["models"][0]["id"]
    return api, resource["k"], model_id


def pbi_column(source, property_name, name=None):
    return {
        "Column": {
            "Expression": {"SourceRef": {"Source": source}},
            "Property": property_name,
        },
        "Name": name or f"{source}.{property_name}",
    }


def pbi_sum(source, property_name):
    return {
        "Aggregation": {
            "Expression": pbi_column(source, property_name),
            "Function": 0,
            "Name": f"Sum({source}.{property_name})",
        }
    }


def pbi_where(source, property_name, values):
    return {
        "Condition": {
            "In": {
                "Expressions": [pbi_column(source, property_name)],
                "Values": [[{"Literal": {"Value": f"{value}L"}}] for value in values],
            }
        }
    }


def decode_pbi_rows(rows, width, value_dicts=None, dictionary_columns=None):
    # R marca colunas repetidas e Ø marca colunas nulas. DN aponta para um
    # dicionário de valores (por exemplo, D0 para códigos CBO). Sem esse
    # passo, o Power BI devolve o índice do dicionário, não o valor real.
    previous = [None] * width
    value_dicts = value_dicts or {}
    dictionary_columns = dictionary_columns or {}
    for row in rows:
        repeated = int(row.get("R", 0))
        nulls = int(row.get("Ø", 0))
        values = iter(row.get("C", []))
        current = []
        for index in range(width):
            bit = 1 << index
            if repeated & bit:
                value = previous[index]
            elif nulls & bit:
                value = None
            else:
                value = next(values, None)
                dictionary_name = dictionary_columns.get(index)
                dictionary = value_dicts.get(dictionary_name, ())
                if isinstance(value, int) and 0 <= value < len(dictionary):
                    value = dictionary[value]
            current.append(value)
        previous = current
        yield current


def pbi_age_band(value):
    codes = {
        "1": "Até 17 anos", "2": "18 a 24 anos", "3": "25 a 29 anos",
        "4": "30 a 39 anos", "5": "40 a 49 anos", "6": "50 a 64 anos",
        "7": "65 anos ou mais",
    }
    raw = str(value or "").strip()
    return codes.get(raw, age_band(value))


def pbi_education_name(value):
    codes = {
        "1": "Analfabeto", "2": "Fundamental Incompleto",
        "3": "Fundamental Completo", "4": "Médio Incompleto",
        "5": "Médio Completo", "6": "Superior Incompleto",
        "7": "Superior Completo",
    }
    raw = str(value or "").strip()
    return codes.get(raw, raw or "Não informado")


def powerbi_rows(api, resource_key, model_id, dimensions, competence, batch):
    source = "d"
    select = [pbi_column(source, item) for item in dimensions]
    select.extend((pbi_sum(source, "Admitidos"), pbi_sum(source, "Desligados")))
    command = {
        "SemanticQueryDataShapeCommand": {
            "Query": {
                "Version": 2,
                "From": [{"Name": source, "Entity": PBI_FACT, "Type": 0}],
                "Select": select,
                "Where": [
                    pbi_where(source, "competência", [competence]),
                    pbi_where(source, "município", batch),
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
    payload = {"version": "1.0.0", "queries": [{"Query": {"Commands": [command]}}], "modelId": model_id}
    response = requests.post(f"{api}public/reports/querydata?synchronous=true", headers=headers, json=payload, timeout=180)
    response.raise_for_status()
    data = response.json()["results"][0]["result"]["data"]
    dataset = data.get("dsr", {}).get("DS", [{}])[0]
    raw_rows = dataset.get("PH", [{}])[0].get("DM0", [])
    schema = raw_rows[0].get("S", []) if raw_rows else []
    dictionary_columns = {
        index: column["DN"] for index, column in enumerate(schema) if column.get("DN")
    }
    return decode_pbi_rows(raw_rows, len(select), dataset.get("ValueDicts", {}), dictionary_columns)


def powerbi_worker_totals(competence):
    api, resource_key, model_id = pbi_context()
    worker_dimensions = (
        "competência", "município", "subclasse", "sexo", "faixaetária",
        "graudeinstrução", "indicadoraprendiz", "indtrabintermitente",
        "indtrabtemp", "indestrangeiro",
    )
    occupation_dimensions = (
        "competência", "município", "cbo2002ocupação", "tempoemprego",
        "indicadoraprendiz", "indtrabintermitente", "indtrabtemp", "indestrangeiro",
    )
    totals = defaultdict(lambda: [0, 0])
    occupation_totals = defaultdict(lambda: [0, 0, 0.0])
    municipality_codes = list(RA_MUNICIPALITIES)

    for start in range(0, len(municipality_codes), 6):
        batch = municipality_codes[start:start + 6]
        for row in powerbi_rows(api, resource_key, model_id, worker_dimensions, competence, batch):
            month, code, subclass, sex, age, education, apprentice, intermittent, temporary, is_foreigner, admissions, dismissals = row
            code = municipality_code(code)
            if code not in RA_MUNICIPALITIES:
                continue
            key = (
                code, section_from_subclass(subclass), sex_name(sex), pbi_age_band(age),
                pbi_education_name(education), yes_indicator(apprentice),
                yes_indicator(intermittent), yes_indicator(temporary), yes_indicator(is_foreigner),
            )
            totals[key][0] += int(admissions or 0)
            totals[key][1] += int(dismissals or 0)

        for row in powerbi_rows(api, resource_key, model_id, occupation_dimensions, competence, batch):
            month, code, occupation, tenure, apprentice, intermittent, temporary, is_foreigner, admissions, dismissals = row
            code = municipality_code(code)
            occupation_name = occupation_group(occupation)
            if code not in RA_MUNICIPALITIES or not occupation_name:
                continue
            apprentice_flag = yes_indicator(apprentice)
            intermittent_flag = yes_indicator(intermittent)
            temporary_flag = yes_indicator(temporary)
            foreigner_flag = yes_indicator(is_foreigner)
            key = (code, occupation_name, apprentice_flag, intermittent_flag, temporary_flag, foreigner_flag)
            admissions, dismissals = int(admissions or 0), int(dismissals or 0)
            occupation_totals[key][0] += admissions
            occupation_totals[key][1] += dismissals
            try:
                occupation_totals[key][2] += float(tenure or 0) * dismissals
            except (TypeError, ValueError):
                pass

    if not totals:
        raise RuntimeError("A consulta pública do Novo Caged não retornou dados da Região Administrativa.")
    return totals, occupation_totals

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
            candidates = [name for name in reader.fieldnames if any(term in name for term in ("estrang", "imigr", "nacion", "aprendiz", "intermit", "tempor"))]
            print("CAMPOS_CAGED_TRABALHADOR:", ", ".join(candidates))
            if not {"municipio", "saldomovimentacao"}.issubset(reader.fieldnames):
                raise RuntimeError("Faltam as colunas município e saldo movimentação.")
            totals = defaultdict(lambda: [0, 0])
            group_totals = defaultdict(lambda: [0, 0, 0.0, 0])
            detail_totals = defaultdict(lambda: [0, 0, 0.0, 0])
            occupation_totals = defaultdict(lambda: [0, 0, 0.0, 0])
            worker_totals = defaultdict(lambda: [0, 0])
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
                worker_key = key + (
                    yes_indicator(pick(row, "apprentice")),
                    yes_indicator(pick(row, "intermittent")),
                    yes_indicator(pick(row, "temporary")),
                    yes_indicator(pick(row, "foreigner_indicator")) or foreigner(pick(row, "nationality"))
                )
                group = group_name(pick(row, "subclass"))
                group_key = (code, group)
                detail_key = (code, group, activity_name(group, pick(row, "section")))
                occupation = occupation_group(pick(row, "occupation"))
                occupation_key = (code, occupation) if occupation else None
                if movement > 0:
                    totals[key][0] += 1
                    worker_totals[worker_key][0] += 1
                    group_totals[group_key][0] += 1
                    detail_totals[detail_key][0] += 1
                    if occupation_key: occupation_totals[occupation_key][0] += 1
                else:
                    totals[key][1] += 1
                    worker_totals[worker_key][1] += 1
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
        return totals, group_totals, detail_totals, occupation_totals, worker_totals, matched
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


def import_data(competence, source_files, source_url, totals, group_totals, detail_totals, occupation_totals, worker_totals, worker_occupation_totals, matched):
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
    supabase_request("DELETE", "caged_worker_monthly", url, key, query=f"?competence=eq.{month}")
    worker_records = [
        {"competence": month, "ibge_code": code, "cnae_section": section, "sex": sex,
         "age_band": age, "education": education, "is_apprentice": apprentice,
         "is_intermittent": intermittent, "is_temporary": temporary, "is_foreigner": is_foreigner,
         "admissions": values[0], "dismissals": values[1], "balance": values[0] - values[1]}
        for (code, section, sex, age, education, apprentice, intermittent, temporary, is_foreigner), values in worker_totals.items()
    ]
    for index in range(0, len(worker_records), 100):
        supabase_request("POST", "caged_worker_monthly", url, key, worker_records[index:index + 100],
                         "?on_conflict=competence,ibge_code,cnae_section,sex,age_band,education,is_apprentice,is_intermittent,is_temporary,is_foreigner")
    supabase_request("DELETE", "caged_occupation_worker_monthly", url, key, query=f"?competence=eq.{month}")
    worker_occupation_records = [
        {"competence": month, "ibge_code": code, "occupation_group": occupation_group_name,
         "is_apprentice": apprentice, "is_intermittent": intermittent,
         "is_temporary": temporary, "is_foreigner": is_foreigner,
         "admissions": values[0], "dismissals": values[1], "balance": values[0] - values[1],
         "average_dismissal_tenure": (values[2] / values[1]) if values[1] else None}
        for (code, occupation_group_name, apprentice, intermittent, temporary, is_foreigner), values in worker_occupation_totals.items()
    ]
    for index in range(0, len(worker_occupation_records), 100):
        supabase_request("POST", "caged_occupation_worker_monthly", url, key, worker_occupation_records[index:index + 100],
                         "?on_conflict=competence,ibge_code,occupation_group,is_apprentice,is_intermittent,is_temporary,is_foreigner")
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
    worker_totals = defaultdict(lambda: [0, 0])
    matched = 0
    movement_files = [file for file in files if "CAGEDFOR" not in file.name.upper()]
    skipped = len(files) - len(movement_files)
    if skipped:
        print(f"Ignorando {skipped} arquivo(s) CAGEDFOR: a página setorial segue a série mensal sem ajustes do CAGED.")
        for source_file in files:
            if "CAGEDFOR" in source_file.name.upper():
                print("CAMPOS_CAGEDFOR_TRABALHADOR:", ", ".join(worker_header_fields(source_file)))
    for source_file in movement_files:
        partial, partial_groups, partial_details, partial_occupations, partial_workers, count = aggregate_file(source_file)
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
        for item, values in partial_workers.items():
            worker_totals[item][0] += values[0]
            worker_totals[item][1] += values[1]
        matched += count
    if not matched:
        print(f"PULADO: {args.competencia}; nenhum movimento regional foi encontrado.")
        return
    worker_totals, worker_occupation_totals = powerbi_worker_totals(args.competencia)
    print(f"Vínculos enriquecidos pela base oficial do Painel Novo Caged: {len(worker_totals)} agregados; {len(worker_occupation_totals)} ocupações filtradas.")
    import_data(args.competencia, movement_files, args.source_url or ", ".join(map(str, movement_files)), totals, group_totals, detail_totals, occupation_totals, worker_totals, worker_occupation_totals, matched)
    print(f"Importação regional concluída: {args.competencia}; {matched} movimentos; {len(totals)} agregados.")


if __name__ == "__main__":
    main()
