import { useWindowVirtualizer } from '@tanstack/react-virtual';
import { useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { ImageResult } from '@/types/search';
import { ImageCard } from './ImageCard';

const GAP = 16;
const VIRTUALIZE_AFTER = 60;

function columnsFor(width: number) {
  if (width < 600) return 1;
  if (width < 900) return 2;
  if (width < 1180) return 3;
  return 4;
}

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(1024);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.clientWidth);
    const ro = new ResizeObserver(([entry]) => entry && setWidth(entry.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width] as const;
}

export interface GridProps {
  images: ImageResult[];
  onOpen: (index: number) => void;
  highlightIds?: Set<string>;
  intentLabelOf?: (img: ImageResult) => string[] | undefined;
  label: string;
}

/**
 * Row-based grid with stable 4:3 thumbnails. Above 60 items rows are virtualized against the
 * window scroll; ordering and Tab order stay row-major (no CSS column masonry).
 */
export function ImageGrid({ images, onOpen, highlightIds, intentLabelOf, label }: GridProps) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const cols = columnsFor(width);
  const rows = useMemo(() => {
    const out: number[][] = [];
    for (let i = 0; i < images.length; i += cols) out.push(Array.from({ length: Math.min(cols, images.length - i) }, (_, j) => i + j));
    return out;
  }, [images.length, cols]);
  const cardWidth = (width - GAP * (cols - 1)) / cols;
  const estimate = cardWidth * 0.75 + 132 + GAP;
  const virtual = images.length > VIRTUALIZE_AFTER;
  const virtualizer = useWindowVirtualizer({
    count: rows.length,
    estimateSize: () => estimate,
    overscan: 3,
    scrollMargin: ref.current?.offsetTop ?? 0,
    enabled: virtual,
  });

  const card = (i: number) => {
    const img = images[i]!;
    return (
      <div role="listitem" key={img.image_id}>
        <ImageCard
          img={img}
          onOpen={() => onOpen(i)}
          highlighted={highlightIds?.has(img.image_id)}
          dimmed={highlightIds !== undefined && highlightIds.size > 0 && !highlightIds.has(img.image_id)}
          intentLabels={intentLabelOf?.(img)}
        />
      </div>
    );
  };
  const rowStyle = { display: 'grid', gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`, gap: GAP };

  if (!virtual) {
    return (
      <div ref={ref} role="list" aria-label={label} style={rowStyle}>
        {images.map((_, i) => card(i))}
      </div>
    );
  }
  const items = virtualizer.getVirtualItems();
  return (
    <div ref={ref} role="list" aria-label={label} style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>
      {items.map((v) => (
        <div
          key={v.key}
          data-index={v.index}
          ref={virtualizer.measureElement}
          style={{ position: 'absolute', top: 0, left: 0, width: '100%', transform: `translateY(${v.start - virtualizer.options.scrollMargin}px)`, paddingBottom: GAP }}
        >
          <div style={rowStyle}>{rows[v.index]!.map(card)}</div>
        </div>
      ))}
    </div>
  );
}
