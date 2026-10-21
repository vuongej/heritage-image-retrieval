import { afterEach, describe, expect, it, vi } from 'vitest';
import { z } from 'zod';
import { ApiError, request } from './backendClient';

function respond(status: number, body: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })),
  );
}

const call = () => request('/v1/search', z.object({}), { method: 'POST', body: { query: 'x' } }).catch((e: unknown) => e);

afterEach(() => vi.unstubAllGlobals());

describe('request() error mapping', () => {
  it('maps a content-guard rejection to kind "blocked" and keeps the server message', async () => {
    respond(400, { detail: 'Hệ thống không hỗ trợ tìm kiếm nội dung khiêu dâm.', code: 'query_blocked', category: 'sexual' });
    const err = await call();
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ kind: 'blocked', status: 400, code: 'query_blocked' });
    expect((err as ApiError).detail).toContain('khiêu dâm');
  });

  it('keeps other HTTP 400/422 responses as invalid_request', async () => {
    respond(422, { detail: [{ msg: 'field required' }] });
    expect(await call()).toMatchObject({ kind: 'invalid_request', status: 422, detail: 'field required' });
    respond(400, { detail: 'bad request' });
    expect(await call()).toMatchObject({ kind: 'invalid_request', code: undefined });
  });
});
