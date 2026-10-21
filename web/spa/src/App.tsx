import { lazy } from 'react';
import { BrowserRouter, Link, Route, Routes } from 'react-router-dom';
import { Layout } from './components/shared/Layout';
import { EmptyState } from './components/shared/states';
import { SearchPage } from './pages/Search';

// Charts (Recharts) and diagrams (Mermaid) only load with the pages that need them.
const ModerationPage = lazy(() => import('./pages/Moderation'));
const BenchmarkPage = lazy(() => import('./pages/Benchmark'));
const DocsPage = lazy(() => import('./pages/Docs'));

function NotFound() {
  return (
    <EmptyState title="Không tìm thấy trang">
      <Link to="/" className="font-medium text-brand-700 underline">
        Về trang tìm kiếm
      </Link>
    </EmptyState>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<SearchPage />} />
          <Route path="moderation" element={<ModerationPage />} />
          <Route path="benchmark" element={<BenchmarkPage />} />
          <Route path="docs" element={<DocsPage />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
