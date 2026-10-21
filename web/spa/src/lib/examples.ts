import type { QueryType } from '@/types/search';

export interface ExampleQuery {
  query: string;
  type: QueryType;
  /** Where the example comes from — examples are not "known good" results. */
  source: string;
  note?: string;
}

// From evals/ui_testcases.json (the repo's UI test suite) and the assignment brief. Multi-hop examples
// were checked against the verified KG (retrieval/hop.py); the brief's example stays to show the
// honest seed_not_linked state.
export const EXAMPLES: ExampleQuery[] = [
  { query: 'Quần thể Tràng An', type: 'SINGLE', source: 'TC01 — tên thực thể chính xác' },
  { query: 'chợ họp trên sông, thuyền chở đầy trái cây', type: 'SINGLE', source: 'TC03 — truy vấn mô tả' },
  { query: 'Phở bò và Bánh cuốn', type: 'MULTI_INTENT', source: 'TC04 — hai món ăn' },
  { query: 'hồ bơi và công viên nước ở Phú Quốc', type: 'MULTI_INTENT', source: 'Đề bài — 2 ý định + điều kiện chung' },
  { query: 'các chợ truyền thống', type: 'SET_QUERY', source: 'TC05 — truy vấn tập hợp' },
  {
    query: 'lăng của con trai vua Gia Long',
    type: 'MULTI_HOP',
    source: 'Multi-hop 2 bước — con trai → lăng',
    note: 'Gia Long → Minh Mạng (nhiều nguồn) → các thực thể lăng Minh Mạng trong catalog.',
  },
  {
    query: 'mộ mẹ của Hồ Chí Minh',
    type: 'MULTI_HOP',
    source: 'Multi-hop 2 bước — mẹ → mộ',
  },
  {
    query: 'vợ vua Khải Định',
    type: 'MULTI_HOP',
    source: 'Multi-hop — đích là người',
    note: 'Quan hệ được xác minh nhưng catalog không có ảnh người: không trả ảnh thay thế.',
  },
  {
    query: 'ảnh con trai chủ tịch Phạm Nhật Vượng',
    type: 'MULTI_HOP',
    source: 'Đề bài — multi-hop',
    note: 'Chỉ trả ảnh khi KG có quan hệ có nguồn; nếu không sẽ hiện trạng thái chưa xác minh.',
  },
];
