import { Search, X } from 'lucide-react';
import { useEffect, useId, useState, type FormEvent } from 'react';
import { MAX_QUERY_LENGTH } from '@/config';
import { Button, cn } from '@/components/shared/ui';

export function SearchBar({
  initial,
  onSubmit,
  compact = false,
  busy = false,
}: {
  initial: string;
  onSubmit: (query: string) => void;
  compact?: boolean;
  busy?: boolean;
}) {
  const [value, setValue] = useState(initial);
  const id = useId();
  // Back/forward navigation changes the URL query: mirror it, do not keep stale text.
  useEffect(() => setValue(initial), [initial]);

  function submit(e: FormEvent) {
    e.preventDefault();
    const q = value.trim();
    if (q) onSubmit(q);
  }

  return (
    <form role="search" onSubmit={submit} className={cn('w-full', compact ? 'max-w-none' : 'mx-auto max-w-[640px]')}>
      <label htmlFor={id} className="sr-only">
        Truy vấn tìm ảnh
      </label>
      <div
        className={cn(
          'flex items-center gap-2 rounded-[10px] border border-border bg-surface pl-3 pr-1.5 shadow-sm transition-shadow duration-[180ms] focus-within:border-brand-600 focus-within:ring-4 focus-within:ring-brand-600/15',
          compact ? 'h-11' : 'h-14',
        )}
      >
        <Search aria-hidden className="size-4.5 shrink-0 text-muted" />
        <input
          id={id}
          type="search"
          value={value}
          maxLength={MAX_QUERY_LENGTH}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Ví dụ: hồ bơi và công viên nước ở Phú Quốc"
          autoComplete="off"
          enterKeyHint="search"
          className={cn('h-full min-w-0 flex-1 bg-transparent outline-none placeholder:text-slate-400', compact ? 'text-body' : 'text-lead')}
        />
        {value && (
          <button
            type="button"
            onClick={() => setValue('')}
            className="rounded p-1 text-muted hover:bg-slate-100 hover:text-text"
            aria-label="Xoá nội dung truy vấn"
          >
            <X aria-hidden className="size-4" />
          </button>
        )}
        <Button type="submit" variant="primary" size={compact ? 'sm' : 'md'} disabled={!value.trim() || busy} aria-busy={busy}>
          Tìm
        </Button>
      </div>
    </form>
  );
}
