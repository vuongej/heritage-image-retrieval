import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import handler from '../../api/proxy';

const upstream = vi.fn();
beforeEach(() => {
  vi.stubEnv('BACKEND_URL', 'https://search.hf.space');
  vi.stubEnv('PROCESS_URL', 'https://processor.hf.space');
  vi.stubEnv('HF_SPACE_TOKEN', 'search-token');
  vi.stubEnv('PROCESS_HF_TOKEN', 'process-token');
  vi.stubEnv('HF_PROCESS_SPACE', '');
  vi.stubEnv('TEST_API_KEY', 'internal-key');
  upstream.mockReset().mockResolvedValue(Response.json({ status: 'ok' }));
  vi.stubGlobal('fetch', upstream);
});
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

describe('production proxy routing and private Space authentication', () => {
  it.each([
    ['v1/process/health', 'https://processor.hf.space', 'process-token'],
    ['v1/health', 'https://search.hf.space', 'search-token'],
  ])('routes %s with only its configured credentials', async (path, host, token) => {
    const res = await handler(new Request(`https://app/api?__path=${path}`, {
      headers: { Authorization: 'Bearer user-token', 'X-API-Key': 'user-key', Cookie: 'session=private' },
    }));
    expect(res.status).toBe(200);
    const [url, init] = upstream.mock.calls[0]!;
    expect(url).toBe(`${host}/${path}`);
    expect(init.headers.get('Authorization')).toBe(`Bearer ${token}`);
    expect(init.headers.get('X-API-Key')).toBe('internal-key');
    expect(init.headers.has('Cookie')).toBe(false);
    expect(init.redirect).toBe('manual');
  });

  it('does not leak the search token when the processor has no HF token', async () => {
    vi.stubEnv('PROCESS_HF_TOKEN', '');
    await handler(new Request('https://app/api?__path=v1/process/jobs'));
    expect(upstream.mock.calls[0]![1].headers.has('Authorization')).toBe(false);
  });

  it('reuses the existing HF token only for the explicitly configured private Space', async () => {
    vi.stubEnv('PROCESS_HF_TOKEN', '');
    vi.stubEnv('HF_PROCESS_SPACE', 'owner/processor');
    vi.stubEnv('PROCESS_URL', 'https://owner-processor.hf.space/');
    await handler(new Request('https://app/api?__path=v1/process/health'));
    expect(upstream.mock.calls[0]![1].headers.get('Authorization')).toBe('Bearer search-token');
  });

  it.each(['https://other.hf.space', 'https://owner-processor.hf.space.attacker.test',
    'https://owner-processor.hf.space@attacker.test', 'http://owner-processor.hf.space'])
  ('does not reuse HF credentials for a mismatched target: %s', async (target) => {
    vi.stubEnv('PROCESS_HF_TOKEN', '');
    vi.stubEnv('HF_PROCESS_SPACE', 'owner/processor');
    vi.stubEnv('PROCESS_URL', target);
    await handler(new Request('https://app/api?__path=v1/process/health'));
    expect(upstream.mock.calls[0]![1].headers.has('Authorization')).toBe(false);
  });

  it('reports missing processor configuration without calling search', async () => {
    vi.stubEnv('PROCESS_URL', '');
    const res = await handler(new Request('https://app/api?__path=v1/process/health'));
    expect(res.status).toBe(503);
    expect(upstream).not.toHaveBeenCalled();
  });

  it('forwards a CSV upload and its multipart boundary to the processor', async () => {
    const form = new FormData();
    form.append('file', new Blob(['entity_name,image_url\nExample,https://example.com/a.jpg\n']), 'test.csv');
    form.append('use_vlm', 'false');
    await handler(new Request('https://app/api?__path=v1/process/jobs', { method: 'POST', body: form }));
    const [url, init] = upstream.mock.calls[0]!;
    expect(url).toBe('https://processor.hf.space/v1/process/jobs');
    expect(init.method).toBe('POST');
    expect(init.headers.get('Content-Type')).toMatch(/^multipart\/form-data; boundary=/);
    expect(new TextDecoder().decode(init.body)).toContain('entity_name,image_url');
  });
});
