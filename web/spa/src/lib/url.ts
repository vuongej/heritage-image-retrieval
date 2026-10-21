/** Only absolute http(s) URLs are ever placed in src/href; anything else is dropped. */
export function safeHttpUrl(value: string | null | undefined): string | undefined {
  if (!value) return undefined;
  try {
    const url = new URL(value);
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.toString() : undefined;
  } catch {
    return undefined;
  }
}

export function hostOf(value: string | null | undefined): string | undefined {
  const safe = safeHttpUrl(value);
  return safe ? new URL(safe).hostname.replace(/^www\./, '') : undefined;
}

/** Same-origin API-relative paths returned by the backend (e.g. "/thumbs/<sha>.jpg"). */
export function safeApiPath(value: string | null | undefined, base: string): string | undefined {
  if (!value || !/^\/thumbs\/[0-9a-f]{64}\.jpg$/.test(value)) return undefined;
  return `${base}${value}`;
}
