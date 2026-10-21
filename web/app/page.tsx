'use client';
import { useState } from 'react';
import SearchBar from '@/components/SearchBar';
import ResultGrid from '@/components/ResultGrid';
import FacetChips from '@/components/FacetChips';
import { search, type SearchResult } from '@/lib/api';

export default function Page() {
  const [res, setRes] = useState<SearchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function run(q: string) {
    if (!q.trim()) return;
    setLoading(true); setErr(null);
    try { setRes(await search(q)); }
    catch (e: any) { setErr(e.message); setRes(null); }
    finally { setLoading(false); }
  }

  return (
    <>
      <SearchBar onSearch={run} loading={loading} />
      {err && <div className="empty">Lỗi: {err}</div>}
      {res && (
        <>
          <div className="muted">
            intent <b>{res.intent_type}</b> · parser <b>{res.parser}</b> ·{' '}
            {res.hits.length} ảnh · {res.total_ms} ms
          </div>
          <FacetChips facets={res.facets} onPick={run} />
          <ResultGrid hits={res.hits} />
          <div className="timings">
            <b>timings</b>:{' '}
            {Object.entries(res.timings_ms).map(([k, v]) => (
              <span key={k}><code>{k}</code> {Math.round(v)}ms </span>
            ))}
            <span>· <code>total</code> {res.total_ms}ms</span>
          </div>
        </>
      )}
      {!res && !err && <div className="empty">
        Nhập truy vấn để bắt đầu. Thử: “Quần thể Tràng An”, “hồ bơi và công viên nước ở Phú Quốc”,
        “những con vật sống trong rừng”.
      </div>}
    </>
  );
}
