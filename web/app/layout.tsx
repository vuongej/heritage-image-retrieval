import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Heritage Image Retrieval',
  description: 'Truy xuất ảnh di sản Việt Nam — single / multi-intent / multi-hop',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="vi">
      <body>
        <header className="topbar">
          <strong>Heritage Image Retrieval</strong>
          <span className="muted">Phần A · lọc ảnh &nbsp;|&nbsp; Phần B · truy xuất</span>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
