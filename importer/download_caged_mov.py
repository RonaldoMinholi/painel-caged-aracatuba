#!/usr/bin/env python3
"""Baixa CAGEDMOV e CAGEDFOR do Google Drive usando uma conta de serviço."""

import argparse
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

FOLDER_MIME = "application/vnd.google-apps.folder"
FILE_PATTERN = re.compile(r"^CAGED(MOV|FOR)(\d{6})\.(zip|7z|txt)$", re.IGNORECASE)
SCOPE = ["https://www.googleapis.com/auth/drive.readonly"]


def folder_id(value):
    if "/folders/" in value:
        return value.split("/folders/", 1)[1].split("/", 1)[0].split("?", 1)[0]
    query_id = parse_qs(urlparse(value).query).get("id", [None])[0]
    return query_id or value.strip()


def drive_service():
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        raise RuntimeError(
            "O secret GOOGLE_SERVICE_ACCOUNT_JSON não foi encontrado."
        )

    try:
        info = json.loads(raw)
        credentials = service_account.Credentials.from_service_account_info(
            info,
            scopes=SCOPE,
        )
    except Exception as error:
        raise RuntimeError(
            "GOOGLE_SERVICE_ACCOUNT_JSON não contém um JSON válido."
        ) from error

    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def list_files(service, parent_id):
    page_token = None

    while True:
        response = service.files().list(
            q=f"'{parent_id}' in parents and trashed = false",
            spaces="drive",
            fields="nextPageToken, files(id,name,mimeType)",
            pageToken=page_token,
            pageSize=1000,
            orderBy="name",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()

        yield from response.get("files", [])
        page_token = response.get("nextPageToken")

        if not page_token:
            return


def find_files(service, root_id, competencia, inicio, fim):
    found = []
    pending = [(root_id, Path())]

    while pending:
        current_id, relative_parent = pending.pop()

        for item in list_files(service, current_id):
            item_id = item["id"]
            name = item["name"]
            mime_type = item["mimeType"]

            if mime_type == FOLDER_MIME:
                pending.append((item_id, relative_parent / name))
                continue

            match = FILE_PATTERN.match(name)
            if not match:
                continue

            kind = match.group(1).upper()
            month = match.group(2)

            if competencia and month != competencia:
                continue
            if inicio and month < inicio:
                continue
            if fim and month > fim:
                continue

            found.append((month, kind, item_id, relative_parent / name))

    selected = []
    seen = set()

    for month, kind, item_id, relative_path in sorted(
        found,
        key=lambda item: str(item[3]),
    ):
        identity = (month, kind)

        if identity in seen:
            print(
                f"Arquivo CAGED{kind}{month} repetido; ignorando {relative_path}."
            )
            continue

        seen.add(identity)
        selected.append((month, kind, item_id, relative_path))

    return selected


def download_file(service, file_id, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)

    request = service.files().get_media(
        fileId=file_id,
        supportsAllDrives=True,
    )

    with destination.open("wb") as output:
        downloader = MediaIoBaseDownload(
            output,
            request,
            chunksize=16 * 1024 * 1024,
        )

        done = False

        while not done:
            status, done = downloader.next_chunk()
            if status:
                print(f"  {int(status.progress() * 100)}%")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--competencia")
    parser.add_argument("--inicio")
    parser.add_argument("--fim")
    args = parser.parse_args()

    for label, value in (
        ("--competencia", args.competencia),
        ("--inicio", args.inicio),
        ("--fim", args.fim),
    ):
        if value and not re.fullmatch(r"\d{6}", value):
            raise ValueError(f"{label} deve estar no formato AAAAMM.")

    if args.competencia and (args.inicio or args.fim):
        raise ValueError("Use --competencia ou --inicio/--fim; não os dois.")

    if args.inicio and args.fim and args.inicio > args.fim:
        raise ValueError("--inicio não pode ser posterior a --fim.")

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    service = drive_service()

    try:
        selected = find_files(
            service,
            folder_id(args.folder),
            args.competencia,
            args.inicio,
            args.fim,
        )
    except HttpError as error:
        raise RuntimeError(
            "Não foi possível listar o Drive. Confirme que a conta de serviço "
            "é Leitora da pasta principal."
        ) from error

    if not selected:
        raise RuntimeError(
            "Nenhum arquivo CAGEDMOV ou CAGEDFOR foi encontrado."
        )

    failures = []

    for month, kind, file_id, relative_path in selected:
        destination = output / relative_path
        print(f"Baixando CAGED{kind} {month}: {relative_path}")

        for attempt in range(1, 4):
            try:
                download_file(service, file_id, destination)
                break
            except (HttpError, OSError) as error:
                destination.unlink(missing_ok=True)
                print(f"Tentativa {attempt}/3 falhou: {error}")

                if attempt == 3:
                    failures.append(str(relative_path))
                else:
                    time.sleep(10 * attempt)

    failures_file = output / "caged-download-failures.txt"

    if failures:
        failures_file.write_text(
            "\n".join(failures) + "\n",
            encoding="utf-8",
        )
        print(f"Download parcial: {len(failures)} arquivo(s) falharam.")
    else:
        failures_file.unlink(missing_ok=True)
        print(
            f"Download concluído: {len(selected)} arquivo(s) "
            "CAGEDMOV/CAGEDFOR."
        )


if __name__ == "__main__":
    main()
