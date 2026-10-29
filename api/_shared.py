"""
Utilidades compartidas sin estado (stateless) para el backend proxy de SongExtractor.
Garantiza:
- Cero persistencia en disco ni en memoria entre peticiones.
- Sanitización de cookies y datos sensibles en cualquier mensaje de error.
- Validación estricta de URLs HTTPS de playlists públicas de Spotify (rechazando álbumes, artistas o pistas).
- Extracción paginada mediante spotifyscraper (cliente GraphQL interno del reproductor web).
- Inicialización en memoria de YTMusic a partir de cookies/browser.json.
"""

from __future__ import annotations

import difflib
import json
import re
from typing import Any
from urllib.parse import urlparse

from spotify_scraper import SpotifyClient
from spotify_scraper.api import parse_embed, parse_entities
from spotify_scraper.errors import NotFoundError, SpotifyScraperError
from ytmusicapi import YTMusic
from ytmusicapi.auth.browser import setup_browser
from ytmusicapi.helpers import get_authorization, sapisid_from_cookie

SPOTIFY_PLAYLIST_URL_RE = re.compile(
    r"^https://open\.spotify\.com/(?:intl-[a-zA-Z-]+/)?playlist/([a-zA-Z0-9]{22})(?:\?.*)?$"
)
SPOTIFY_NON_PLAYLIST_URL_RE = re.compile(
    r"^https://open\.spotify\.com/(?:intl-[a-zA-Z-]+/)?(album|artist|track|episode|show|user)/",
    re.IGNORECASE,
)
SPOTIFY_PLAYLIST_ID_RE = re.compile(r"^[a-zA-Z0-9]{22}$")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0"
)

_COOKIE_SCRUB_RE = re.compile(
    r"(__Secure-3PAPISID|SAPISID|HSID|SSID|APISID|SID|LOGIN_INFO)=[^;\s\"']+",
    re.IGNORECASE,
)
_SAPISIDHASH_SCRUB_RE = re.compile(r"(SAPISIDHASH\s+)[A-Za-z0-9_]+", re.IGNORECASE)
_BEARER_SCRUB_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE)


def sanitize_error_message(text: str, extra_secrets: list[str] | None = None) -> str:
    """Elimina cualquier cookie o token antes de devolver un mensaje de error."""
    if not text:
        return "Error desconocido"
    cleaned = _COOKIE_SCRUB_RE.sub(r"\1=[REDACTED]", text)
    cleaned = _SAPISIDHASH_SCRUB_RE.sub(r"\1[REDACTED]", cleaned)
    cleaned = _BEARER_SCRUB_RE.sub(r"\1[REDACTED]", cleaned)
    for secret in extra_secrets or []:
        if secret and len(secret) >= 6 and secret in cleaned:
            cleaned = cleaned.replace(secret, "[REDACTED]")
    return cleaned


def extract_and_validate_playlist_id(url_or_id: str) -> str:
    """
    Valida que la entrada sea una URL HTTPS de playlist de Spotify o un ID de 22 caracteres.
    Rechaza explícitamente URLs de álbumes, artistas, canciones individuales o podcasts.
    """
    if not url_or_id or not isinstance(url_or_id, str):
        raise ValueError("Debes proporcionar el enlace de una playlist pública de Spotify.")

    raw = url_or_id.strip()
    if SPOTIFY_PLAYLIST_ID_RE.match(raw):
        return raw

    parsed = urlparse(raw)
    if parsed.scheme.lower() != "https":
        raise ValueError("El enlace de Spotify debe comenzar con https://")
    if parsed.netloc.lower() != "open.spotify.com":
        raise ValueError("El enlace debe pertenecer a 'open.spotify.com'.")

    non_playlist_match = SPOTIFY_NON_PLAYLIST_URL_RE.match(raw)
    if non_playlist_match:
        kind = non_playlist_match.group(1).lower()
        raise ValueError(
            f"Has pegado un enlace de tipo '{kind}'. Solo se admiten enlaces de playlists públicas "
            "(https://open.spotify.com/playlist/...)."
        )

    match = SPOTIFY_PLAYLIST_URL_RE.match(raw)
    if not match:
        raise ValueError(
            "Formato de enlace de Spotify no válido. "
            "Ejemplo esperado: https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
        )
    return match.group(1)


def fetch_spotify_playlist_page_stateless(
    playlist_id: str,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    """
    Obtiene una página de hasta 100 canciones de una playlist pública de Spotify
    usando spotifyscraper contra el endpoint GraphQL del reproductor web sin requerir
    cuenta Premium ni credenciales de API.
    """
    valid_id = extract_and_validate_playlist_id(playlist_id)
    limit = max(1, min(100, int(limit)))
    offset = max(0, int(offset))

    with SpotifyClient() as client:
        try:
            next_data = client._fetch_next_data("playlist", valid_id)
            session = parse_embed.get_session(next_data)
            union = client._fetch_union(
                "playlist",
                valid_id,
                "playlistV2",
                session,
                overrides={"offset": offset, "limit": limit},
            )
            playlist = parse_entities.parse_playlist_gql(union)
            content = union.get("content") if isinstance(union, dict) else {}
            raw_items = content.get("items") if isinstance(content, dict) else []
            raw_count = len(raw_items) if isinstance(raw_items, list) else len(playlist.tracks)
        except NotFoundError as exc:
            raise LookupError(
                "No se encontró la playlist en Spotify o es privada."
            ) from exc
        except SpotifyScraperError as exc:
            raise RuntimeError(
                f"No se pudo leer la playlist desde Spotify: {sanitize_error_message(str(exc))}"
            ) from exc

    total_tracks = playlist.total_tracks if playlist.total_tracks is not None else len(playlist.tracks)
    cover_url = playlist.images[0].url if playlist.images else None
    owner_name = (
        (playlist.owner.name or "Spotify")
        if playlist.owner
        else "Spotify"
    )

    tracks_out: list[dict[str, Any]] = []
    for idx, item in enumerate(playlist.tracks):
        tr = item.track
        artists_list = [a.name for a in (tr.artists or ()) if a and a.name]
        primary_artist = artists_list[0] if artists_list else "Artista desconocido"
        album_name = tr.album.name if tr.album and tr.album.name else ""
        thumb = tr.images[-1].url if tr.images else cover_url

        tracks_out.append(
            {
                "index": offset + idx,
                "spotify_id": tr.id,
                "spotify_uri": tr.uri or f"spotify:track:{tr.id}",
                "title": tr.name,
                "artist": primary_artist,
                "artists": artists_list,
                "album": album_name,
                "duration_ms": tr.duration_ms or 0,
                "isrc": getattr(tr, "isrc", None),
                "thumbnail": thumb,
            }
        )

    next_offset = offset + raw_count
    has_next = raw_count > 0 and next_offset < total_tracks

    return {
        "playlist_id": valid_id,
        "name": playlist.name or f"Playlist {valid_id}",
        "description": playlist.description or "",
        "owner": owner_name,
        "cover_url": cover_url,
        "total": total_tracks,
        "offset": offset,
        "limit": limit,
        "raw_count": raw_count,
        "next_offset": next_offset if has_next else None,
        "has_next": has_next,
        "tracks": tracks_out,
    }


def _extract_clean_cookie_string(raw_input: str) -> str:
    """
    Extrae y limpia la cadena de cookies de YouTube Music sin importar cómo la haya
    copiado el usuario desde DevTools (valor directo, con saltos de línea de Chrome,
    con prefijo 'Cookie:', o bloque completo de Request Headers).
    """
    text = raw_input.strip()

    # Si pegó un bloque de cabeceras HTTP con varias líneas tipo "Header: Value"
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for i, ln in enumerate(lines):
        low = ln.lower()
        if low.startswith("cookie:"):
            val = ln.split(":", 1)[1].strip()
            if val:
                return val
            if i + 1 < len(lines):
                return lines[i + 1].strip()
        if low == "cookie" and i + 1 < len(lines):
            return lines[i + 1].strip()

    # Si es el valor de la cookie envuelto en varias líneas al copiar de Chrome DevTools
    joined = " ".join(lines)
    # Normalizar posibles cortes de línea dentro de tokens largos si no hay '; '
    cleaned = re.sub(r"\s*;\s*", "; ", joined)
    return cleaned.strip()


def _extract_sapisid(cookie_str: str) -> str:
    """Extrae el valor de __Secure-3PAPISID (o SAPISID) desde la cadena de cookie."""
    match = re.search(r"__Secure-3PAPISID=([^;\s]+)", cookie_str)
    if match:
        return match.group(1).strip()
    try:
        return sapisid_from_cookie(cookie_str)
    except Exception:
        pass
    fallback = re.search(r"(?:^|;\s*)SAPISID=([^;\s]+)", cookie_str)
    if fallback:
        return fallback.group(1).strip()
    raise ValueError(
        "La cookie proporcionada no contiene '__Secure-3PAPISID'. "
        "Asegúrate de haber iniciado sesión en music.youtube.com antes de copiar la cabecera Cookie."
    )


def create_stateless_ytmusic_client(cookie_or_json: str, user_agent: str | None = None) -> YTMusic:
    """
    Construye una instancia de YTMusic 100% en memoria (sin escribir archivos en el servidor)
    a partir de un JSON browser.json o de una cadena de cabecera Cookie cruda.
    Genera automáticamente la cabecera Authorization SAPISIDHASH requerida por ytmusicapi
    para que nunca sea confundida con un JSON de OAuth.
    """
    if not cookie_or_json or not isinstance(cookie_or_json, str):
        raise ValueError("Se requiere la cookie o el contenido de browser.json de YouTube Music.")

    raw = cookie_or_json.strip()
    ua = (user_agent or DEFAULT_USER_AGENT).strip()
    cookie_line = ""

    if raw.startswith("{") and raw.endswith("}"):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                for k, v in parsed.items():
                    if k.lower() == "cookie" and isinstance(v, str):
                        cookie_line = v.strip()
                        break
                if parsed.get("user-agent") or parsed.get("User-Agent"):
                    ua = str(parsed.get("user-agent") or parsed.get("User-Agent")).strip()
        except json.JSONDecodeError as exc:
            raise ValueError(f"El formato JSON proporcionado no es válido: {exc}") from None

    if not cookie_line:
        cookie_line = _extract_clean_cookie_string(raw)

    sapisid = _extract_sapisid(cookie_line)
    origin = "https://music.youtube.com"
    auth_header = get_authorization(f"{sapisid} {origin}")

    headers_raw = (
        f"Accept: */*\n"
        f"Accept-Language: es-ES,es;q=0.9,en;q=0.8\n"
        f"Authorization: {auth_header}\n"
        f"Content-Type: application/json\n"
        f"X-Goog-AuthUser: 0\n"
        f"x-origin: {origin}\n"
        f"User-Agent: {ua}\n"
        f"Cookie: {cookie_line}\n"
    )
    auth_json_str = setup_browser(filepath=None, headers_raw=headers_raw)
    auth_dict = json.loads(auth_json_str)
    auth_dict["authorization"] = auth_header
    auth_dict["x-origin"] = origin
    auth_dict["origin"] = origin

    # Evitar que ytmusicapi realice una petición GET adicional no autenticada a music.youtube.com
    # en cada invocación serverless para buscar X-Goog-Visitor-Id
    visitor_match = re.search(r"VISITOR_INFO1_LIVE=([^;\s]+)", cookie_line)
    auth_dict["x-goog-visitor-id"] = visitor_match.group(1).strip() if visitor_match else ""

    return YTMusic(auth=auth_dict)


def normalize_text(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"\((?:feat\.?|ft\.?|with|prod\.?|remaster(?:ed)?|live|version)[^)]*\)", "", text)
    text = re.sub(r"\[(?:feat\.?|ft\.?|with|prod\.?|remaster(?:ed)?|live|version)[^\]]*\]", "", text)
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def score_yt_candidate(
    title: str,
    artist: str,
    duration_ms: int | None,
    candidate: dict[str, Any],
) -> float:
    target_title = normalize_text(title)
    target_artist = normalize_text(artist)

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

    target_duration_s = (duration_ms or 0) / 1000.0
    cand_duration_s = candidate.get("duration_seconds")
    if target_duration_s > 0 and isinstance(cand_duration_s, (int, float)) and cand_duration_s > 0:
        diff = abs(target_duration_s - cand_duration_s)
        if diff <= 5:
            score = min(1.0, score + 0.05)
        elif diff > 30:
            score = max(0.0, score - 0.15)

    return round(score, 3)


def is_quota_exceeded_error(exc: Exception | str) -> bool:
    msg = str(exc).lower()
    keywords = (
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
    return any(k in msg for k in keywords)
