#!/usr/bin/env python3
"""
fetch_spotify_playlist.py - Extractor de playlists públicas de Spotify sin cuenta Premium ni OAuth.

Utiliza la librería no oficial spotifyscraper (endpoint GraphQL del reproductor web)
para leer playlists públicas de Spotify paginando de 100 en 100 sin requerir registro
en el Developer Dashboard ni credenciales de API, y guarda el resultado en playlist_data.json.

Licencia: MIT
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
from pathlib import Path
import sys
import time
from typing import Any

from api._shared import (
    extract_and_validate_playlist_id,
    fetch_spotify_playlist_page_stateless,
    sanitize_error_message,
)

DEFAULT_OUTPUT_FILE = "playlist_data.json"
DEFAULT_LOG_FILE = "fetch_spotify.log"
PAGE_LIMIT = 100
POLITE_DELAY_SECONDS = 0.35


def setup_logging(log_file: str) -> logging.Logger:
    logger = logging.getLogger("spotify_fetcher")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    return logger


def fetch_full_playlist(
    playlist_url: str,
    logger: logging.Logger,
    max_tracks: int | None = None,
) -> dict[str, Any]:
    """
    Descarga todas las canciones de una playlist pública de Spotify paginando de 100 en 100
    con una pausa cortés entre páginas para evitar bloqueos.
    """
    playlist_id = extract_and_validate_playlist_id(playlist_url)
    logger.info("Consultando playlist pública de Spotify (ID: %s)...", playlist_id)

    all_tracks: list[dict[str, Any]] = []
    offset = 0
    playlist_name = f"Playlist {playlist_id}"
    playlist_description = ""
    owner_name = "Spotify"
    cover_url = None
    total_reported = 0

    while True:
        page = fetch_spotify_playlist_page_stateless(
            playlist_id=playlist_id,
            offset=offset,
            limit=PAGE_LIMIT,
        )
        if offset == 0:
            playlist_name = page["name"]
            playlist_description = page["description"]
            owner_name = page["owner"]
            cover_url = page["cover_url"]
            total_reported = page["total"]
            logger.info(
                "Playlist encontrada: '%s' (por %s) | Total reportado: %d canciones",
                playlist_name,
                owner_name,
                total_reported,
            )

        page_tracks = page.get("tracks") or []
        for tr in page_tracks:
            tr["index"] = len(all_tracks)
            all_tracks.append(tr)
            if max_tracks is not None and len(all_tracks) >= max_tracks:
                break

        logger.info(
            "Descargando metadatos: %d / %d canciones...",
            len(all_tracks),
            total_reported or len(all_tracks),
        )

        if max_tracks is not None and len(all_tracks) >= max_tracks:
            break

        if not page.get("has_next") or page.get("next_offset") is None:
            break

        offset = int(page["next_offset"])
        time.sleep(POLITE_DELAY_SECONDS)

    return {
        "schema_version": "2.0",
        "extracted_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "playlist_id": playlist_id,
        "playlist_name": playlist_name,
        "playlist_description": playlist_description,
        "playlist_url": playlist_url.strip(),
        "owner": {"display_name": owner_name},
        "cover_url": cover_url,
        "total_tracks_reported": total_reported,
        "total_tracks": len(all_tracks),
        "tracks": all_tracks,
    }


def save_playlist_json(data: dict[str, Any], output_path: str) -> None:
    target = Path(output_path)
    temp_target = target.with_suffix(target.suffix + ".tmp")
    with open(temp_target, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    temp_target.replace(target)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Extrae las canciones de una playlist pública de Spotify usando spotifyscraper "
            "(sin requerir cuenta Premium ni credenciales de API) y genera playlist_data.json."
        ),
    )
    parser.add_argument(
        "playlist_url",
        nargs="?",
        help="URL HTTPS de la playlist pública de Spotify (ej. https://open.spotify.com/playlist/...)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=DEFAULT_OUTPUT_FILE,
        help=f"Archivo JSON de salida (por defecto: {DEFAULT_OUTPUT_FILE})",
    )
    parser.add_argument(
        "--max-tracks",
        type=int,
        default=None,
        help="Límite opcional de canciones a descargar.",
    )
    parser.add_argument(
        "--log-file",
        default=DEFAULT_LOG_FILE,
        help=f"Archivo de registro (por defecto: {DEFAULT_LOG_FILE})",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    logger = setup_logging(args.log_file)

    playlist_url = args.playlist_url
    if not playlist_url:
        try:
            playlist_url = input(
                "Introduce el enlace HTTPS de la playlist pública de Spotify: "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            logger.error("Operación cancelada por el usuario.")
            return 1

    try:
        data = fetch_full_playlist(
            playlist_url=playlist_url,
            logger=logger,
            max_tracks=args.max_tracks,
        )
        save_playlist_json(data, args.output)
    except (ValueError, LookupError, RuntimeError) as exc:
        logger.error("%s", sanitize_error_message(str(exc)))
        return 1
    except KeyboardInterrupt:
        logger.warning("Descarga interrumpida por el usuario.")
        return 130
    except Exception as exc:
        logger.error("Error inesperado: %s", sanitize_error_message(str(exc)))
        return 1

    logger.info(
        "Extracción completada: %d canciones guardadas en '%s'.",
        data["total_tracks"],
        args.output,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

