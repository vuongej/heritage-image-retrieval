import { ImageOff, ShieldOff } from 'lucide-react';
import { useState } from 'react';
import { fmtDec } from '@/lib/format';
import type { ImageResult, ScoreKind } from '@/types/search';
import { ModerationBadge } from '@/components/shared/badges';
import { cn } from '@/components/shared/ui';

export const SCORE_KIND_LABEL: Record<ScoreKind, string> = {
  reranker: 'điểm reranker',
  cosine: 'cosine',
  rank: 'thứ hạng (không phải điểm liên quan)',
  other: 'điểm dự phòng',
};

/** Pixels are only requested for approved images; anything else gets a neutral placeholder. */
export function canRenderPixels(img: ImageResult): boolean {
  return img.moderation.status === 'approved' && Boolean(img.thumbnail_url);
}

export function PolicyPlaceholder({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex h-full w-full flex-col items-center justify-center gap-1.5 bg-slate-100 p-3 text-center text-muted">
      <ShieldOff aria-hidden className={compact ? 'size-5' : 'size-7'} />
      <span className="text-caption">Ảnh không hiển thị theo chính sách nội dung</span>
    </div>
  );
}

export function Thumb({ img, className, fit = 'cover' }: { img: ImageResult; className?: string; fit?: 'cover' | 'contain' }) {
  const [failed, setFailed] = useState(false);
  if (!canRenderPixels(img)) return <PolicyPlaceholder />;
  if (failed)
    return (
      <div className={cn('flex h-full w-full flex-col items-center justify-center gap-1.5 bg-slate-100 p-3 text-center text-muted', className)}>
        <ImageOff aria-hidden className="size-6" />
        <span className="text-caption">Không tải được ảnh từ {img.source_host ?? 'nguồn gốc'}</span>
      </div>
    );
  return (
    <img
      src={img.thumbnail_url}
      alt={img.caption ? `${img.entity_name ?? 'Ảnh'} — ${img.caption}` : img.entity_name ?? 'Ảnh kết quả'}
      loading="lazy"
      decoding="async"
      referrerPolicy="no-referrer"
      width={img.width ?? 400}
      height={img.height ?? 300}
      onError={() => setFailed(true)}
      className={cn(fit === 'cover' ? 'h-full w-full object-cover' : 'max-h-[80vh] w-auto object-contain', className)}
    />
  );
}

export function ImageCard({
  img,
  onOpen,
  highlighted = false,
  dimmed = false,
  intentLabels,
}: {
  img: ImageResult;
  onOpen: () => void;
  highlighted?: boolean;
  dimmed?: boolean;
  intentLabels?: string[];
}) {
  return (
    <article
      className={cn(
        'group flex h-full flex-col overflow-hidden rounded-[var(--radius-card)] border bg-surface transition-[box-shadow,opacity] duration-[180ms]',
        highlighted ? 'border-q-hop ring-2 ring-q-hop/40' : 'border-border hover:shadow-md',
        dimmed && 'opacity-45',
      )}
    >
      <button
        type="button"
        onClick={onOpen}
        className="relative block aspect-[4/3] w-full overflow-hidden bg-slate-100 text-left"
        aria-label={`Xem chi tiết ảnh ${img.entity_name ?? img.image_id}`}
      >
        <Thumb img={img} className="transition-transform duration-[240ms] group-hover:scale-[1.02]" />
      </button>
      <div className="flex flex-1 flex-col gap-1 p-3">
        <h3 className="line-clamp-3 text-[13.5px] font-semibold leading-snug" title={img.entity_name}>
          {img.entity_name ?? <span className="text-muted">Chưa có tên thực thể</span>}
        </h3>
        {img.entity_class && <p className="line-clamp-2 text-caption text-muted">{img.entity_class}</p>}
        {intentLabels && intentLabels.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {intentLabels.map((l) => (
              <span key={l} className="rounded-full bg-violet-50 px-1.5 text-[11px] text-violet-800">
                {l}
              </span>
            ))}
          </div>
        )}
        <div className="mt-auto flex flex-wrap items-center justify-between gap-x-2 gap-y-1 pt-1.5 text-caption">
          <ModerationBadge status={img.moderation.status} source={img.moderation.source} />
          {img.score !== undefined && (
            <span className="font-mono tabular text-muted" title={SCORE_KIND_LABEL[img.score_kind]}>
              {img.score_kind === 'rank' ? 'hạng' : 'điểm'} {fmtDec(img.score)}
            </span>
          )}
        </div>
        {img.source_host && <p className="truncate text-[11px] text-slate-500">{img.source_host}</p>}
      </div>
    </article>
  );
}
