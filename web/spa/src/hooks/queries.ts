import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { ApiError } from '@/api/backendClient';
import {
  getAuditQueue,
  getHealth,
  getIndexCounts,
  getLatency,
  getQuality,
  getRerankAb,
  getStats,
  getVerify,
  listReports,
} from '@/api/metricsAdapter';
import { searchImages } from '@/api/searchAdapter';
import { DATA_MODE } from '@/config';
import type { SearchParams } from '@/types/search';

const live = DATA_MODE === 'live';
/** Max automatic re-asks while a multi-hop online lookup is pending (~30 s at 4 s). */
const HOP_POLLS = 8;

/** Retry only transient failures, never 4xx; 429 waits for the user (Retry-After shown). */
function retry(count: number, err: unknown) {
  if (err instanceof ApiError && ['network', 'timeout', 'server'].includes(err.kind)) return count < 1;
  return false;
}

export function useHealth() {
  return useQuery({ queryKey: ['health'], queryFn: ({ signal }) => getHealth(signal), enabled: live, staleTime: 30_000, retry });
}

export function useStats() {
  return useQuery({ queryKey: ['stats'], queryFn: ({ signal }) => getStats(signal), enabled: live, staleTime: 30_000, retry });
}

export function useSearch(params: SearchParams | null) {
  return useQuery({
    queryKey: ['search', params?.query, params?.top_k, params?.parent_class ?? null],
    queryFn: async ({ signal }) => {
      if (!params) throw new Error('missing params');
      if (!live) return (await import('@/mocks/fixtures')).mockSearch(params);
      return searchImages(params, signal);
    },
    enabled: Boolean(params?.query),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
    // Multi-hop online lookup keeps running in the background after the request budget: poll a few
    // times (backend does not cache pending answers) until the edge lands or the lookup gives up.
    refetchInterval: (query) =>
      query.state.data?.status === 'pending' && query.state.dataUpdateCount < HOP_POLLS ? 4_000 : false,
    retry,
  });
}

const report = <T,>(key: string, fn: (s?: AbortSignal) => Promise<T>) =>
  ({ queryKey: ['report', key], queryFn: ({ signal }: { signal: AbortSignal }) => fn(signal), enabled: live, staleTime: 300_000, retry });

export const useReportList = () => useQuery(report('list', listReports));
export const useLatency = () => useQuery(report('latency', getLatency));
export const useQuality = () => useQuery(report('quality', getQuality));
export const useIndexCounts = () => useQuery(report('index_counts', getIndexCounts));
export const useRerankAb = () => useQuery(report('rerank_ab', getRerankAb));
export const useVerify = () => useQuery(report('verify', getVerify));
export const useAuditQueue = () => useQuery(report('audit', getAuditQueue));
