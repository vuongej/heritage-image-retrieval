import * as Tabs from '@radix-ui/react-tabs';
import { Lightbulb, MapPin, X } from 'lucide-react';
import { fmtInt, sentenceCase, titleCase } from '@/lib/format';
import type { IntentGroup, LocationConstraint } from '@/types/search';
import { cn, Tip } from '@/components/shared/ui';

export function IntentChip({ intent, index, onRemove }: { intent: IntentGroup; index: number; onRemove?: () => void }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-violet-200 bg-violet-50 py-0.5 pl-2.5 pr-1 text-[13px] text-violet-900">
      <span className="grid size-4 place-items-center rounded-full bg-q-multi font-mono text-[10px] font-semibold text-white">{index + 1}</span>
      <span className="font-medium">{sentenceCase(intent.text)}</span>
      <span className="font-mono text-caption text-violet-700">{fmtInt(intent.images.length)} ảnh</span>
      {onRemove ? (
        <button
          type="button"
          onClick={onRemove}
          className="rounded-full p-0.5 text-violet-700 hover:bg-violet-100"
          aria-label={`Bỏ ý định “${intent.text}” và tìm lại`}
        >
          <X aria-hidden className="size-3.5" />
        </button>
      ) : (
        <span className="w-1" />
      )}
    </span>
  );
}

export function ConstraintChip({ constraint }: { constraint: LocationConstraint }) {
  return (
    <Tip
      content={
        constraint.derived
          ? 'Suy ra từ sub-query backend trả về: mọi ý định đều kết thúc bằng cùng cụm địa điểm. Backend gộp điều kiện vào văn bản từng sub-query, không trả trường constraint riêng.'
          : 'Điều kiện do backend trả về.'
      }
    >
      <span tabIndex={0} className="inline-flex items-center gap-1.5 rounded-full border border-teal-200 bg-teal-50 px-2.5 py-0.5 text-[13px] text-teal-900">
        <MapPin aria-hidden className="size-3.5" />
        <span className="font-medium">{titleCase(constraint.label)}</span>
        <span className="text-caption text-teal-700">· áp dụng cho mọi ý định</span>
      </span>
    </Tip>
  );
}

export type IntentView = 'grouped' | 'merged' | 'all';

/** "Phải đáp ứng cả hai" stays disabled: the backend has no per-image conjunction. */
export function IntentModeSwitch({ value, onChange }: { value: IntentView; onChange: (v: IntentView) => void }) {
  const tab = 'rounded-md px-3 py-1.5 text-[13px] font-medium text-muted data-[state=active]:bg-surface data-[state=active]:text-text data-[state=active]:shadow-sm';
  return (
    <Tabs.Root value={value} onValueChange={(v) => onChange(v as IntentView)}>
      <Tabs.List aria-label="Cách hiển thị kết quả nhiều ý định" className="inline-flex flex-wrap gap-1 rounded-lg bg-slate-100 p-1">
        <Tip content="Mỗi ý định một nhóm (OR theo nhóm). Ảnh thuộc nhóm theo matched_subqueries của backend.">
          <Tabs.Trigger value="grouped" className={tab}>
            Theo ý định
          </Tabs.Trigger>
        </Tip>
        <Tip content="Gộp tất cả, mỗi image_id xuất hiện một lần, giữ đủ các ý định mà ảnh khớp.">
          <Tabs.Trigger value="merged" className={tab}>
            Gộp tất cả
          </Tabs.Trigger>
        </Tip>
        <Tip content="Backend chưa hỗ trợ khớp đồng thời mọi ý định trên cùng một ảnh (AND).">
          <span tabIndex={0}>
            <Tabs.Trigger value="all" disabled className={cn(tab, 'cursor-not-allowed opacity-50')}>
              Phải đáp ứng cả hai
            </Tabs.Trigger>
          </span>
        </Tip>
      </Tabs.List>
    </Tabs.Root>
  );
}

export function MultiIntentSummary({
  intents,
  locations,
  onRemove,
}: {
  intents: IntentGroup[];
  locations: LocationConstraint[];
  onRemove?: (id: string) => void;
}) {
  return (
    <div className="space-y-2 rounded-[var(--radius-card)] border border-border bg-surface p-3">
      <p className="flex items-center gap-1.5 text-[13px] font-semibold">
        <Lightbulb aria-hidden className="size-4 text-q-multi" />
        Hệ thống phát hiện {intents.length} ý định
      </p>
      <div className="flex flex-wrap gap-2">
        {intents.map((it, i) => (
          <IntentChip key={it.id} intent={it} index={i} onRemove={onRemove && intents.length > 1 ? () => onRemove(it.id) : undefined} />
        ))}
      </div>
      {locations.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-caption font-medium uppercase leading-[1.4] tracking-wide text-muted">Điều kiện áp dụng</span>
          {locations.map((c) => (
            <ConstraintChip key={c.label} constraint={c} />
          ))}
        </div>
      )}
    </div>
  );
}
