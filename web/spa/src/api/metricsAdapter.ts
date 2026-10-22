import { request } from './backendClient';
import { healthSchema, statsSchema, type Health, type Stats } from './validators';

// Trạng thái backend tìm kiếm (thanh header, trang Tìm kiếm).

export const getHealth = (signal?: AbortSignal) => request('/v1/health', healthSchema, { signal }).then((r) => r.data);
export const getStats = (signal?: AbortSignal) => request('/v1/stats', statsSchema, { signal }).then((r) => r.data);

export type { Health, Stats };
