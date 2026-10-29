#!/usr/bin/env python3
"""
upload_ytmusic.py - Migrador de playlists a YouTube Music con soporte de reanudación.

Lee el archivo JSON generado por fetch_spotify_playlist.py, gestiona un archivo de estado
(upload_state.json) para permitir migraciones multi-sesión de playlists grandes
(>4.000 canciones) respetando límites de cuota y tasa, y crea/actualiza la playlist
en YouTube Music mediante autenticación por navegador (ytmusicapi).

Licencia: MIT
"""

from __future__ import annotations

import argparse
import datetime
import difflib
import json
import logging
import os
import re
import stat
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import requests
import ytmusicapi
from ytmusicapi import YTMusic
from ytmusicapi.helpers import get_authorization, sapisid_from_cookie

DEFAULT_INPUT_FILE = "playlist_data.json"
DEFAULT_STATE_FILE = "upload_state.json"
DEFAULT_AUTH_FILE = "browser.json"
DEFAULT_LOG_FILE = "upload_ytmusic.log"
DEFAULT_UNMATCHED_LOG_FILE = "unmatched_tracks.log"

QUOTA_DAILY_SAFE_LIMIT = 9500
QUOTA_COST_CREATE_PLAYLIST = 50
QUOTA_COST_ADD_ITEM = 50
MIN_SLEEP_SECONDS = 0.5
DEFAULT_SLEEP_SECONDS = 1.0
MAX_API_RETRIES = 4


class SecretScrubbingFilter(logging.Filter):
    """Filtro de logging que oculta cookies, cabeceras SAPISIDHASH y tokens."""

    def __init__(self, secrets: list[str] | None = None) -> None:
        super().__init__()
        self.secrets = [s for s in (secrets or []) if s and len(s) >= 6]
        self._cookie_re = re.compile(
            r"(__Secure-3PAPISID|SAPISID|HSID|SSID|APISID|SID|LOGIN_INFO)=[^;\s\"']+",
            re.IGNORECASE,
        )
        self._sapisidhash_re = re.compile(
            r"(SAPISIDHASH\s+)[A-Za-z0-9_]+",
            re.IGNORECASE,
        )
        self._bearer_re = re.compile(
            r"(Bearer\s+)[A-Za-z0-9\-._~+/]+=*",
            re.IGNORECASE,
        )

    def sanitize(self, text: str) -> str:
        if not text:
            return text
        sanitized = self._cookie_re.sub(r"\1=[REDACTED_COOKIE]", text)
        sanitized = self._sapisidhash_re.sub(r"\1[REDACTED_HASH]", text)
        sanitized = self._bearer_re.sub(r"\1[REDACTED_TOKEN]", text)
        for secret in self.secrets:
            if secret in sanitized:
                sanitized = sanitized.replace(secret, "[REDACTED_SECRET]")
        return sanitized

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self.sanitize(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: self.sanitize(v) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    self.sanitize(a) if isinstance(a, str) else a for a in record.args
                )
        return True


def enforce_secure_file_permissions(filepath: str | Path) -> None:
    """Aplica permisos 0o600 para que solo el propietario pueda leer/escribir el archivo."""
    path = Path(filepath)
    if not path.exists():
        return
    try:
        if os.name == "posix":
            os.chmod(path, 0o600)
        else:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError as exc:
        logging.getLogger(__name__).warning(
            "No se pudieron aplicar permisos restrictivos a %s: %s",
            path.name,
            exc.strerror or "error de sistema",
        )


def setup_logging(
    log_file: str,
    unmatched_log_file: str,
    secrets: list[str],
) -> tuple[logging.Logger, logging.Logger, SecretScrubbingFilter]:
    """Configura el logger principal y el logger específico de canciones no encontradas/baja confianza."""
    scrubber = SecretScrubbingFilter(secrets=secrets)
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    main_logger = logging.getLogger("ytmusic_uploader")
    main_logger.setLevel(logging.INFO)
    main_logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(scrubber)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.addFilter(scrubber)

    main_logger.addHandler(console_handler)
    main_logger.addHandler(file_handler)
    enforce_secure_file_permissions(log_file)

    unmatched_logger = logging.getLogger("ytmusic_unmatched")
    unmatched_logger.setLevel(logging.INFO)
    unmatched_logger.handlers.clear()
    unmatched_logger.propagate = False

    unmatched_handler = logging.FileHandler(unmatched_log_file, encoding="utf-8")
    unmatched_handler.setFormatter(formatter)
    unmatched_handler.addFilter(scrubber)
    unmatched_logger.addHandler(unmatched_handler)
    enforce_secure_file_permissions(unmatched_log_file)

    return main_logger, unmatched_logger, scrubber


def build_browser_auth_from_cookie(
    cookie_str: str,
    auth_filepath: str,
    user_agent: str,
) -> str:
    """
    Construye un archivo browser.json compatible con ytmusicapi a partir de la cadena
    de Cookie proporcionada en variables de entorno y aplica permisos 0o600.
    Incluye la cabecera Authorization SAPISIDHASH requerida por ytmusicapi.
    """
    if "__Secure-3PAPISID" not in cookie_str:
        raise ValueError(
            "La cadena de cookie proporcionada en YTMUSIC_COOKIE no contiene '__Secure-3PAPISID'. "
            "Asegúrese de haber iniciado sesión en https://music.youtube.com en una ventana de incógnito "
            "y copiar la cabecera Cookie completa de una petición '/browse'."
        )

    match = re.search(r"__Secure-3PAPISID=([^;\s]+)", cookie_str)
    sapisid = match.group(1).strip() if match else sapisid_from_cookie(cookie_str)
    origin = "https://music.youtube.com"
    auth_header = get_authorization(f"{sapisid} {origin}")

    headers_raw = (
        f"Accept: */*\n"
        f"Accept-Language: es-ES,es;q=0.9,en;q=0.8\n"
        f"Authorization: {auth_header}\n"
        f"Content-Type: application/json\n"
        f"X-Goog-AuthUser: 0\n"
        f"x-origin: {origin}\n"
        f"User-Agent: {user_agent}\n"
        f"Cookie: {cookie_str.strip()}\n"
    )

    ytmusicapi.setup(filepath=auth_filepath, headers_raw=headers_raw)
    enforce_secure_file_permissions(auth_filepath)
    return auth_filepath


def validate_browser_auth_file(auth_filepath: str) -> list[str]:
    """
    Verifica que el archivo browser.json exista, tenga permisos 0o600 y contenga
    la cookie __Secure-3PAPISID requerida por ytmusicapi.
    Devuelve una lista de valores sensibles para ocultar en los logs.
    """
    path = Path(auth_filepath)
    if not path.exists():
        raise FileNotFoundError(
            f"No se encontró el archivo de autenticación '{auth_filepath}' ni la variable "
            "YTMUSIC_COOKIE en .env.\n"
            "Consulte el README.md (Sección Configuración de YouTube Music) para generar 'browser.json'."
        )

    enforce_secure_file_permissions(path)

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"El archivo '{auth_filepath}' no tiene un formato JSON válido: {exc}"
        ) from None

    if not isinstance(data, dict):
        raise ValueError(f"El archivo '{auth_filepath}' debe contener un objeto JSON de cabeceras.")

    cookie_val = ""
    for k, v in data.items():
        if k.lower() == "cookie" and isinstance(v, str):
            cookie_val = v
            break

    if not cookie_val or "__Secure-3PAPISID" not in cookie_val:
        raise ValueError(
            f"El archivo '{auth_filepath}' no contiene una cabecera 'cookie' válida con '__Secure-3PAPISID'. "
            "Por favor regenere browser.json desde una sesión activa en music.youtube.com."
        )

    secrets = [cookie_val]
    auth_header = data.get("authorization") or data.get("Authorization")
    if isinstance(auth_header, str) and auth_header:
        secrets.append(auth_header)

    return secrets


def create_ytmusic_client(auth_filepath: str) -> YTMusic:
    """Inicializa el cliente YTMusic y verifica que utilice HTTPS."""
    yt = YTMusic(auth=auth_filepath)
    # Verificar que las llamadas a la API utilicen HTTPS
    base_url = getattr(yt, "base_url", "https://music.youtube.com/youtubei/v1/")
    if isinstance(base_url, str) and not base_url.startswith("https://"):
        raise RuntimeError("Error de seguridad: El cliente de YouTube Music no utiliza HTTPS.")
    return yt


def load_playlist_data(input_path: str) -> dict[str, Any]:
    """Lee y valida la estructura del archivo JSON generado por fetch_spotify_playlist.py."""
    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(
            f"No se encontró el archivo de entrada '{input_path}'. "
            "Ejecute primero fetch_spotify_playlist.py para generar el archivo de datos."
        )

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict) or "tracks" not in data or not isinstance(data["tracks"], list):
        raise ValueError(
            f"El archivo '{input_path}' no contiene una estructura válida de playlist ('tracks' ausente)."
        )

    return data


def load_or_init_state(
    state_path: str,
    playlist_data: dict[str, Any],
    target_title: str | None = None,
) -> dict[str, Any]:
    """Carga el archivo de estado existente o inicializa uno nuevo si no existe."""
    path = Path(state_path)
    source_id = playlist_data.get("playlist_id") or "unknown"
    source_name = playlist_data.get("playlist_name") or "Spotify Playlist"
    default_yt_title = target_title or f"{source_name} (Spotify)"

    if path.exists():
        enforce_secure_file_permissions(path)
        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f)
        if not isinstance(state, dict):
            raise ValueError(f"El archivo de estado '{state_path}' está corrupto.")

        state.setdefault("source_playlist_id", source_id)
        state.setdefault("source_playlist_name", source_name)
        state.setdefault("yt_playlist_id", None)
        state.setdefault("yt_playlist_title", default_yt_title)
        state.setdefault("created_at", datetime.datetime.now(datetime.timezone.utc).isoformat())
        state.setdefault("updated_at", datetime.datetime.now(datetime.timezone.utc).isoformat())
        state.setdefault("total_tracks_in_source", len(playlist_data.get("tracks", [])))
        state.setdefault("processed_indices", [])
        state.setdefault("processed_track_keys", [])
        state.setdefault("added_video_ids", [])
        state.setdefault("failed_tracks", [])
        state.setdefault("estimated_quota_used_last_run", 0)
        return state

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return {
        "source_playlist_id": source_id,
        "source_playlist_name": source_name,
        "yt_playlist_id": None,
        "yt_playlist_title": default_yt_title,
        "created_at": now_iso,
        "updated_at": now_iso,
        "total_tracks_in_source": len(playlist_data.get("tracks", [])),
        "processed_indices": [],
        "processed_track_keys": [],
        "added_video_ids": [],
        "failed_tracks": [],
        "estimated_quota_used_last_run": 0,
    }


def save_state(state: dict[str, Any], state_path: str) -> None:
    """Guarda el estado de migración de manera atómica y aplica permisos 0o600."""
    state["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    target = Path(state_path)
    temp_target = target.with_suffix(target.suffix + ".tmp")

    with open(temp_target, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    temp_target.replace(target)
    enforce_secure_file_permissions(target)


def get_track_key(track: dict[str, Any], fallback_index: int) -> str:
    """Obtiene un identificador único estable para una canción dentro del estado."""
    uri = track.get("spotify_uri")
    if uri and isinstance(uri, str):
        return f"{fallback_index}:{uri}"
    sp_id = track.get("spotify_id")
    if sp_id and isinstance(sp_id, str):
        return f"{fallback_index}:spotify:track:{sp_id}"
    title = (track.get("title") or "").strip().lower()
    artist = (track.get("artist") or "").strip().lower()
    return f"{fallback_index}:{title}::{artist}"


def normalize_text(text: str) -> str:
    """Normaliza cadenas para comparación de similitud entre Spotify y YouTube Music."""
    text = text.lower()
    text = re.sub(r"\((?:feat\.?|ft\.?|with|prod\.?|remaster(?:ed)?|live|version)[^)]*\)", "", text)
    text = re.sub(r"\[(?:feat\.?|ft\.?|with|prod\.?|remaster(?:ed)?|live|version)[^\]]*\]", "", text)
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def score_candidate(track: dict[str, Any], candidate: dict[str, Any]) -> float:
    """
    Calcula una puntuación de confianza (0.0 a 1.0) comparando título, artista y duración
    entre la pista de Spotify y un resultado de búsqueda de YouTube Music.
    """
    target_title = normalize_text(track.get("title") or "")
    target_artist = normalize_text(track.get("artist") or "")

    cand_title = normalize_text(candidate.get("title") or "")
    cand_artists_raw = candidate.get("artists") or []
    cand_artists = [
        normalize_text(a.get("name") or "")
        for a in cand_artists_raw
        if isinstance(a, dict) and a.get("name")
    ]
    cand_artist_joined = " ".join(cand_artists)

    title_ratio = difflib.SequenceMatcher(None, target_title, cand_title).ratio()
    if target_title and cand_title and (target_title in cand_title or cand_title in target_title):
        title_ratio = max(title_ratio, 0.88)

    artist_ratio = 0.0
    if target_artist and cand_artists:
        best_single = max(
            difflib.SequenceMatcher(None, target_artist, ca).ratio() for ca in cand_artists
        )
        in_joined = 0.9 if target_artist in cand_artist_joined else 0.0
        artist_ratio = max(best_single, in_joined)

    score = (title_ratio * 0.65) + (artist_ratio * 0.35)

    # Ajuste por diferencia de duración si ambos datos están presentes
    target_duration_s = (track.get("duration_ms") or 0) / 1000.0
    cand_duration_s = candidate.get("duration_seconds")
    if target_duration_s > 0 and isinstance(cand_duration_s, (int, float)) and cand_duration_s > 0:
        diff = abs(target_duration_s - cand_duration_s)
        if diff <= 5:
            score = min(1.0, score + 0.05)
        elif diff > 30:
            score = max(0.0, score - 0.15)

    return round(score, 3)


def select_best_match(
    track: dict[str, Any],
    search_results: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, float]:
    """
    Selecciona el mejor resultado que tenga videoId válido y devuelve (resultado, confianza).
    Prioriza el primer resultado válido salvo que un resultado posterior tenga mucha mayor similitud.
    """
    valid_candidates = [
        r for r in (search_results or []) if isinstance(r, dict) and r.get("videoId")
    ]
    if not valid_candidates:
        return None, 0.0

    best_candidate = valid_candidates[0]
    best_score = score_candidate(track, best_candidate)

    for candidate in valid_candidates[1:5]:
        cand_score = score_candidate(track, candidate)
        if cand_score > best_score + 0.12:
            best_candidate = candidate
            best_score = cand_score

    return best_candidate, best_score


def is_quota_or_rate_limit_error(exc: Exception) -> bool:
    """Detecta si una excepción corresponde a un error de cuota agotada (HTTP 403 quotaExceeded) o bloqueo."""
    msg = str(exc).lower()
    quota_keywords = (
        "quotaexceeded",
        "quota exceeded",
        "dailylimitexceeded",
        "rate_limit_exceeded",
        "resource_exhausted",
        "too many requests",
        "http 403",
        "status code 403",
        "403 forbidden",
        "http 429",
        "status code 429",
    )
    return any(keyword in msg for keyword in quota_keywords)


class QuotaExceededStop(Exception):
    """Excepción interna para detener limpiamente la migración cuando se agota la cuota."""


def call_ytmusic_safely(
    func: Any,
    logger: logging.Logger,
    scrubber: SecretScrubbingFilter,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """
    Ejecuta una operación en ytmusicapi con manejo de errores de red, límite de tasa
    y detección explícita de cuota excedida (HTTP 403 / quotaExceeded).
    """
    for attempt in range(1, MAX_API_RETRIES + 1):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            clean_err = scrubber.sanitize(str(exc))
            if is_quota_or_rate_limit_error(exc):
                raise QuotaExceededStop(
                    f"Se detectó límite de cuota o tasa en YouTube Music (403/429 quotaExceeded): {clean_err}"
                ) from None

            if isinstance(exc, requests.RequestException) and attempt < MAX_API_RETRIES:
                wait_s = 2 ** attempt
                logger.warning(
                    "Error temporal de red con YouTube Music. Reintentando en %d s (%d/%d)...",
                    wait_s,
                    attempt,
                    MAX_API_RETRIES,
                )
                time.sleep(wait_s)
                continue

            raise RuntimeError(f"Error en llamada a YouTube Music: {clean_err}") from None

    raise RuntimeError("Se agotaron los reintentos de conexión con YouTube Music.")


def sanitize_playlist_title(title: str) -> str:
    """Limpia caracteres no permitidos por YouTube (< y >) y trunca a 150 caracteres."""
    cleaned = title.replace("<", "(").replace(">", ")").strip()
    return cleaned[:150] if cleaned else "Migrated Playlist"


def migrate_playlist(
    yt: YTMusic,
    playlist_data: dict[str, Any],
    state: dict[str, Any],
    state_path: str,
    logger: logging.Logger,
    unmatched_logger: logging.Logger,
    scrubber: SecretScrubbingFilter,
    sleep_seconds: float,
    max_songs_per_run: int | None = None,
    enforce_quota_cap: bool = False,
    privacy_status: str = "PRIVATE",
) -> int:
    """
    Ejecuta el proceso de migración incremental hacia YouTube Music guardando el estado
    después de cada canción añadida.
    """
    tracks = playlist_data.get("tracks") or []
    processed_keys = set(state.get("processed_track_keys") or [])
    processed_indices = set(state.get("processed_indices") or [])

    pending_tracks: list[tuple[int, dict[str, Any], str]] = []
    for idx, track in enumerate(tracks):
        t_idx = track.get("index", idx)
        t_key = get_track_key(track, t_idx)
        if t_key not in processed_keys and t_idx not in processed_indices:
            pending_tracks.append((t_idx, track, t_key))

    if not pending_tracks:
        logger.info(
            "¡Todas las canciones (%d) de esta playlist ya fueron procesadas según '%s'!",
            len(tracks),
            state_path,
        )
        return 0

    needs_playlist_creation = not bool(state.get("yt_playlist_id"))
    creation_cost = QUOTA_COST_CREATE_PLAYLIST if needs_playlist_creation else 0
    estimated_total_cost = creation_cost + (len(pending_tracks) * QUOTA_COST_ADD_ITEM)

    logger.info(
        "Canciones totales: %d | Ya procesadas: %d | Pendientes: %d",
        len(tracks),
        len(tracks) - len(pending_tracks),
        len(pending_tracks),
    )
    logger.info(
        "Coste estimado de cuota para canciones pendientes: %d unidades "
        "(Creación: %d + %d canciones x %d unidades).",
        estimated_total_cost,
        creation_cost,
        len(pending_tracks),
        QUOTA_COST_ADD_ITEM,
    )

    if estimated_total_cost > QUOTA_DAILY_SAFE_LIMIT:
        max_safe_songs = (QUOTA_DAILY_SAFE_LIMIT - creation_cost) // QUOTA_COST_ADD_ITEM
        logger.warning(
            "========================================================================\n"
            "ADVERTENCIA CRÍTICA DE CUOTA DE YOUTUBE (%d unidades > %d límite seguro):\n"
            "La cuota diaria predeterminada de YouTube es de 10.000 unidades/día (~%d canciones/día).\n"
            "Para una playlist de %d canciones pendientes no es posible completar la migración en un solo día\n"
            "sin un aumento de cuota. El progreso se guardará después de cada canción en '%s'\n"
            "para que pueda reanudar en sesiones/días posteriores.\n"
            "========================================================================",
            estimated_total_cost,
            QUOTA_DAILY_SAFE_LIMIT,
            max_safe_songs,
            len(pending_tracks),
            state_path,
        )
        if enforce_quota_cap and (max_songs_per_run is None or max_songs_per_run > max_safe_songs):
            max_songs_per_run = max_safe_songs
            logger.info(
                "Modo --respect-quota-limit activo: limitando esta sesión a %d canciones (%d unidades).",
                max_songs_per_run,
                creation_cost + (max_songs_per_run * QUOTA_COST_ADD_ITEM),
            )

    if max_songs_per_run is not None and max_songs_per_run > 0:
        pending_tracks = pending_tracks[:max_songs_per_run]
        logger.info("Procesando hasta %d canciones en esta sesión.", len(pending_tracks))

    quota_used_this_run = 0

    try:
        # Paso 1: Crear playlist en YouTube Music si aún no existe en el estado
        yt_playlist_id = state.get("yt_playlist_id")
        if not yt_playlist_id:
            yt_title = sanitize_playlist_title(state.get("yt_playlist_title") or "Spotify Migrated Playlist")
            raw_desc = playlist_data.get("playlist_description") or ""
            yt_desc = sanitize_playlist_title(
                f"Migrada desde Spotify ({playlist_data.get('playlist_name', '')}). {raw_desc}".strip()
            )
            logger.info("Creando nueva playlist en YouTube Music: '%s'...", yt_title)
            created_id = call_ytmusic_safely(
                yt.create_playlist,
                logger,
                scrubber,
                title=yt_title,
                description=yt_desc,
                privacy_status=privacy_status,
            )
            if not created_id or not isinstance(created_id, str) or "error" in created_id.lower():
                raise RuntimeError(
                    f"No se pudo obtener un ID de playlist válido al crear la playlist: {created_id}"
                )

            yt_playlist_id = created_id
            state["yt_playlist_id"] = yt_playlist_id
            state["yt_playlist_title"] = yt_title
            quota_used_this_run += QUOTA_COST_CREATE_PLAYLIST
            state["estimated_quota_used_last_run"] = quota_used_this_run
            save_state(state, state_path)
            logger.info("Playlist creada con éxito en YouTube Music (ID: %s).", yt_playlist_id)

        # Paso 2: Procesar canciones pendientes una por una
        added_count_session = 0
        not_found_count_session = 0

        for pos, (t_idx, track, t_key) in enumerate(pending_tracks, start=1):
            title = (track.get("title") or "").strip()
            artist = (track.get("artist") or "").strip()
            album = (track.get("album") or "").strip()
            query = f"{title} {artist}".strip()

            logger.info(
                "[%d/%d] Buscando en YouTube Music: '%s' - '%s'...",
                pos,
                len(pending_tracks),
                title,
                artist,
            )

            search_results = call_ytmusic_safely(
                yt.search,
                logger,
                scrubber,
                query,
                filter="songs",
            )

            best_match, confidence = select_best_match(track, search_results)

            # Si no hubo resultados con filter="songs", intentar búsqueda en "videos" como respaldo
            if best_match is None:
                fallback_results = call_ytmusic_safely(
                    yt.search,
                    logger,
                    scrubber,
                    query,
                    filter="videos",
                )
                best_match, confidence = select_best_match(track, fallback_results)

            if best_match is None:
                not_found_count_session += 1
                msg = (
                    f"NO ENCONTRADA | Índice={t_idx} | Título='{title}' | "
                    f"Artista='{artist}' | Álbum='{album}' | ISRC={track.get('isrc')}"
                )
                logger.warning(msg)
                unmatched_logger.warning(msg)

                state["failed_tracks"].append(
                    {
                        "index": t_idx,
                        "title": title,
                        "artist": artist,
                        "album": album,
                        "isrc": track.get("isrc"),
                        "reason": "Sin resultados en YouTube Music",
                    }
                )
                state["processed_indices"].append(t_idx)
                state["processed_track_keys"].append(t_key)
                save_state(state, state_path)
                time.sleep(max(sleep_seconds, MIN_SLEEP_SECONDS))
                continue

            video_id = best_match["videoId"]
            matched_title = best_match.get("title") or ""
            matched_artists = ", ".join(
                a.get("name", "") for a in (best_match.get("artists") or []) if isinstance(a, dict)
            )

            if confidence < 0.55:
                low_conf_msg = (
                    f"BAJA CONFIANZA ({confidence:.2f}) | Índice={t_idx} | "
                    f"Original: '{title}' - '{artist}' -> "
                    f"Encontrado: '{matched_title}' - '{matched_artists}' (videoId={video_id})"
                )
                logger.warning(low_conf_msg)
                unmatched_logger.info(low_conf_msg)

            add_resp = call_ytmusic_safely(
                yt.add_playlist_items,
                logger,
                scrubber,
                yt_playlist_id,
                [video_id],
                duplicates=False,
            )

            # Verificar si la respuesta de ytmusicapi indica error de estado o cuota
            if isinstance(add_resp, dict):
                status_str = str(add_resp.get("status") or "")
                if "FAILURE" in status_str.upper():
                    actions_str = json.dumps(add_resp)
                    if is_quota_or_rate_limit_error( RuntimeError(actions_str) ):
                        raise QuotaExceededStop(
                            "YouTube Music rechazó la adición por límite de cuota o tamaño."
                        )
                    logger.warning(
                        "Aviso al añadir '%s' (videoId=%s): estado devuelto=%s",
                        title,
                        video_id,
                        status_str,
                    )

            added_count_session += 1
            quota_used_this_run += QUOTA_COST_ADD_ITEM
            state["processed_indices"].append(t_idx)
            state["processed_track_keys"].append(t_key)
            state["added_video_ids"].append(video_id)
            state["estimated_quota_used_last_run"] = quota_used_this_run
            save_state(state, state_path)

            logger.info(
                "Añadida [%d/%d]: '%s' -> '%s' (%s) [videoId=%s, confianza=%.2f]",
                pos,
                len(pending_tracks),
                title,
                matched_title,
                matched_artists,
                video_id,
                confidence,
            )

            time.sleep(max(sleep_seconds, MIN_SLEEP_SECONDS))

    except QuotaExceededStop as exc:
        save_state(state, state_path)
        logger.error(
            "========================================================================\n"
            "DETENCIÓN LIMPIA POR LÍMITE DE CUOTA / TASA:\n"
            "%s\n"
            "El estado actual se ha guardado de forma segura en '%s'.\n"
            "Puede reanudar la migración en la siguiente sesión ejecutando el mismo comando.\n"
            "========================================================================",
            scrubber.sanitize(str(exc)),
            state_path,
        )
        return 2
    except KeyboardInterrupt:
        save_state(state, state_path)
        logger.warning(
            "Migración pausada por el usuario (Ctrl+C). Progreso guardado en '%s'.",
            state_path,
        )
        return 130

    logger.info(
        "Sesión finalizada: %d canciones añadidas, %d no encontradas. "
        "Progreso total acumulado: %d/%d canciones procesadas. Estado guardado en '%s'.",
        added_count_session,
        not_found_count_session,
        len(state["processed_track_keys"]),
        len(tracks),
        state_path,
    )
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Crea una playlist en YouTube Music a partir del archivo JSON generado por "
            "fetch_spotify_playlist.py, con soporte de reanudación automática y control de cuota."
        ),
        epilog=(
            "Ejemplos de uso:\n"
            "  python upload_ytmusic.py\n"
            "  python upload_ytmusic.py -i playlist_data.json -s upload_state.json --max-songs 190\n"
            "  python upload_ytmusic.py --playlist-name \"Mis Favoritas de Spotify\" --respect-quota-limit"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-i",
        "--input",
        default=DEFAULT_INPUT_FILE,
        help=f"Archivo JSON de entrada con las canciones extraídas (por defecto: {DEFAULT_INPUT_FILE})",
    )
    parser.add_argument(
        "-s",
        "--state-file",
        default=DEFAULT_STATE_FILE,
        help=f"Archivo JSON de estado para reanudar migraciones (por defecto: {DEFAULT_STATE_FILE})",
    )
    parser.add_argument(
        "--auth-file",
        default=None,
        help=f"Archivo de autenticación de navegador de ytmusicapi (por defecto: {DEFAULT_AUTH_FILE})",
    )
    parser.add_argument(
        "--playlist-name",
        default=None,
        help="Nombre personalizado para la nueva playlist en YouTube Music.",
    )
    parser.add_argument(
        "--privacy",
        choices=["PRIVATE", "PUBLIC", "UNLISTED"],
        default="PRIVATE",
        help="Nivel de privacidad de la playlist a crear (por defecto: PRIVATE).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_SLEEP_SECONDS,
        help=(
            f"Pausa en segundos entre cada canción para evitar bloqueos "
            f"(mínimo permitido: {MIN_SLEEP_SECONDS}s, por defecto: {DEFAULT_SLEEP_SECONDS}s)."
        ),
    )
    parser.add_argument(
        "--max-songs",
        type=int,
        default=None,
        help="Número máximo de canciones a procesar en esta sesión (útil para dividir por días).",
    )
    parser.add_argument(
        "--respect-quota-limit",
        action="store_true",
        help="Limita automáticamente la sesión a ~190 canciones (9.500 unidades de cuota).",
    )
    parser.add_argument(
        "--log-file",
        default=DEFAULT_LOG_FILE,
        help=f"Archivo de log general (por defecto: {DEFAULT_LOG_FILE})",
    )
    parser.add_argument(
        "--unmatched-log",
        default=DEFAULT_UNMATCHED_LOG_FILE,
        help=(
            "Archivo de log para canciones no encontradas o de baja confianza "
            f"(por defecto: {DEFAULT_UNMATCHED_LOG_FILE})"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    sleep_seconds = max(args.delay, MIN_SLEEP_SECONDS)
    auth_file = (
        args.auth_file
        or os.getenv("YTMUSIC_AUTH_FILE", "").strip()
        or DEFAULT_AUTH_FILE
    )
    env_cookie = os.getenv("YTMUSIC_COOKIE", "").strip()
    user_agent = (
        os.getenv("YTMUSIC_USER_AGENT", "").strip()
        or "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0"
    )

    preliminary_secrets = [env_cookie] if env_cookie else []
    logger, unmatched_logger, scrubber = setup_logging(
        log_file=args.log_file,
        unmatched_log_file=args.unmatched_log,
        secrets=preliminary_secrets,
    )

    if args.delay < MIN_SLEEP_SECONDS:
        logger.warning(
            "La pausa solicitada (%.2fs) es menor al mínimo seguro de %.1fs. Se ajustó a %.1fs.",
            args.delay,
            MIN_SLEEP_SECONDS,
            sleep_seconds,
        )

    try:
        if not Path(auth_file).exists() and env_cookie:
            logger.info(
                "Generando '%s' con permisos seguros a partir de la variable YTMUSIC_COOKIE...",
                auth_file,
            )
            build_browser_auth_from_cookie(
                cookie_str=env_cookie,
                auth_filepath=auth_file,
                user_agent=user_agent,
            )

        file_secrets = validate_browser_auth_file(auth_file)
        scrubber.secrets.extend([s for s in file_secrets if s and len(s) >= 6])

        playlist_data = load_playlist_data(args.input)
        state = load_or_init_state(
            state_path=args.state_file,
            playlist_data=playlist_data,
            target_title=args.playlist_name,
        )
        yt = create_ytmusic_client(auth_file)

        return migrate_playlist(
            yt=yt,
            playlist_data=playlist_data,
            state=state,
            state_path=args.state_file,
            logger=logger,
            unmatched_logger=unmatched_logger,
            scrubber=scrubber,
            sleep_seconds=sleep_seconds,
            max_songs_per_run=args.max_songs,
            enforce_quota_cap=args.respect_quota_limit,
            privacy_status=args.privacy,
        )
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        logger.error("%s", scrubber.sanitize(str(exc)))
        return 1
    except Exception as exc:
        logger.error(
            "Error inesperado durante la carga a YouTube Music: %s",
            scrubber.sanitize(str(exc)),
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())

