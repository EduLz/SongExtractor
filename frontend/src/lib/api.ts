import { SpotifyTrack } from './types';

export const STORAGE_KEYS = {
  UPLOAD_STATE: 'se_upload_state_v2',
  EXTRACTED_PLAYLIST: 'se_extracted_playlist_v2',
  YTMUSIC_COOKIE: 'se_ytmusic_cookie_session',
} as const;

const SPOTIFY_PLAYLIST_URL_RE =
  /^https:\/\/open\.spotify\.com\/(?:intl-[a-zA-Z-]+\/)?playlist\/([a-zA-Z0-9]{22})(?:\?.*)?$/;

const SPOTIFY_NON_PLAYLIST_RE =
  /^https:\/\/open\.spotify\.com\/(?:intl-[a-zA-Z-]+\/)?(album|artist|track|episode|show)\//i;

export function parseSpotifyPlaylistUrl(input: string): {
  valid: boolean;
  playlistId: string | null;
  error?: string;
} {
  const trimmed = input.trim();
  if (!trimmed) {
    return { valid: false, playlistId: null, error: 'Pega el enlace de una playlist de Spotify.' };
  }
  if (/^[a-zA-Z0-9]{22}$/.test(trimmed)) {
    return { valid: true, playlistId: trimmed };
  }
  const nonPlaylist = SPOTIFY_NON_PLAYLIST_RE.exec(trimmed);
  if (nonPlaylist) {
    return {
      valid: false,
      playlistId: null,
      error:
        'Ese enlace pertenece a un álbum, canción o artista. Por favor pega el enlace de una playlist pública.',
    };
  }
  const match = SPOTIFY_PLAYLIST_URL_RE.exec(trimmed);
  if (!match) {
    return {
      valid: false,
      playlistId: null,
      error:
        'El enlace no parece válido. Asegúrate de copiarlo desde Spotify (Compartir → Copiar enlace de la playlist).',
    };
  }
  return { valid: true, playlistId: match[1] };
}

export class QuotaExceededError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'QuotaExceededError';
  }
}

async function parseErrorDetail(resp: Response): Promise<string> {
  try {
    const data = await resp.json();
    if (typeof data?.detail === 'string') return data.detail;
    if (typeof data?.detail?.message === 'string') return data.detail.message;
    if (typeof data?.message === 'string') return data.message;
    return 'No se pudo completar la operación en este momento.';
  } catch {
    return (await resp.text()) || `Error de comunicación (${resp.status})`;
  }
}

export interface SpotifyPlaylistPageResponse {
  playlist_id: string;
  name: string;
  description: string;
  owner: string;
  cover_url: string | null;
  total: number;
  offset: number;
  limit: number;
  raw_count: number;
  next_offset: number | null;
  has_next: boolean;
  tracks: SpotifyTrack[];
}

export async function fetchSpotifyPlaylistPage(params: {
  playlistId: string;
  offset: number;
  limit?: number;
}): Promise<SpotifyPlaylistPageResponse> {
  const limit = params.limit ?? 100;
  const query = new URLSearchParams({
    offset: String(params.offset),
    limit: String(limit),
  });
  const resp = await fetch(
    `/api/spotify/playlist/${encodeURIComponent(params.playlistId)}?${query.toString()}`,
    {
      method: 'GET',
    }
  );
  if (!resp.ok) {
    throw new Error(await parseErrorDetail(resp));
  }
  return resp.json();
}

export async function searchYTMusicTrack(params: {
  cookie: string;
  track: SpotifyTrack;
}): Promise<{
  found: boolean;
  confidence: number;
  low_confidence?: boolean;
  match: {
    videoId: string;
    title: string;
    artist: string;
    album: string;
    duration: string;
    thumbnail?: string | null;
  } | null;
}> {
  const resp = await fetch('/api/ytmusic/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      cookie: params.cookie,
      title: params.track.title,
      artist: params.track.artist,
      album: params.track.album,
      duration_ms: params.track.duration_ms,
      isrc: params.track.isrc,
    }),
  });

  if (resp.status === 403) {
    throw new QuotaExceededError(await parseErrorDetail(resp));
  }
  if (!resp.ok) {
    throw new Error(await parseErrorDetail(resp));
  }
  return resp.json();
}

export async function createYTMusicPlaylist(params: {
  cookie: string;
  title: string;
  description: string;
  privacyStatus: 'PRIVATE' | 'PUBLIC' | 'UNLISTED';
}): Promise<{
  status: string;
  playlist_id: string;
  playlist_url: string;
  quota_cost: number;
}> {
  const resp = await fetch('/api/ytmusic/add', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      cookie: params.cookie,
      action: 'create_playlist',
      title: params.title,
      description: params.description,
      privacy_status: params.privacyStatus,
    }),
  });

  if (resp.status === 403) {
    throw new QuotaExceededError(await parseErrorDetail(resp));
  }
  if (!resp.ok) {
    throw new Error(await parseErrorDetail(resp));
  }
  return resp.json();
}

export async function addTrackToYTMusicPlaylist(params: {
  cookie: string;
  playlistId: string;
  videoId: string;
}): Promise<{
  status: string;
  playlist_id: string;
  video_id: string;
  quota_cost: number;
}> {
  const resp = await fetch('/api/ytmusic/add', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      cookie: params.cookie,
      action: 'add_item',
      playlist_id: params.playlistId,
      video_id: params.videoId,
    }),
  });

  if (resp.status === 403) {
    throw new QuotaExceededError(await parseErrorDetail(resp));
  }
  if (!resp.ok) {
    throw new Error(await parseErrorDetail(resp));
  }
  return resp.json();
}
