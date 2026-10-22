import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError } from '@/api/backendClient';
import { getHealth, getStats } from '@/api/metricsAdapter';
import {
  cancelJob,
  getItems,
  getJob,
  getProcessHealth,
  listJobs,
  uploadCsv,
  type ItemFilter,
  type UploadOptions,
} from '@/api/processAdapter';
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
    // Only retain results when loading more/filtering the same query, never across search terms.
    placeholderData: (previousData, previousQuery) =>
      previousQuery?.queryKey[1] === params?.query ? previousData : undefined,
    staleTime: 60_000,
    // Multi-hop online lookup keeps running in the background after the request budget: poll a few
    // times (backend does not cache pending answers) until the edge lands or the lookup gives up.
    refetchInterval: (query) =>
      query.state.data?.status === 'pending' && query.state.dataUpdateCount < HOP_POLLS ? 4_000 : false,
    retry,
  });
}

// ---- Pipeline A: processing service (/api/v1/process/*) ----
const RUNNING = new Set(['queued', 'running']);

export function useProcessHealth() {
  return useQuery({ queryKey: ['process', 'health'], queryFn: ({ signal }) => getProcessHealth(signal), enabled: live, staleTime: 10_000, refetchInterval: 15_000, retry });
}

export function useJobs() {
  return useQuery({
    queryKey: ['process', 'jobs'],
    queryFn: ({ signal }) => listJobs(signal),
    enabled: live,
    refetchInterval: (q) => (q.state.data?.items.some((j) => RUNNING.has(j.status)) ? 3_000 : false),
    retry,
  });
}

export function useJob(id: string | undefined) {
  return useQuery({
    queryKey: ['process', 'job', id],
    queryFn: ({ signal }) => getJob(id as string, signal),
    enabled: live && Boolean(id),
    // Tiến độ từng tầng: hỏi lại mỗi 1,5 s cho tới khi job kết thúc.
    refetchInterval: (q) => (!q.state.data || RUNNING.has(q.state.data.status) ? 1_500 : false),
    retry,
  });
}

export function useJobItems(id: string, filter: ItemFilter) {
  return useQuery({
    queryKey: ['process', 'items', id, filter],
    queryFn: ({ signal }) => getItems(id, filter, signal),
    enabled: live,
    placeholderData: keepPreviousData,
    retry,
  });
}

export function useUpload() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ file, ...opts }: UploadOptions & { file: File }) => uploadCsv(file, opts),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['process'] }),
  });
}

export function useCancelJob() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: cancelJob, onSuccess: () => qc.invalidateQueries({ queryKey: ['process'] }) });
}
