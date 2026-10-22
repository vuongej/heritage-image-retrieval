import { lazy } from 'react';
import { BrowserRouter, Link, Navigate, Route, Routes } from 'react-router-dom';
import { Layout } from './components/shared/Layout';
import { EmptyState } from './components/shared/states';
import { SearchPage } from './pages/Search';

// Trang Xử lý dữ liệu chỉ tải khi mở.
const ProcessPage = lazy(() => import('./pages/Process'));

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
          <Route path="process" element={<ProcessPage />} />
          <Route path="moderation" element={<Navigate to="/process" replace />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
