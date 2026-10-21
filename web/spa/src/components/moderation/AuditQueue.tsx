import { Lock } from 'lucide-react';
import { useState } from 'react';
import type { AuditQueue as Queue } from '@/api/metricsAdapter';
import { API_BASE } from '@/config';
import { fmtInt } from '@/lib/format';
import { safeApiPath } from '@/lib/url';
import { CapabilityNotice } from '@/components/shared/states';
import { Mono } from '@/components/shared/ui';

function AuditThumb({ src, alt }: { src?: string; alt: string }) {
  const [failed, setFailed] = useState(false);
  if (!src || failed) return <div className="grid size-14 place-items-center rounded bg-slate-100 text-[10px] text-muted">không có</div>;
  return <img src={src} alt={alt} loading="lazy" width={56} height={56} onError={() => setFailed(true)} className="size-14 rounded object-cover" />;
}

/** Read-only: POST /v1/verify/label exists but the API has no reviewer authorization. */
export function AuditQueue({ q }: { q: Queue }) {
  return (
    <div className="space-y-3">
      <p className="text-[13px]">
        Hàng đợi gán nhãn mù: <span className="font-semibold tabular">{fmtInt(q.total)}</span> ảnh ({Object.entries(q.by_stratum).map(([k, v]) => `${k} ${fmtInt(v)}`).join(' · ')}), đã gán{' '}
        <span className="font-semibold tabular">{fmtInt(q.labelled)}</span>. Dự đoán của mô hình không được gửi xuống trang để nhãn người độc lập.
      </p>
      <CapabilityNotice tone="unsupported" title="Chưa tích hợp thao tác duyệt">
        <span className="inline-flex items-center gap-1">
          <Lock aria-hidden className="size-3.5" /> API chỉ có một key dev chung, chưa phân quyền reviewer — nút gán nhãn bị tắt trên trang này.
        </span>{' '}
        Gán nhãn nội bộ dùng công cụ <Mono>/ui</Mono> của backend.
      </CapabilityNotice>
      <div className="overflow-x-auto rounded-[var(--radius-card)] border border-border">
        <table className="w-full min-w-[640px] text-table">
          <thead className="bg-slate-50 text-left text-caption uppercase tracking-wide text-muted">
            <tr>
              <th className="px-3 py-2 font-medium">Ảnh</th>
              <th className="px-3 py-2 font-medium">Thực thể · nhóm</th>
              <th className="px-3 py-2 font-medium">Tầng mẫu</th>
              <th className="px-3 py-2 font-medium">Nhãn người</th>
              <th className="px-3 py-2 font-medium">Khoá</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {q.items.map((it) => (
              <tr key={it.key} className="align-top">
                <td className="px-3 py-2">
                  <AuditThumb src={safeApiPath(it.thumb, API_BASE)} alt={it.entity ?? 'Ảnh audit'} />
                </td>
                <td className="px-3 py-2">
                  <p className="font-medium">{it.entity ?? '—'}</p>
                  <p className="line-clamp-2 text-caption text-muted">{it.category}</p>
                </td>
                <td className="px-3 py-2">
                  <Mono>{it.stratum}</Mono>
                </td>
                <td className="px-3 py-2">{it.human ? <Mono>{it.human}</Mono> : <span className="text-muted">chưa gán</span>}</td>
                <td className="px-3 py-2">
                  <Mono className="text-muted">{it.key.slice(0, 10)}…</Mono>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
