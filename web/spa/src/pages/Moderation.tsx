import { lazy, Suspense } from 'react';
import { AuditQueue } from '@/components/moderation/AuditQueue';
import { PipelineFlow } from '@/components/moderation/PipelineFlow';
import { DataSourceBadge, GateBadge } from '@/components/shared/badges';
import { StatCard } from '@/components/shared/StatCard';
import { CapabilityNotice, EmptyState, ErrorState, NotMeasured } from '@/components/shared/states';
import { Card, Mono, SectionTitle } from '@/components/shared/ui';
import { DATA_MODE } from '@/config';
import { useAuditQueue, useVerify } from '@/hooks/queries';
import { fmtDateTime, fmtDec, fmtInt, fmtPct } from '@/lib/format';
import type { VerifyReport } from '@/api/metricsAdapter';

const RiskCoverageChart = lazy(() => import('@/components/moderation/RiskCoverageChart').then((m) => ({ default: m.RiskCoverageChart })));

function Kpis({ r }: { r: VerifyReport }) {
  const flag = r.approved_flag_eval;
  const falseReject = flag.accuracy_cascade !== undefined && flag.accuracy_cascade !== null ? 1 - flag.accuracy_cascade : undefined;
  const gateRate = r.seconds.S0_gate ? r.gate.source_rows / r.seconds.S0_gate : undefined;
  const cached = (r.cost.jev_this_run.requests ?? 0) === 0;
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <StatCard
        label="Ảnh đã xử lý"
        value={fmtInt(r.gate.source_rows)}
        unit="dòng qua gate"
        provenance="ACTUAL"
        footnote={`Pilot ${fmtInt(r.pilot_rows)} dòng (${fmtInt(r.pilot_groups)} nhóm) đi qua tải ảnh + mô hình; đánh giá trên ${fmtInt(r.cascade_proxy.rows)} ảnh tập ${r.target_split}.`}
      >
        Sống sau gate: <span className="font-semibold">{fmtInt(r.gate.live_rows)}</span> · loại theo rule {fmtInt(r.gate.rejected_rows)}
      </StatCard>
      <StatCard
        label="Thông lượng"
        value={cached ? <NotMeasured>Chưa đo</NotMeasured> : '—'}
        provenance={cached ? undefined : 'ACTUAL'}
        footnote="Lần chạy này dùng lại cache (tải ảnh 0,03 s, Jev 0 request) nên thời gian không đại diện cho pipeline đầy đủ."
      >
        Chỉ stage S0 (rule trên metadata, không tải ảnh): <span className="font-mono tabular">{fmtInt(gateRate)}</span> dòng/s.
      </StatCard>
      <StatCard
        label="Chi phí / 1.000 ảnh"
        value={<NotMeasured>Chưa đo</NotMeasured>}
        footnote={r.cost.cache_note ? `Ghi chú báo cáo: ${r.cost.cache_note}.` : undefined}
      >
        Lần chạy: Jev {fmtInt(r.cost.jev_this_run.requests)} request, {fmtDec(r.cost.jev_this_run.usd, 4)} USD; DeepSeek ước tính {fmtDec(r.cost.deepseek_usd_estimate, 4)} USD. Cần một lần chạy không cache với phạm vi chi phí xác định.
      </StatCard>
      <StatCard
        label="Chất lượng kiểm duyệt"
        value={fmtPct(falseReject)}
        unit="loại nhầm"
        provenance="ACTUAL"
        footnote={`So với cột flag do người duyệt trong CSV: n = ${fmtInt(flag.rows)}, tất cả là approved (rejected = ${fmtInt(flag.rejected)}) ⇒ chỉ đo được loại nhầm (${flag.measurable ?? 'false-reject only'}); precision/recall cần nhãn người có cả lớp âm.`}
      >
        Đồng thuận với VLM thầy (proxy, không phải accuracy): <span className="font-semibold">{fmtPct(r.cascade_proxy.agreement_all)}</span>
      </StatCard>
    </div>
  );
}

function ScalePanel() {
  return (
    <Card className="p-4">
      <SectionTitle aside={<DataSourceBadge kind="ESTIMATE" note="Chưa tính vì thiếu số đo đầu vào." />}>Lộ trình 10–100 triệu ảnh</SectionTitle>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-2 text-[13px] leading-relaxed">
          <p>Công thức ngoại suy (chỉ là lý thuyết, không đo được nút cổ chai phân tán):</p>
          <ul className="space-y-1 font-mono text-[12.5px]">
            <li>thời gian = N ảnh / thông lượng duy trì (ảnh/s)</li>
            <li>chi phí = N / 1.000 × chi phí đo được / 1.000 ảnh</li>
          </ul>
          <p className="text-muted">Giả định cần ghi: số worker, GPU, băng thông tải ảnh, tỉ lệ lỗi/thử lại, đuôi chậm, tỉ lệ chuyển VLM (α), giá token tại thời điểm đo.</p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[320px] text-table">
            <thead className="text-left text-caption uppercase tracking-wide text-muted">
              <tr>
                <th className="py-1.5 font-medium">Quy mô</th>
                <th className="py-1.5 font-medium">Thời gian</th>
                <th className="py-1.5 font-medium">Chi phí</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {['10.000.000', '100.000.000'].map((n) => (
                <tr key={n}>
                  <td className="py-2 font-mono">{n}</td>
                  <td className="py-2">
                    <NotMeasured>cần thông lượng đo</NotMeasured>
                  </td>
                  <td className="py-2">
                    <NotMeasured>cần chi phí/1k đo</NotMeasured>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </Card>
  );
}

function Breakdown({ title, rows }: { title: string; rows: VerifyReport['by_category'] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[360px] text-table">
        <caption className="mb-1 text-left text-[13px] font-semibold">{title}</caption>
        <thead className="text-left text-caption uppercase tracking-wide text-muted">
          <tr>
            <th className="py-1.5 font-medium">Nhóm</th>
            <th className="py-1.5 pl-3 text-right font-medium">n</th>
            <th className="py-1.5 pl-3 text-right font-medium">Tỉ lệ yes</th>
            <th className="py-1.5 pl-3 text-right font-medium">Đồng thuận*</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.slice(0, 10).map((b) => (
            <tr key={b.key}>
              <td className="max-w-[220px] py-1.5 pr-2">{b.key}</td>
              <td className="py-1.5 pl-3 text-right font-mono tabular">{fmtInt(b.n)}</td>
              <td className="py-1.5 text-right font-mono tabular">{fmtPct(b.yes_rate)}</td>
              <td className="py-1.5 text-right font-mono tabular">{fmtPct(b.agreement)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StageSeconds({ r }: { r: VerifyReport }) {
  const rows = Object.entries(r.seconds).filter(([k]) => k !== 'total');
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[300px] text-table">
        <caption className="mb-1 text-left text-[13px] font-semibold">Thời gian từng stage (giây, lần chạy dùng cache)</caption>
        <tbody className="divide-y divide-border">
          {rows.map(([k, v]) => (
            <tr key={k}>
              <td className="py-1.5 font-mono">{k}</td>
              <td className="py-1.5 text-right font-mono tabular">{fmtDec(v, 2)}</td>
            </tr>
          ))}
          <tr>
            <td className="py-1.5 font-semibold">Tổng</td>
            <td className="py-1.5 text-right font-mono font-semibold tabular">{fmtDec(r.seconds.total, 2)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

export default function ModerationPage() {
  const verify = useVerify();
  const audit = useAuditQueue();
  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-h1 font-semibold tracking-tight">Kiểm duyệt ảnh sau crawl — Phần A</h1>
        <p className="max-w-3xl text-muted">
          Số liệu đọc từ báo cáo pipeline verify thật (<Mono>reports/verify/report.json</Mono>). Ô nào chưa có phép đo hợp lệ hiển thị “Chưa đo”.
        </p>
      </header>

      {DATA_MODE === 'mock' && <EmptyState title="Chưa có số liệu xử lý thực tế">Chế độ mock không tạo số liệu kiểm duyệt.</EmptyState>}
      {verify.isPending && DATA_MODE === 'live' && <div className="skeleton h-40 rounded-lg" />}
      {verify.isError && (
        <div className="space-y-3">
          <ErrorState error={verify.error} onRetry={() => verify.refetch()} />
          <CapabilityNotice title="Cách tạo báo cáo">
            Chạy <Mono>python -X utf8 -m pipeline.verify</Mono> để sinh <Mono>reports/verify/report.json</Mono>.
          </CapabilityNotice>
        </div>
      )}

      {verify.data && (
        <>
          <p className="flex flex-wrap items-center gap-2 text-caption text-muted">
            <DataSourceBadge kind="ACTUAL" />
            <span>
              Báo cáo <Mono>{verify.data.meta.path}</Mono> · cập nhật {fmtDateTime(verify.data.meta.modified_at)} · sha256 <Mono>{verify.data.meta.sha256.slice(0, 12)}</Mono> · CSV{' '}
              <Mono>{verify.data.data.csv}</Mono> · seed {verify.data.data.seed}
            </span>
          </p>
          {verify.data.data.proxy_warning && (
            <CapabilityNotice tone="warn" title="Đọc đúng chỉ số proxy">
              {verify.data.data.proxy_warning}
            </CapabilityNotice>
          )}
          <Kpis r={verify.data.data} />

          <section aria-labelledby="flow-title">
            <SectionTitle id="flow-title">Luồng xử lý và khối lượng từng stage</SectionTitle>
            <PipelineFlow r={verify.data.data} />
          </section>

          <section aria-labelledby="quality-title" className="grid gap-4 lg:grid-cols-2">
            <Card className="p-4">
              <SectionTitle id="quality-title" aside={<DataSourceBadge kind="ACTUAL" note="Proxy so với nhãn VLM bootstrap." />}>
                Risk–coverage (proxy)
              </SectionTitle>
              <Suspense fallback={<div className="skeleton h-64 rounded" />}>
                <RiskCoverageChart r={verify.data.data} />
              </Suspense>
            </Card>
            <Card className="space-y-4 p-4">
              <SectionTitle>Độ chính xác so với nhãn người (cột flag)</SectionTitle>
              <table className="w-full text-table">
                <tbody className="divide-y divide-border">
                  {(['accuracy_vlm_teacher', 'accuracy_head', 'accuracy_jev', 'accuracy_cascade'] as const).map((k) => (
                    <tr key={k}>
                      <td className="py-1.5 font-mono">{k}</td>
                      <td className="py-1.5 text-right font-mono tabular">{fmtPct(verify.data.data.approved_flag_eval[k])}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="text-caption text-muted">
                n = {fmtInt(verify.data.data.approved_flag_eval.rows)}; mọi ảnh trong mẫu đều approved nên đây là tỉ lệ giữ đúng. Nhãn người bổ sung:{' '}
                {String((verify.data.data.human_eval as { status?: string }).status ?? '—')}
              </p>
              <GateBadge status="PARTIAL" /> <span className="text-caption text-muted">Gate PROCESSING: thiếu precision/recall theo lớp lỗi, throughput và chi phí đo không cache.</span>
            </Card>
          </section>

          <section className="grid gap-4 lg:grid-cols-3">
            <Card className="p-4">
              <Breakdown title="Theo category (top 10)" rows={verify.data.data.by_category} />
            </Card>
            <Card className="p-4">
              <Breakdown title="Theo host ảnh (top 10)" rows={verify.data.data.by_host} />
            </Card>
            <Card className="p-4">
              <StageSeconds r={verify.data.data} />
            </Card>
          </section>
          <p className="text-caption text-muted">* Đồng thuận = proxy với nhãn VLM bootstrap, không phải accuracy.</p>
          <ScalePanel />
        </>
      )}

      {DATA_MODE === 'live' && (
        <section aria-labelledby="queue-title">
          <SectionTitle id="queue-title">Hàng đợi gán nhãn người</SectionTitle>
          {audit.isPending && <div className="skeleton h-32 rounded-lg" />}
          {audit.isError && <ErrorState error={audit.error} onRetry={() => audit.refetch()} />}
          {audit.data && <AuditQueue q={audit.data} />}
        </section>
      )}
    </div>
  );
}
