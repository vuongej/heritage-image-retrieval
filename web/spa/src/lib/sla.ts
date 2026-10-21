import { SLA_MS, SLA_WARN_MS } from '@/config';

export type SlaLevel = 'ok' | 'warn' | 'bad' | 'none';

/** Strict "< 3 s": exactly 3,000 ms is a breach (SKILL.md §7.1). */
export function slaLevel(ms: number | null | undefined): SlaLevel {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return 'none';
  if (ms < SLA_MS) return 'ok';
  if (ms <= SLA_WARN_MS) return 'warn';
  return 'bad';
}

export function isBreach(ms: number): boolean {
  return ms >= SLA_MS;
}

export type GateStatus = 'PASS' | 'FAIL' | 'NOT_MEASURED' | 'NOT_SUPPORTED' | 'PARTIAL';

/**
 * PASS only when every measured request is strictly below the SLA (breach rate 0) and n > 0.
 * p95 alone never decides PASS.
 */
export function slaGate(n: number | undefined, underRatio: number | undefined): GateStatus {
  if (!n || underRatio === undefined) return 'NOT_MEASURED';
  return underRatio >= 1 ? 'PASS' : 'FAIL';
}
