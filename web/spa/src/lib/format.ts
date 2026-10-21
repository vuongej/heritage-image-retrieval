const intFmt = new Intl.NumberFormat('vi-VN');
const pctFmt = new Intl.NumberFormat('vi-VN', { style: 'percent', maximumFractionDigits: 1 });
const decFmt = new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 3 });

export const DASH = '—';

export function fmtInt(n: number | null | undefined): string {
  return n === null || n === undefined || !Number.isFinite(n) ? DASH : intFmt.format(Math.round(n));
}

export function fmtPct(ratio: number | null | undefined): string {
  return ratio === null || ratio === undefined || !Number.isFinite(ratio) ? DASH : pctFmt.format(ratio);
}

export function fmtDec(n: number | null | undefined, digits = 3): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return DASH;
  return digits === 3 ? decFmt.format(n) : n.toLocaleString('vi-VN', { maximumFractionDigits: digits });
}

export function fmtMs(n: number | null | undefined): string {
  return n === null || n === undefined || !Number.isFinite(n) ? DASH : `${intFmt.format(Math.round(n))} ms`;
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString('vi-VN', { dateStyle: 'medium', timeStyle: 'short' });
}

/** Display-only: capitalize the first letter of a lower-cased backend phrase ("hồ bơi" -> "Hồ bơi"). */
export function sentenceCase(text: string): string {
  return text.replace(/^\s*(\p{L})/u, (m) => m.toLocaleUpperCase('vi-VN'));
}

/** Display-only capitalization of a lower-cased place name ("phú quốc" -> "Phú Quốc"). */
export function titleCase(text: string): string {
  return text.replace(/(^|\s)(\p{L})/gu, (_, sp: string, ch: string) => sp + ch.toLocaleUpperCase('vi-VN'));
}
