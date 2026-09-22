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
import time
from collections import defaultdict
from ftplib import FTP, all_errors
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

try:
    import py7zr
except ImportError:
    py7zr = None


# A Tabela 8.1 oficial usa os seis primeiros dígitos do código IBGE.
# Os microdados trazem sete dígitos; por isso ambos são normalizados para seis.
RA_ARACATUBA_CODES = {
    '350110', '350210', '350280', '350420', '350440', '350510', '350620',
    '350640', '350650', '350770', '350775', '350810', '351100', '351190',
    '351250', '351650', '351680', '351690', '351710', '351780', '351820',
    '351890', '352044', '352300', '352650', '352725', '352770', '353010',
    '353210', '353286', '353320', '353330', '353730', '353740', '353770',
    '354440', '354805', '354840', '354925', '355230', '355255', '355520',
    '355630',
}

SECTIONS = {
    'A': 'Agropecuária',
    'B': 'Indústrias extrativas',
    'C': 'Indústrias de transformação',
    'D': 'Eletricidade e gás',
    'E': 'Água, esgoto e gestão de resíduos',
    'F': 'Construção',
    'G': 'Comércio',
    'H': 'Transporte, armazenagem e correio',
    'I': 'Alojamento e alimentação',
    'J': 'Informação e comunicação',
    'K': 'Atividades financeiras e seguros',
    'L': 'Atividades imobiliárias',
    'M': 'Atividades profissionais, científicas e técnicas',
    'N': 'Atividades administrativas e serviços complementares',
    'O': 'Administração pública, defesa e seguridade social',
    'P': 'Educação',
    'Q': 'Saúde humana e serviços sociais',
    'R': 'Artes, cultura, esporte e recreação',
    'S': 'Outras atividades de serviços',
    'T': 'Serviços domésticos',
    'U': 'Organismos internacionais',
}

SEXES = {
    '1': 'Masculino',
    '2': 'Feminino',
    '3': 'Não informado',
    '9': 'Não informado',
}

ALIASES = {
    'municipality': ('codigomunicipio', 'codigo_municipio', 'municipio'),
    'movement': ('saldomovimentacao', 'saldo_movimentacao'),
    'section': ('cnae20secao', 'cnae_2_0_secao', 'secao'),
    'sex': ('sexo',),
    'age': ('idade',),
    'education': ('graudeinstrucao', 'grau_de_instrucao'),
}


def clean(value):
    return re.sub(r'[^a-z0-9]', '', str(value).lower())


def pick(row, key):
    for alias in ALIASES[key]:
        value = row.get(alias)
        if value not in (None, ''):
            return str(value).strip()
    return 'Não informado'


def municipality_code(value):
    """Normaliza o IBGE do microdado para seis dígitos."""
    raw = str(value or '').strip().split('.')[0]
    digits = re.sub(r'\D', '', raw)
    return digits[:6] if len(digits) >= 6 else ''


def section_name(value):
    code = str(value or '').strip().upper()
    return SECTIONS.get(code, 'Não informado')


def sex_name(value):
    return SEXES.get(str(value or '').strip(), 'Não informado')


def age_band(value):
    try:
        age = int(float(value))
    except (TypeError, ValueError):
        return 'Não informado'

    if age <= 17:
        return 'Até 17 anos'
    if age <= 24:
        return '18 a 24 anos'
    if age <= 29:
        return '25 a 29 anos'
    if age <= 39:
        return '30 a 39 anos'
    if age <= 49:
        return '40 a 49 anos'
    if age <= 64:
        return '50 a 64 anos'
    return '65 anos ou mais'


def candidate_urls(competence):
    year = competence[:4]
    filename = f'CAGEDMOV{competence}'
    extensions = ('.zip', '.7z', '.txt')

    official_ftp = f'ftp://ftp.mtps.gov.br/pdet/microdados/NOVO%20CAGED/{year}'
    official_https = f'https://ftp.mtps.gov.br/pdet/microdados/NOVO%20CAGED/{year}'

    configured = (os.getenv('CAGED_SOURCE_BASE_URL') or '').format(year=year).rstrip('/')
    bases = [official_ftp, official_https]

    if configured and configured not in bases:
        bases.append(configured)

    return [
        f'{base}/{filename}{extension}'
        for base in bases
        for extension in extensions
    ]


def download(competence):
    for url in candidate_urls(competence):
        for attempt in range(1, 4):
            try:
                suffix = Path(url).suffix
                destination = Path(tempfile.mkdtemp()) / f'caged{suffix}'

                if url.startswith('ftp://'):
                    parsed = urlparse(url)
                    directory, filename = os.path.split(unquote(parsed.path))

                    ftp = FTP()
                    ftp.connect(parsed.hostname, parsed.port or 21, timeout=45)
                    ftp.login()
                    ftp.set_pasv(True)

                    with destination.open('wb') as output:
                        ftp.retrbinary(
                            f'RETR {directory}/{filename}',
                            output.write,
                            blocksize=1024 * 1024,
                        )

                    ftp.quit()
                    return destination, url

                response = requests.get(url, stream=True, timeout=(30, 600))

                if response.status_code != 200:
                    print(f'Fonte indisponível ({response.status_code}): {url}')
                    shutil.rmtree(destination.parent, ignore_errors=True)
                    break

                with destination.open('wb') as output:
                    for part in response.iter_content(1024 * 1024):
                        if part:
                            output.write(part)

                return destination, url

            except all_errors + (requests.RequestException, OSError) as error:
                print(f'Tentativa {attempt}/3 falhou para {url}: {error}')
                shutil.rmtree(destination.parent, ignore_errors=True)

                if attempt < 3:
                    time.sleep(attempt * 20)

    raise FileNotFoundError(
        f'Competência {competence} ainda não encontrada na fonte oficial.'
    )


def text_stream(path):
    if path.suffix.lower() == '.txt':
        return io.TextIOWrapper(
            path.open('rb'),
            encoding='latin1',
            errors='replace',
        )

    if path.suffix.lower() == '.zip':
        import zipfile

        archive = zipfile.ZipFile(path)
        name = next(
            item for item in archive.namelist()
            if item.lower().endswith('.txt')
        )

        return io.TextIOWrapper(
            archive.open(name),
            encoding='latin1',
            errors='replace',
        )

    if path.suffix.lower() == '.7z' and py7zr:
        folder = path.parent / 'extract'

        with py7zr.SevenZipFile(path, mode='r') as archive:
            archive.extractall(folder)

        source_text = next(folder.rglob('*.txt'))

        return io.TextIOWrapper(
            source_text.open('rb'),
            encoding='latin1',
            errors='replace',
        )

    raise RuntimeError(
        'Arquivo .7z exige py7zr. Execute pip install -r importer/requirements.txt.'
    )


def aggregate(path):
    stream = text_stream(path)
    reader = csv.DictReader(stream, delimiter=';')
    reader.fieldnames = [clean(name) for name in reader.fieldnames]

    totals = defaultdict(lambda: [0, 0])
    matched = 0

    for raw in reader:
        row = {clean(key): value for key, value in raw.items()}

        municipality = municipality_code(pick(row, 'municipality'))

        if municipality not in RA_ARACATUBA_CODES:
            continue

        try:
            movement = int(float(pick(row, 'movement')))
        except ValueError:
            continue

        key = (
            municipality,
            section_name(pick(row, 'section')),
            sex_name(pick(row, 'sex')),
            age_band(pick(row, 'age')),
            pick(row, 'education'),
        )

        if movement > 0:
            totals[key][0] += 1
        elif movement < 0:
            totals[key][1] += 1

        matched += 1

    return totals, matched


def supabase_request(method, table, url, key, payload=None, query=''):
    headers = {
        'apikey': key,
        'Authorization': f'Bearer {key}',
        'Content-Type': 'application/json',
        'Prefer': 'resolution=merge-duplicates',
    }

    response = requests.request(
        method,
        f'{url}/rest/v1/{table}{query}',
        headers=headers,
        json=payload,
        timeout=120,
    )

    response.raise_for_status()


def import_data(competence, source_file, source_url, totals, matched):
    supabase_url = os.getenv('SUPABASE_URL')
    service_role_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

    if not supabase_url or not service_role_key:
        raise RuntimeError(
            'Defina SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY.'
        )

    month = f'{competence[:4]}-{competence[4:]}-01'

    records = [
        {
            'competence': month,
            'ibge_code': municipality,
            'cnae_section': section,
            'sex': sex,
            'age_band': age,
            'education': education,
            'admissions': values[0],
            'dismissals': values[1],
            'balance': values[0] - values[1],
        }
        for (municipality, section, sex, age, education), values in totals.items()
    ]

    supabase_request(
        'DELETE',
        'caged_monthly',
        supabase_url,
        service_role_key,
        query=f'?competence=eq.{month}',
    )

    for index in range(0, len(records), 500):
        supabase_request(
            'POST',
            'caged_monthly',
            supabase_url,
            service_role_key,
            records[index:index + 500],
            '?on_conflict=competence,ibge_code,cnae_section,sex,age_band,education',
        )

    digest = hashlib.sha256(source_file.read_bytes()).hexdigest()

    metadata = {
        'competence': month,
        'source_url': source_url,
        'source_sha256': digest,
        'rows_processed': matched,
        'status': 'completed',
    }

    supabase_request(
        'POST',
        'caged_imports',
        supabase_url,
        service_role_key,
        metadata,
        '?on_conflict=competence',
    )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        '--competencia',
        required=True,
        help='AAAAMM',
    )

    parser.add_argument(
        '--file',
        help='Arquivo .zip, .7z ou .txt já baixado.',
    )

    parser.add_argument(
        '--source-url',
        help='URL pública da fonte do arquivo local.',
    )

    arguments = parser.parse_args()

    if not re.fullmatch(r'20\d{2}(0[1-9]|1[0-2])', arguments.competencia):
        parser.error('Use AAAAMM, por exemplo 202606.')

    temporary_folder = None

    if arguments.file:
        source_file = Path(arguments.file)

        if not source_file.is_file():
            parser.error(f'Arquivo não encontrado: {source_file}')

        source_url = arguments.source_url or str(source_file)

    else:
        source_file, source_url = download(arguments.competencia)
        temporary_folder = source_file.parent

    try:
        totals, matched = aggregate(source_file)

        if not matched:
            raise RuntimeError(
                'Nenhum registro dos 43 municípios da Região Administrativa '
                'de Araçatuba encontrado; verifique o layout do arquivo.'
            )

        import_data(
            arguments.competencia,
            source_file,
            source_url,
            totals,
            matched,
        )

        print(
            f'Importação concluída: {arguments.competencia}; '
            f'{matched} movimentos; {len(totals)} agregados.'
        )

    finally:
        if temporary_folder:
            shutil.rmtree(temporary_folder, ignore_errors=True)


if __name__ == '__main__':
    main()
