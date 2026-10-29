export type FlowStep = 'connect' | 'preview' | 'ytconfig' | 'migrate' | 'summary';

export type TrackMigrationStatus =
  | 'pending'
  | 'searching'
  | 'added'
  | 'low_confidence'
  | 'failed';

export interface SpotifyTrack {
  index: number;
  spotify_id: string | null;
  spotify_uri: string;
  title: string;
  artist: string;
  artists: string[];
  album: string;
  duration_ms: number;
  isrc?: string | null;
  thumbnail?: string | null;
}

export interface PlaylistMetadata {
  playlist_id: string;
  name: string;
  description: string;
  owner: string;
  cover_url: string | null;
  total_tracks: number;
}

export interface TrackMigrationRecord {
  index: number;
  trackKey: string;
  status: TrackMigrationStatus;
  videoId?: string;
  matchedTitle?: string;
  matchedArtist?: string;
  confidence?: number;
  errorReason?: string;
}

export interface UploadStateSession {
  source_playlist_id: string;
  source_playlist_url: string;
  source_playlist_name: string;
  yt_playlist_id: string | null;
  yt_playlist_title: string;
  yt_privacy: 'PRIVATE' | 'PUBLIC' | 'UNLISTED';
  account_fingerprint?: string | null;
  created_at: string;
  updated_at: string;
  total_tracks_in_source: number;
  processed_indices: number[];
  processed_track_keys: string[];
  added_video_ids: string[];
  track_records: Record<number, TrackMigrationRecord>;
  estimated_quota_used: number;
}
