import * as Dialog from '@radix-ui/react-dialog';
import { ChevronLeft, ChevronRight, ExternalLink, X, ZoomIn, ZoomOut } from 'lucide-react';
import { useEffect, useState } from 'react';
import { fmtDec, fmtInt } from '@/lib/format';
import { safeHttpUrl } from '@/lib/url';
import type { ImageResult } from '@/types/search';
import { ModerationBadge } from '@/components/shared/badges';
import { Button, Field, Mono } from '@/components/shared/ui';
import { canRenderPixels, PolicyPlaceholder, SCORE_KIND_LABEL, Thumb } from './ImageCard';

/** Radix Dialog gives focus trap, Esc to close, scroll lock and focus return to the card. */
export function Lightbox({
  images,
  index,
  onIndex,
  onClose,
  intentLabelOf,
}: {
  images: ImageResult[];
  index: number | null;
  onIndex: (i: number) => void;
  onClose: () => void;
  intentLabelOf?: (img: ImageResult) => string[] | undefined;
}) {
  const [zoom, setZoom] = useState(1);
  const img = index !== null ? images[index] : undefined;
  useEffect(() => setZoom(1), [index]);

  const prev = () => index !== null && index > 0 && onIndex(index - 1);
  const next = () => index !== null && index < images.length - 1 && onIndex(index + 1);
  const original = img ? safeHttpUrl(img.original_url) : undefined;

  return (
    <Dialog.Root open={Boolean(img)} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-slate-950/80" />
        <Dialog.Content
          onKeyDown={(e) => {
            if (e.key === 'ArrowLeft') prev();
            if (e.key === 'ArrowRight') next();
          }}
          className="fixed inset-0 z-50 flex flex-col bg-surface outline-none md:inset-6 md:rounded-xl lg:flex-row"
          aria-describedby={undefined}
        >
          {img && (
            <>
              <div className="relative flex min-h-[45vh] flex-1 items-center justify-center overflow-auto bg-slate-950">
                <div style={{ transform: `scale(${zoom})`, transformOrigin: 'center' }} className="max-h-full max-w-full transition-transform duration-[180ms]">
                  {canRenderPixels(img) ? (
                    <Thumb img={img} fit="contain" />
                  ) : (
                    <div className="h-64 w-80">
                      <PolicyPlaceholder />
                    </div>
                  )}
                </div>
                <div className="absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-1 rounded-full bg-slate-900/85 p-1 text-white">
                  <button type="button" onClick={prev} disabled={index === 0} className="rounded-full p-2 hover:bg-white/15 disabled:opacity-40" aria-label="Ảnh trước">
                    <ChevronLeft aria-hidden className="size-4" />
                  </button>
                  <span className="px-1 font-mono text-caption tabular" aria-live="polite">
                    {fmtInt((index ?? 0) + 1)}/{fmtInt(images.length)}
                  </span>
                  <button type="button" onClick={next} disabled={index === images.length - 1} className="rounded-full p-2 hover:bg-white/15 disabled:opacity-40" aria-label="Ảnh sau">
                    <ChevronRight aria-hidden className="size-4" />
                  </button>
                  <span className="mx-1 h-4 w-px bg-white/25" />
                  <button type="button" onClick={() => setZoom(zoom === 1 ? 2 : 1)} className="rounded-full p-2 hover:bg-white/15" aria-label={zoom === 1 ? 'Phóng to 2x' : 'Thu nhỏ'} aria-pressed={zoom === 2}>
                    {zoom === 1 ? <ZoomIn aria-hidden className="size-4" /> : <ZoomOut aria-hidden className="size-4" />}
                  </button>
                </div>
              </div>
              <aside className="w-full shrink-0 overflow-y-auto border-t border-border p-5 lg:w-[360px] lg:border-l lg:border-t-0">
                <div className="mb-3 flex items-start justify-between gap-3">
                  <Dialog.Title className="text-h3 font-semibold leading-snug">{img.entity_name ?? 'Ảnh kết quả'}</Dialog.Title>
                  <Dialog.Close asChild>
                    <Button variant="ghost" size="sm" aria-label="Đóng">
                      <X aria-hidden className="size-4" />
                    </Button>
                  </Dialog.Close>
                </div>
                <dl className="divide-y divide-border">
                  {img.caption && <Field label="Mô tả (metadata)">{img.caption}</Field>}
                  {img.entity_class && <Field label="Nhóm">{img.entity_class}</Field>}
                  <Field label="Kiểm duyệt">
                    <ModerationBadge status={img.moderation.status} />
                    <span className="block text-caption text-muted">Nguồn: {img.moderation.source}</span>
                    {img.moderation.labels.length > 0 && <span className="block text-caption">Nhãn: {img.moderation.labels.join(', ')}</span>}
                  </Field>
                  <Field label="Điểm">
                    {img.score === undefined ? '—' : <Mono>{fmtDec(img.score, 4)}</Mono>}{' '}
                    <span className="text-caption text-muted">({SCORE_KIND_LABEL[img.score_kind]})</span>
                  </Field>
                  {intentLabelOf?.(img)?.length ? <Field label="Khớp ý định">{intentLabelOf(img)!.join(' · ')}</Field> : null}
                  <Field label="Kích thước gốc">{img.width && img.height ? <Mono>{`${img.width}×${img.height}`}</Mono> : <span className="text-muted">Chưa biết (catalog chưa đo kích thước)</span>}</Field>
                  <Field label="Kiểm tra pixel">{img.quality.pixel_checked ? 'Đã kiểm tra' : 'Chưa — truy xuất dựa trên metadata văn bản'}</Field>
                  <Field label="image_id">
                    <Mono className="break-all">{img.image_id}</Mono>
                  </Field>
                  {img.entity_id && (
                    <Field label="entity_id">
                      <Mono className="break-all">{img.entity_id}</Mono>
                    </Field>
                  )}
                  {img.producer_step_ids.length > 0 && <Field label="Bước truy xuất">{img.producer_step_ids.join(', ')}</Field>}
                </dl>
                {original && canRenderPixels(img) && (
                  <a
                    href={original}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-4 inline-flex items-center gap-1.5 text-[13px] font-medium text-brand-700 underline-offset-2 hover:underline"
                  >
                    <ExternalLink aria-hidden className="size-3.5" />
                    Mở ảnh gốc ({img.source_host})
                  </a>
                )}
              </aside>
            </>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
