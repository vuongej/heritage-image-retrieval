export type DataMode = 'live' | 'mock';

const mode = (import.meta.env.VITE_DATA_MODE ?? 'live').toLowerCase();

/** `live` is the default and the graded mode. A live error is an error — never a silent mock. */
export const DATA_MODE: DataMode = mode === 'mock' ? 'mock' : 'live';
export const API_BASE: string = import.meta.env.VITE_API_BASE || '/api';
export const GITHUB_URL: string | undefined = import.meta.env.VITE_GITHUB_URL || undefined;

/** Assignment SLA: strictly below 3,000 ms; exactly 3,000 ms is a breach. */
export const SLA_MS = 3000;
export const SLA_WARN_MS = 5000;
export const REQUIRED_IMAGES = 80_000;
export const MAX_TOP_K = 100;
export const PAGE_STEP = 20;
export const MAX_QUERY_LENGTH = 2000; // api/schemas.py SearchRequest.query max_length
export const REQUEST_TIMEOUT_MS = 20_000;
