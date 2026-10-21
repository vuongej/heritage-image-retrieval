import { Github, Images } from 'lucide-react';
import { Suspense } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { DATA_MODE, GITHUB_URL } from '@/config';
import { useHealth } from '@/hooks/queries';
import { fmtInt } from '@/lib/format';
import { cn, Tip } from './ui';

const NAV = [
  { to: '/', label: 'Tìm kiếm', end: true },
  { to: '/moderation', label: 'Kiểm duyệt' },
  { to: '/benchmark', label: 'Benchmark' },
  { to: '/docs', label: 'Tài liệu' },
];

function HealthPill() {
  const health = useHealth();
  if (DATA_MODE === 'mock') return null;
  if (health.isPending) return <span className="text-caption text-muted">Đang kiểm tra backend…</span>;
  if (health.isError)
    return (
      <span className="inline-flex items-center gap-1.5 text-caption text-red-700">
        <span aria-hidden className="size-2 rounded-full bg-red-600" />
        Backend không phản hồi
      </span>
    );
  const h = health.data;
  return (
    <Tip
      content={`GET /v1/health · ${h.backend ?? ''} · embedding ${h.embedding?.model ?? '—'} · rerank ${h.rerank ?? '—'} · index ${
        h.index_complete ? 'hoàn tất' : 'chưa hoàn tất'
      }`}
    >
      <span tabIndex={0} className="inline-flex items-center gap-1.5 text-caption text-muted">
        <span aria-hidden className="size-2 rounded-full bg-emerald-600" />
        <span className="hidden md:inline">Catalog</span> <span className="font-mono tabular">{fmtInt(h.catalog?.images)}</span> ảnh
      </span>
    </Tip>
  );
}

export function Layout() {
  return (
    <div className="flex min-h-screen flex-col">
      <a
        href="#main"
        className="sr-only z-[60] rounded bg-brand-600 px-3 py-2 text-white focus:not-sr-only focus:fixed focus:left-3 focus:top-3"
      >
        Bỏ qua tới nội dung chính
      </a>
      {DATA_MODE === 'mock' && (
        <div role="status" className="sticky top-0 z-50 bg-fuchsia-700 px-4 py-1.5 text-center text-caption font-semibold tracking-wide text-white">
          DỮ LIỆU MINH HỌA — KHÔNG PHẢI KẾT QUẢ ĐO (DATA_MODE=mock)
        </div>
      )}
      <header className={cn('sticky z-40 h-14 border-b border-border bg-surface/95 backdrop-blur', DATA_MODE === 'mock' ? 'top-7' : 'top-0')}>
        <div className="mx-auto flex h-full max-w-[1280px] items-center gap-3 px-4">
          <NavLink to="/" className="flex shrink-0 items-center gap-2 font-semibold text-text" aria-label="Kho Ảnh Thông Minh — trang tìm kiếm">
            <span className="grid size-8 place-items-center rounded-lg bg-brand-600 text-white">
              <Images aria-hidden className="size-4.5" />
            </span>
            <span className="hidden sm:inline">Kho Ảnh Thông Minh</span>
          </NavLink>
          <nav aria-label="Điều hướng chính" className="-mx-1 flex min-w-0 flex-1 items-center overflow-x-auto">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.end}
                className={({ isActive }) =>
                  cn(
                    'whitespace-nowrap rounded-md px-2.5 py-1.5 text-[13.5px] font-medium transition-colors duration-[120ms]',
                    isActive ? 'bg-brand-50 text-brand-700' : 'text-muted hover:bg-slate-100 hover:text-text',
                  )
                }
              >
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="hidden shrink-0 sm:block">
            <HealthPill />
          </div>
          {GITHUB_URL ? (
            <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer" className="rounded-md p-2 text-muted hover:bg-slate-100 hover:text-text" aria-label="Mã nguồn trên GitHub">
              <Github aria-hidden className="size-4.5" />
            </a>
          ) : (
            <Tip content="Repo chưa được công bố (VITE_GITHUB_URL trống).">
              <span tabIndex={0} aria-disabled="true" aria-label="GitHub — chưa có URL công khai" className="cursor-not-allowed rounded-md p-2 text-slate-300">
                <Github aria-hidden className="size-4.5" />
              </span>
            </Tip>
          )}
        </div>
      </header>
      <main id="main" tabIndex={-1} className="mx-auto w-full max-w-[1280px] flex-1 px-4 py-6 outline-none">
        <Suspense
          fallback={
            <div role="status" aria-label="Đang tải trang" className="space-y-3">
              <div className="skeleton h-7 w-64 rounded" />
              <div className="skeleton h-28 w-full rounded-lg" />
            </div>
          }
        >
          <Outlet />
        </Suspense>
      </main>
      <footer className="border-t border-border bg-surface">
        <div className="mx-auto flex max-w-[1280px] flex-wrap items-center justify-between gap-2 px-4 py-4 text-caption text-muted">
          <span>Capstone — Xử lý & truy xuất ảnh di sản Việt Nam</span>
          <span>
            Chế độ dữ liệu: <span className="font-mono">{DATA_MODE}</span>
          </span>
        </div>
      </footer>
    </div>
  );
}
