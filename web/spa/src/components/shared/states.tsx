import { AlertTriangle, Ban, Info, RefreshCw, SearchX, WifiOff } from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import { ApiError, errorCopy } from '@/api/backendClient';
import { Button, cn } from './ui';

export function SkeletonGrid({ count = 8 }: { count?: number }) {
  return (
    <div role="status" aria-label="Đang tải kết quả" className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="overflow-hidden rounded-[var(--radius-card)] border border-border bg-surface">
          <div className="skeleton aspect-[4/3]" />
          <div className="space-y-2 p-3">
            <div className="skeleton h-3.5 w-3/4 rounded" />
            <div className="skeleton h-3 w-1/2 rounded" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function EmptyState({ title, children, icon }: { title: string; children?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-[var(--radius-card)] border border-dashed border-border bg-surface px-6 py-10 text-center">
      <div className="text-muted">{icon ?? <SearchX aria-hidden className="size-8" />}</div>
      <p className="text-lead font-semibold">{title}</p>
      {children && <div className="max-w-xl text-body text-muted">{children}</div>}
    </div>
  );
}

function useCountdown(seconds?: number) {
  const [left, setLeft] = useState(seconds ?? 0);
  useEffect(() => {
    setLeft(seconds ?? 0);
    if (!seconds) return;
    const id = setInterval(() => setLeft((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(id);
  }, [seconds]);
  return left;
}

export function ErrorState({ error, onRetry, context }: { error: unknown; onRetry?: () => void; context?: string }) {
  const api = error instanceof ApiError ? error : undefined;
  const copy = api ? errorCopy[api.kind] : { title: 'Đã xảy ra lỗi', hint: error instanceof Error ? error.message : String(error) };
  const wait = useCountdown(api?.retryAfterSeconds);
  const Icon = api?.kind === 'network' ? WifiOff : AlertTriangle;
  return (
    <div role="alert" className="flex flex-col gap-2 rounded-[var(--radius-card)] border border-red-200 bg-red-50 p-4 text-red-900">
      <div className="flex items-center gap-2 font-semibold">
        <Icon aria-hidden className="size-4" />
        {copy.title}
        {api?.status && <span className="font-mono text-caption font-normal">HTTP {api.status}</span>}
      </div>
      <p className="text-body">{copy.hint}</p>
      {api?.detail && <p className="font-mono text-caption break-words">{api.detail}</p>}
      {context && <p className="text-caption">{context}</p>}
      <p className="text-caption">Chế độ live: lỗi được hiển thị nguyên trạng, không thay bằng dữ liệu minh họa.</p>
      {onRetry && (
        <div>
          <Button size="sm" onClick={onRetry} disabled={wait > 0}>
            <RefreshCw aria-hidden className="size-3.5" />
            {wait > 0 ? `Thử lại sau ${wait}s` : 'Thử lại'}
          </Button>
        </div>
      )}
    </div>
  );
}

type NoticeTone = 'info' | 'warn' | 'unsupported';
export function CapabilityNotice({ tone = 'info', title, children, className }: { tone?: NoticeTone; title: string; children?: ReactNode; className?: string }) {
  const Icon = tone === 'unsupported' ? Ban : tone === 'warn' ? AlertTriangle : Info;
  return (
    <div
      role="note"
      className={cn(
        'flex gap-2.5 rounded-[var(--radius-card)] border p-3 text-body',
        tone === 'info' && 'border-brand-600/20 bg-brand-50 text-slate-800',
        tone === 'warn' && 'border-amber-300 bg-amber-50 text-amber-950',
        tone === 'unsupported' && 'border-slate-300 bg-slate-100 text-slate-800',
        className,
      )}
    >
      <Icon aria-hidden className="mt-0.5 size-4 shrink-0" />
      <div className="min-w-0">
        <p className="font-semibold">{title}</p>
        {children && <div className="mt-0.5 text-[13px] leading-relaxed">{children}</div>}
      </div>
    </div>
  );
}

/** Missing measurement — explicit, never a zero. */
export function NotMeasured({ children = 'Chưa có số đo' }: { children?: ReactNode }) {
  return <span className="text-muted italic">{children}</span>;
}
