import * as Tabs from '@radix-ui/react-tabs';
import { lazy, Suspense, useState } from 'react';
import { Link } from 'react-router-dom';
import type { IndexCounts, LatencyReport, LatencyRun, QualityReport, RerankAb, Stats } from '@/api/metricsAdapter';
import { DataSourceBadge, GateBadge } from '@/components/shared/badges';
import { DownloadReport } from '@/components/shared/DownloadReport';
import { CapabilityNotice, EmptyState, ErrorState, NotMeasured } from '@/components/shared/states';
import { Card, Mono, SectionTitle } from '@/components/shared/ui';
import { DATA_MODE, REQUIRED_IMAGES, SLA_MS } from '@/config';
import { useIndexCounts, useLatency, useQuality, useRerankAb, useStats } from '@/hooks/queries';
import { DASH, fmtDateTime, fmtDec, fmtInt, fmtMs, fmtPct } from '@/lib/format';
import { slaGate, type GateStatus } from '@/lib/sla';

const LatencyChart = lazy(() => import('@/components/benchmark/LatencyChart').then((m) => ({ default: m.LatencyChart })));

// Kinds used by scripts/eval_latency.py mapped onto the assignment's query classes.
const KIND_TYPE: Record<string, { type: string; label: string }> = {
  entity: { type: 'SINGLE', label: 'entity — tên thực thể' },
  regression: { type: 'SINGLE', label: 'regression — 104 truy vấn hồi quy' },
  set: { type: 'SINGLE (SET_QUERY)', label: 'set — truy vấn tập hợp' },
  multi: { type: 'MULTI_INTENT', label: 'multi — nhiều ý định' },
};

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return <th className={`px-3 py-2 font-medium ${right ? 'text-right' : ''}`}>{children}</th>;
}
function Td({ children, right, mono }: { children: React.ReactNode; right?: boolean; mono?: boolean }) {
  return <td className={`px-3 py-2 ${right ? 'text-right' : ''} ${mono ? 'font-mono tabular' : ''}`}>{children}</td>;
}

function breaches(run: LatencyRun) {
  if (run.under_3000ms === null || run.under_3000ms === undefined) return undefined;
  return Math.round(run.requests * (1 - run.under_3000ms));
}

// Per-kind rows have only p50/p95. Two deductions are exact: zero breaches overall means zero in
// every kind; a kind p95 at/above the SLA means at least 5% of that kind breached.
function kindGate(total: number | undefined, p95: number | null | undefined): GateStatus {
  if (total === 0) return 'PASS';
  if (p95 !== null && p95 !== undefined && p95 >= SLA_MS) return 'FAIL';
  return 'NOT_MEASURED';
}

function kindBreach(total: number | undefined, p95: number | null | undefined): string {
  if (total === 0) return '0 (suy từ tổng = 0)';
  if (p95 !== null && p95 !== undefined && p95 >= SLA_MS) return '≥ 5% (suy từ p95)';
  return DASH;
}

// ---------------------------------------------------------------- DATA gate
function DataGate({ stats, counts }: { stats?: Stats; counts?: IndexCounts }) {
  const points = stats?.img_text.available ? stats.img_text.points ?? undefined : undefined;
  const sqlite = stats?.catalog.images;
  const mismatch = points !== undefined && sqlite !== undefined && points !== sqlite;
  const status: GateStatus = points === undefined ? 'NOT_MEASURED' : points >= REQUIRED_IMAGES && !mismatch ? 'PASS' : 'FAIL';
  return (
    <Card className="p-4">
      <SectionTitle aside={<GateBadge status={status} />}>Dữ liệu: ≥ {fmtInt(REQUIRED_IMAGES)} ảnh index và truy xuất được</SectionTitle>
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <p className="mb-1 flex items-center gap-2 text-[13px] font-semibold">
            Live <Mono className="text-muted">GET /v1/stats</Mono> {stats && <DataSourceBadge kind="ACTUAL" note={`Đo lúc ${fmtDateTime(stats.measured_at)}.`} />}
          </p>
          {stats ? (
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-[13px]">
              <dt className="text-muted">Ảnh trong SQLite</dt>
              <dd className="font-mono tabular">{fmtInt(sqlite)}</dd>
              <dt className="text-muted">Point Qdrant img_text</dt>
              <dd className="font-mono tabular">{stats.img_text.available ? fmtInt(points) : `không đọc được (${stats.img_text.reason ?? '—'})`}</dd>
              <dt className="text-muted">Manifest vector</dt>
              <dd className="font-mono tabular">
                {fmtInt(stats.manifest.indexed_count)}/{fmtInt(stats.manifest.count)} {stats.manifest.complete ? '(hoàn tất)' : '(chưa hoàn tất)'}
              </dd>
              <dt className="text-muted">Visual img_visual</dt>
              <dd>{stats.img_visual.available ? fmtInt(stats.img_visual.points) : 'không tồn tại'}</dd>
              <dt className="text-muted">Quan hệ KG có nguồn</dt>
              <dd className="font-mono tabular">{fmtInt(stats.knowledge_graph.kg_relations)}</dd>
            </dl>
          ) : (
            <NotMeasured>Không đọc được /v1/stats</NotMeasured>
          )}
        </div>
        <div>
          <p className="mb-1 flex items-center gap-2 text-[13px] font-semibold">
            Báo cáo <Mono className="text-muted">reports/v2/index_counts.json</Mono> {counts && <DataSourceBadge kind="ACTUAL" />}
          </p>
          {counts ? (
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-[13px]">
              <dt className="text-muted">Dòng CSV / hợp lệ</dt>
              <dd className="font-mono tabular">
                {fmtInt(counts.csv_rows)} / {fmtInt(counts.csv_valid_rows)}
              </dd>
              <dt className="text-muted">Indexed (SQLite ↔ Qdrant khớp)</dt>
              <dd className="font-mono tabular">{fmtInt(counts.indexed_images)}</dd>
              <dt className="text-muted">Yêu cầu</dt>
              <dd className="font-mono tabular">{fmtInt(counts.require)}</dd>
              <dt className="text-muted">Vấn đề</dt>
              <dd>{counts.problems.length ? counts.problems.join('; ') : 'không'}</dd>
            </dl>
          ) : (
            <NotMeasured>Chưa có báo cáo đếm index</NotMeasured>
          )}
        </div>
      </div>
      {mismatch && (
        <CapabilityNotice tone="warn" title="SQLite và Qdrant không cùng số ảnh" className="mt-3">
          Point id của Qdrant là <Mono>rownum</Mono> của SQLite: khi hai bên lệch nhau, nhánh dense có thể trỏ sai ảnh. Chạy lại{' '}
          <Mono>python -m scripts.check_index_counts --require 80000</Mono> sau khi reindex xong.
        </CapabilityNotice>
      )}
      {points !== undefined && points < REQUIRED_IMAGES && (
        <p className="mt-2 text-caption text-red-700">
          {fmtInt(points)} &lt; {fmtInt(REQUIRED_IMAGES)}: chưa đạt yêu cầu tối thiểu, thiếu {fmtInt(REQUIRED_IMAGES - points)} ảnh.
        </p>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- latency
function LatencyRunView({ run }: { run: LatencyRun }) {
  const total = breaches(run);
  const kinds = Object.entries(run.by_kind);
  return (
    <div className="space-y-4">
      <div className="overflow-x-auto rounded-[var(--radius-card)] border border-border">
        <table className="w-full min-w-[860px] text-table">
          <thead className="bg-slate-50 text-left text-caption uppercase tracking-wide text-muted">
            <tr>
              <Th>Loại truy vấn</Th>
              <Th right>n</Th>
              <Th right>p50</Th>
              <Th right>p95</Th>
              <Th right>p99</Th>
              <Th right>max</Th>
              <Th right>Vi phạm ≥ 3.000 ms</Th>
              <Th right>Lỗi</Th>
              <Th>SLA</Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            <tr className="bg-brand-50/50 font-medium">
              <Td>Tất cả (trộn)</Td>
              <Td right mono>{fmtInt(run.requests)}</Td>
              <Td right mono>{fmtMs(run.p50)}</Td>
              <Td right mono>{fmtMs(run.p95)}</Td>
              <Td right mono>{fmtMs(run.p99)}</Td>
              <Td right mono>{fmtMs(run.max)}</Td>
              <Td right mono>
                {total === undefined ? DASH : `${fmtInt(total)} (${fmtPct(1 - (run.under_3000ms ?? 0))})`}
              </Td>
              <Td right mono>{fmtInt(run.errors)}</Td>
              <Td>
                <GateBadge status={slaGate(run.requests, run.under_3000ms ?? undefined)} />
              </Td>
            </tr>
            {kinds.map(([kind, v]) => (
              <tr key={kind}>
                <Td>
                  <span className="font-mono text-[12px] text-muted">{KIND_TYPE[kind]?.type ?? kind}</span>
                  <span className="block">{KIND_TYPE[kind]?.label ?? kind}</span>
                </Td>
                <Td right mono>{DASH}</Td>
                <Td right mono>{fmtMs(v.p50)}</Td>
                <Td right mono>{fmtMs(v.p95)}</Td>
                <Td right mono>{DASH}</Td>
                <Td right mono>{DASH}</Td>
                <Td right mono>{kindBreach(total, v.p95)}</Td>
                <Td right mono>{DASH}</Td>
                <Td>
                  <GateBadge status={kindGate(total, v.p95)} />
                </Td>
              </tr>
            ))}
            <tr>
              <Td>
                <span className="font-mono text-[12px] text-muted">MULTI_HOP</span>
                <span className="block">nhiều bước</span>
              </Td>
              {Array.from({ length: 6 }, (_, i) => (
                <Td key={i} right mono>
                  {DASH}
                </Td>
              ))}
              <Td right mono>{DASH}</Td>
              <Td>
                <GateBadge status="NOT_MEASURED" />
              </Td>
            </tr>
          </tbody>
        </table>
      </div>
      <p className="text-caption text-muted">
        Quy tắc PASS: n &gt; 0 và 100% request &lt; {fmtInt(SLA_MS)} ms (đúng 3.000 ms tính là vi phạm). p95 đạt không đủ để kết luận PASS. Báo cáo không ghi n/max theo
        từng nhóm ⇒ “—”.
      </p>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,360px)]">
        <Card className="p-4">
          <Suspense fallback={<div className="skeleton h-64 rounded" />}>
            <LatencyChart rows={kinds.map(([kind, v]) => ({ kind, p50: v.p50, p95: v.p95 }))} />
          </Suspense>
        </Card>
        <Card className="space-y-3 p-4">
          <p className="text-[13px] font-semibold">Phân rã stage (p50 / p95)</p>
          <table className="w-full text-table">
            <tbody className="divide-y divide-border">
              {Object.keys(run.stage_p50).map((s) => (
                <tr key={s}>
                  <td className="py-1.5 font-mono">{s}</td>
                  <td className="py-1.5 text-right font-mono tabular">
                    {fmtMs(run.stage_p50[s])} / {fmtMs(run.stage_p95[s])}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <dl className="grid grid-cols-2 gap-y-1 border-t border-border pt-2 text-[13px]">
            <dt className="text-muted">Thông lượng đạt</dt>
            <dd className="text-right font-mono tabular">{fmtDec(run.throughput_qps, 2)} req/s</dd>
            <dt className="text-muted">Thời gian đo</dt>
            <dd className="text-right font-mono tabular">{fmtDec(run.wall_seconds, 1)} s</dd>
            <dt className="text-muted">&lt; 1.500 ms (SLO nội bộ)</dt>
            <dd className="text-right font-mono tabular">{fmtPct(run.under_1500ms)}</dd>
            <dt className="text-muted">Cảnh báo 429 / suy giảm</dt>
            <dd className="text-right font-mono tabular">
              {fmtInt(run.warnings_429)} / {fmtInt(run.warnings_degraded)}
            </dd>
          </dl>
          <p className="text-caption text-muted">
            Parser: {Object.entries(run.parsers).map(([k, v]) => `${k} ${fmtInt(v)}`).join(' · ')}
          </p>
        </Card>
      </div>
    </div>
  );
}

function LatencySection({ report, livePoints }: { report: { meta: { path: string; modified_at?: string; sha256: string; id: string }; data: LatencyReport }; livePoints?: number }) {
  const runs = Object.entries(report.data.runs);
  const [run, setRun] = useState(runs[0]?.[0] ?? '');
  const env = report.data.environment as Record<string, unknown>;
  const measuredOn = typeof env.index_count === 'number' ? env.index_count : undefined;
  const stale = measuredOn !== undefined && livePoints !== undefined && measuredOn !== livePoints;
  return (
    <Card className="space-y-4 p-4">
      <SectionTitle
        aside={
          <span className="flex items-center gap-2">
            <DataSourceBadge kind="ACTUAL" />
            <DownloadReport id={report.meta.id} sha256={report.meta.sha256} data={report.data} />
          </span>
        }
      >
        Latency theo loại truy vấn
      </SectionTitle>
      <dl className="grid gap-x-6 gap-y-1 text-[13px] sm:grid-cols-2 lg:grid-cols-3">
        {[
          ['Báo cáo', `${report.meta.path} · ${fmtDateTime(report.meta.modified_at)}`],
          ['sha256', report.meta.sha256.slice(0, 16)],
          ['Máy', `${String(env.machine ?? '—')} · ${String(env.gpu ?? '—')}`],
          ['Index', `${String(env.index_model ?? '—')} · ${fmtInt(env.index_count as number)} ảnh · ${String(env.vector_backend ?? '—')}`],
          ['Rerank / parse', `${Array.isArray(env.rerank) ? env.rerank.join(' ') : '—'} · ${String(env.parse_mode ?? '—')}`],
          ['Cache · tải', `${report.data.cache_state ?? '—'} · ${fmtInt(report.data.offered_rpm)} req/phút`],
          ['Pipeline', String(env.pipeline_version ?? '—')],
          ['Git SHA', 'không có (repo chưa có git)'],
        ].map(([k, v]) => (
          <div key={k} className="flex gap-2">
            <dt className="shrink-0 text-muted">{k}:</dt>
            <dd className="min-w-0 break-words font-mono text-[12px]">{v}</dd>
          </div>
        ))}
      </dl>
      {stale && (
        <CapabilityNotice tone="warn" title="Báo cáo được đo trên index khác index đang chạy">
          Lượt đo dùng index {fmtInt(measuredOn)} ảnh; index live hiện có {fmtInt(livePoints)} point. Kết luận SLA bên dưới chỉ áp dụng cho index cũ — cần chạy lại{' '}
          <Mono>scripts.eval_latency</Mono> trên index hiện tại.
        </CapabilityNotice>
      )}
      <CapabilityNotice title="Ranh giới phép đo">
        <Mono>scripts/eval_latency.py</Mono> gọi hàm <Mono>search()</Mono> trong cùng process và đo bằng <Mono>perf_counter</Mono>: không gồm HTTP, serialize hay mạng trình duyệt. Cache
        kết quả bị tắt (<Mono>{report.data.cache_state}</Mono>). Chưa có mẫu raw từng request trong báo cáo.
      </CapabilityNotice>
      <Tabs.Root value={run} onValueChange={setRun}>
        <Tabs.List aria-label="Chọn lượt đo" className="mb-3 inline-flex gap-1 rounded-lg bg-slate-100 p-1">
          {runs.map(([id]) => (
            <Tabs.Trigger
              key={id}
              value={id}
              className="rounded-md px-3 py-1.5 font-mono text-[12.5px] text-muted data-[state=active]:bg-surface data-[state=active]:text-text data-[state=active]:shadow-sm"
            >
              {id}
            </Tabs.Trigger>
          ))}
        </Tabs.List>
        {runs.map(([id, r]) => (
          <Tabs.Content key={id} value={id}>
            <LatencyRunView run={r} />
          </Tabs.Content>
        ))}
      </Tabs.Root>
    </Card>
  );
}

// ---------------------------------------------------------------- quality
function QualitySection({ report, ab }: { report?: { meta: { path: string; sha256: string; id: string; modified_at?: string }; data: QualityReport }; ab?: RerankAb }) {
  if (!report) return null;
  const s = report.data.summary;
  const e = s.entity ?? {};
  const m = s.multi_intent ?? {};
  const set = s.set_query ?? {};
  const rows: Array<[string, string, string, string]> = [
    ['SINGLE (entity)', fmtInt(e.cases), `Recall@10 ${fmtDec(e['recall@10'])} · Hit@10 ${fmtDec(e['hit@10'])} · nDCG@10 ${fmtDec(e['ndcg@10'])} · MRR ${fmtDec(e.mrr)}`, `Precision@10 ${fmtDec(e['precision@10'])} · rỗng ${fmtInt(e.empty)}`],
    ['SET_QUERY', fmtInt(set.cases), `Precision đúng lớp ${fmtDec(set.precision_exact_class)} · cùng nhóm ${fmtDec(set.precision_same_group)}`, `Thực thể khác nhau TB ${fmtDec(set.distinct_entities_mean, 2)}`],
    ['MULTI_INTENT', fmtInt(m.cases), `Phủ đủ mọi ý định ${fmtInt(m.all_intents_covered)}/${fmtInt(m.cases)} · precision ${fmtDec(m.precision)}`, `Parser nhận multi ${fmtInt(m.intent_multi)}/${fmtInt(m.cases)}`],
  ];
  return (
    <Card className="space-y-4 p-4">
      <SectionTitle
        aside={
          <span className="flex items-center gap-2">
            <DataSourceBadge kind="ACTUAL" note="Nhãn silver tự sinh từ catalog." />
            <DownloadReport id={report.meta.id} sha256={report.meta.sha256} data={report.data} />
          </span>
        }
      >
        Chất lượng truy xuất
      </SectionTitle>
      <CapabilityNotice tone="warn" title="Nhãn silver, không phải gold người">
        {s.label_type} — Recall được tính trên tập liên quan tự sinh (entity_id/category), nên là recall ước lượng.
      </CapabilityNotice>
      <div className="overflow-x-auto rounded-[var(--radius-card)] border border-border">
        <table className="w-full min-w-[720px] text-table">
          <thead className="bg-slate-50 text-left text-caption uppercase tracking-wide text-muted">
            <tr>
              <Th>Loại</Th>
              <Th right>n</Th>
              <Th>Chỉ số chính</Th>
              <Th>Phụ</Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map(([t, n, a, b]) => (
              <tr key={t}>
                <Td>
                  <span className="font-mono text-[12px]">{t}</span>
                </Td>
                <Td right mono>{n}</Td>
                <Td mono>{a}</Td>
                <Td mono>{b}</Td>
              </tr>
            ))}
            <tr>
              <Td>
                <span className="font-mono text-[12px]">MULTI_HOP</span>
              </Td>
              <Td right mono>{DASH}</Td>
              <Td>
                <GateBadge status="NOT_MEASURED" /> <span className="text-caption text-muted">KG chưa có quan hệ có nguồn để gán nhãn bằng chứng.</span>
              </Td>
              <Td>{DASH}</Td>
            </tr>
          </tbody>
        </table>
      </div>
      {ab && (
        <div className="overflow-x-auto rounded-[var(--radius-card)] border border-border">
          <table className="w-full min-w-[720px] text-table">
            <caption className="px-3 pt-3 text-left text-[13px] font-semibold">
              A/B reranker trên cùng pool đóng băng ({fmtInt(ab.cases)} truy vấn) — cùng điều kiện đầu vào
            </caption>
            <thead className="bg-slate-50 text-left text-caption uppercase tracking-wide text-muted">
              <tr>
                <Th>Backend</Th>
                <Th right>nDCG@10 entity</Th>
                <Th right>Hit@10</Th>
                <Th right>Multi phủ đủ</Th>
                <Th right>Set precision</Th>
                <Th right>Rerank p50 / p95</Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {Object.entries(ab.backends).map(([name, b]) => (
                <tr key={name}>
                  <Td>
                    <span className="font-medium">{name}</span>
                    <span className="block text-caption text-muted">{b.model}</span>
                  </Td>
                  <Td right mono>{fmtDec(b.metrics.entity?.['ndcg@10'])}</Td>
                  <Td right mono>{fmtDec(b.metrics.entity?.['hit@10'])}</Td>
                  <Td right mono>{fmtDec(b.metrics.multi?.both_covered)}</Td>
                  <Td right mono>{fmtDec(b.metrics.set?.['group_precision@10'])}</Td>
                  <Td right mono>
                    {fmtMs(b.rerank_ms.p50)} / {fmtMs(b.rerank_ms.p95)}
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

export default function BenchmarkPage() {
  const stats = useStats();
  const counts = useIndexCounts();
  const latency = useLatency();
  const quality = useQuality();
  const ab = useRerankAb();

  if (DATA_MODE === 'mock')
    return <EmptyState title="Chưa có báo cáo benchmark thực">Chế độ mock không hiển thị số đo. Chạy với DATA_MODE=live.</EmptyState>;

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-h1 font-semibold tracking-tight">Benchmark — bằng chứng hiệu năng & chất lượng</h1>
        <p className="max-w-3xl text-muted">
          Chỉ hiển thị số từ báo cáo đã chạy và endpoint live. Phương pháp đo: <Link to="/docs#method" className="font-medium text-brand-700 underline">Xem phương pháp đo</Link>.
        </p>
      </header>

      <DataGate stats={stats.data} counts={counts.data?.data} />

      {latency.isPending && <div className="skeleton h-64 rounded-lg" />}
      {latency.isError && (
        <div className="space-y-2">
          <ErrorState error={latency.error} onRetry={() => latency.refetch()} />
          <CapabilityNotice title="Chưa có báo cáo latency">
            Tạo lại: <Mono>python -X utf8 -m scripts.eval_latency</Mono> → <Mono>reports/v2/latency.json</Mono>.
          </CapabilityNotice>
        </div>
      )}
      {latency.data && (
        <LatencySection report={latency.data} livePoints={stats.data?.img_text.available ? stats.data.img_text.points ?? undefined : undefined} />
      )}

      {quality.isError && <ErrorState error={quality.error} onRetry={() => quality.refetch()} />}
      <QualitySection report={quality.data} ab={ab.data?.data} />

      <Card className="space-y-2 p-4">
        <SectionTitle aside={<GateBadge status="NOT_MEASURED" />}>Load test k6</SectionTitle>
        <p className="text-[13px]">
          Script <Mono>loadtest/loadtest.js</Mono> có sẵn (kịch bản theo loại truy vấn, ngưỡng p95) nhưng chưa có kết quả chạy trong <Mono>reports/</Mono>. Trang này không hiển
          thị RPS hay PASS cho tới khi có file raw + môi trường.
        </p>
        <pre className="overflow-x-auto rounded bg-slate-950 p-3 font-mono text-[12px] text-slate-100">
          k6 run loadtest/loadtest.js -e API_BASE=http://127.0.0.1:8000 -e TEST_API_KEY=… --out json=reports/loadtest/raw.json
        </pre>
      </Card>
    </div>
  );
}
