import type { Hit } from '@/lib/api';

export default function ResultGrid({ hits }: { hits: Hit[] }) {
  if (!hits.length) return <div className="empty">Chưa có kết quả.</div>;
  return (
    <div className="grid">
      {hits.map((h) => (
        <figure key={h.image_id} className="card">
          <img src={h.image_url} alt={h.leaf_label || h.entity_slug || h.image_id} loading="lazy" />
          <figcaption className="meta">
            <b>{h.leaf_label || h.entity_slug || '—'}</b>
            {h.query_type && <span className="badge">{h.query_type}</span>}
            <div>score {h.score.toFixed(3)}</div>
          </figcaption>
        </figure>
      ))}
    </div>
  );
}
