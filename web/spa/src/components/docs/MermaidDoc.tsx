import { useEffect, useId, useState } from 'react';
import { DataSourceBadge } from '@/components/shared/badges';
import { cn } from '@/components/shared/ui';

let ready: Promise<typeof import('mermaid').default> | null = null;
function loadMermaid() {
  ready ??= import('mermaid').then((m) => {
    m.default.initialize({
      startOnLoad: false,
      securityLevel: 'strict',
      theme: 'base',
      fontFamily: 'Be Vietnam Pro, Inter, sans-serif',
      themeVariables: {
        primaryColor: '#EEF2FF',
        primaryBorderColor: '#4F46E5',
        primaryTextColor: '#0F172A',
        lineColor: '#64748B',
        fontSize: '14px',
      },
    });
    return m.default;
  });
  return ready;
}

/** Lazy Mermaid render; on a parse error the diagram source is shown instead. */
export function MermaidDoc({ source, caption, kind }: { source: string; caption: string; kind: 'actual' | 'proposed' }) {
  const id = `m${useId().replace(/[^a-zA-Z0-9]/g, '')}`;
  const [svg, setSvg] = useState<string>();
  const [error, setError] = useState<string>();
  useEffect(() => {
    let alive = true;
    setSvg(undefined);
    setError(undefined);
    loadMermaid()
      .then((m) => m.render(id, source))
      .then((r) => alive && setSvg(r.svg))
      .catch((e: unknown) => alive && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      alive = false;
    };
  }, [id, source]);
  return (
    <figure className={cn('rounded-[var(--radius-card)] border bg-surface p-4', kind === 'proposed' ? 'border-dashed border-slate-400' : 'border-border')}>
      <div className="mb-2 flex justify-end">
        {kind === 'actual' ? <DataSourceBadge kind="ACTUAL" note="Khớp source/config đã khảo sát (docs/backend-inventory.md)." /> : <span className="rounded border border-slate-300 bg-slate-100 px-1.5 py-px font-mono text-[10.5px] font-semibold tracking-wider text-slate-700">ĐỀ XUẤT — CHƯA TRIỂN KHAI</span>}
      </div>
      {svg ? (
        // SVG produced by Mermaid (securityLevel strict) from the static source in this file.
        <div className="mermaid-host overflow-x-auto" dangerouslySetInnerHTML={{ __html: svg }} />
      ) : error ? (
        <div>
          <p className="mb-1 text-caption text-red-700">Không render được sơ đồ ({error.slice(0, 120)}). Mã nguồn:</p>
          <pre className="overflow-x-auto rounded bg-slate-950 p-3 font-mono text-[12px] text-slate-100">{source}</pre>
        </div>
      ) : (
        <div role="status" aria-label="Đang vẽ sơ đồ" className="skeleton h-48 rounded" />
      )}
      <figcaption className="mt-2 text-caption text-muted">{caption}</figcaption>
    </figure>
  );
}
