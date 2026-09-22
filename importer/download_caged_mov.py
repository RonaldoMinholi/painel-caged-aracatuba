#!/usr/bin/env python3
"""Lista uma pasta pública do Google Drive e baixa apenas CAGEDMOVAAAAMM."""

import argparse
import re
from pathlib import Path

import gdown


MOV_PATTERN = re.compile(r"^CAGEDMOV(\d{6})\.(zip|7z|txt)$", re.IGNORECASE)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", required=True, help="URL pública da pasta raiz no Google Drive")
    parser.add_argument("--output", required=True, help="Pasta local de destino")
    parser.add_argument("--competencia", help="AAAAMM opcional; baixa apenas esse mês")
    args = parser.parse_args()

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    files = gdown.download_folder(
        url=args.folder,
        output=str(output),
        quiet=False,
        remaining_ok=True,
        skip_download=True,
    )
    if not files:
        raise RuntimeError("Não foi possível listar os arquivos da pasta do Google Drive.")

    selected = []
    seen = set()

    for item in files:
        name = Path(item.path).name
        match = MOV_PATTERN.match(name)

        if not match:
            continue

        competencia = match.group(1)

        if args.competencia and competencia != args.competencia:
            continue

        if competencia in seen:
            print(f"Competência {competencia} repetida; ignorando {item.path}.")
            continue

        seen.add(competencia)
        selected.append(item)

    if not selected:
        suffix = f" para a competência {args.competencia}" if args.competencia else ""
        raise RuntimeError(f"Nenhum arquivo CAGEDMOVAAAAMM encontrado{suffix}.")

    for item in sorted(selected, key=lambda value: value.path):
        destination = output / item.path
        destination.parent.mkdir(parents=True, exist_ok=True)

        print(f"Baixando apenas microdado de movimentação: {item.path}")

        result = gdown.download(
            url=f"https://drive.google.com/uc?id={item.id}",
            output=str(destination),
            quiet=False,
            resume=True,
        )

        if result is None:
            raise RuntimeError(f"Falha ao baixar {item.path}.")

    print(f"Download seletivo concluído: {len(selected)} arquivo(s) CAGEDMOV.")


if __name__ == "__main__":
    main()
