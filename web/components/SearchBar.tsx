'use client';
import { useState } from 'react';

export default function SearchBar({ onSearch, loading }:
  { onSearch: (q: string) => void; loading: boolean }) {
  const [q, setQ] = useState('');
  return (
    <form className="searchbar" onSubmit={(e) => { e.preventDefault(); onSearch(q); }}>
      <input value={q} onChange={(e) => setQ(e.target.value)}
        placeholder='VD: "Quần thể Tràng An" · "hồ bơi và công viên nước ở Phú Quốc" · "ảnh con hổ và con mèo"'
        aria-label="Truy vấn ảnh" />
      <button type="submit" disabled={loading || !q.trim()}>
        {loading ? 'Đang tìm…' : 'Tìm ảnh'}
      </button>
    </form>
  );
}
