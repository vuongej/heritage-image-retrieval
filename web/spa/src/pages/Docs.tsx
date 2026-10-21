import * as Tabs from '@radix-ui/react-tabs';
import { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { useLocation, useNavigate } from 'react-router-dom';
import { MermaidDoc } from '@/components/docs/MermaidDoc';
import { Card, SectionTitle } from '@/components/shared/ui';
import { useVerify } from '@/hooks/queries';
import { AS_IS, ER, GAPS, MD_ASIS, MD_METHOD, MD_PART_A, processingDiagram, SEQ_HOP, SEQ_MULTI, SEQ_SINGLE, TO_BE } from './docsContent';

const TABS = [
  { id: 'as-is', label: 'Kiến trúc hiện tại (As-Is)' },
  { id: 'to-be', label: 'Kiến trúc đề xuất (To-Be)' },
  { id: 'part-a', label: 'Xử lý ảnh (Phần A)' },
  { id: 'part-b', label: 'Truy xuất (Phần B)' },
  { id: 'method', label: 'Schema & phương pháp đo' },
  { id: 'gaps', label: 'Hạn chế' },
];

/** Markdown without raw HTML (react-markdown escapes it by default). */
function Prose({ children }: { children: string }) {
  return (
    <div className="max-w-3xl space-y-3 text-[14px] leading-relaxed [&_code]:rounded [&_code]:bg-slate-100 [&_code]:px-1 [&_code]:font-mono [&_code]:text-[12.5px] [&_li]:ml-5 [&_ol]:list-decimal [&_ol]:space-y-1 [&_ul]:list-disc [&_ul]:space-y-1">
      <ReactMarkdown>{children}</ReactMarkdown>
    </div>
  );
}

export default function DocsPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const initial = TABS.some((t) => `#${t.id}` === location.hash) ? location.hash.slice(1) : 'as-is';
  const [tab, setTab] = useState(initial);
  useEffect(() => {
    const h = location.hash.slice(1);
    if (TABS.some((t) => t.id === h)) setTab(h);
  }, [location.hash]);
  const verify = useVerify();

  return (
    <div className="space-y-5">
      <header className="space-y-1">
        <h1 className="text-h1 font-semibold tracking-tight">Tài liệu kiến trúc & phương pháp</h1>
        <p className="max-w-3xl text-muted">
          Sơ đồ “As-Is” được đối chiếu với source và config (docs/backend-inventory.md). Thành phần chưa triển khai chỉ xuất hiện ở “To-Be”, vẽ nét đứt.
        </p>
      </header>
      <Tabs.Root
        value={tab}
        onValueChange={(v) => {
          setTab(v);
          navigate({ hash: v }, { replace: true });
        }}
      >
        <Tabs.List aria-label="Mục tài liệu" className="sticky top-14 z-20 -mx-4 mb-5 flex gap-1 overflow-x-auto border-b border-border bg-bg/95 px-4 py-2 backdrop-blur">
          {TABS.map((t) => (
            <Tabs.Trigger
              key={t.id}
              value={t.id}
              className="whitespace-nowrap rounded-md px-3 py-1.5 text-[13px] font-medium text-muted hover:text-text data-[state=active]:bg-brand-50 data-[state=active]:text-brand-700"
            >
              {t.label}
            </Tabs.Trigger>
          ))}
        </Tabs.List>

        <Tabs.Content value="as-is" id="as-is" className="space-y-5">
          <MermaidDoc kind="actual" source={AS_IS} caption="Topology đang chạy local: SPA → FastAPI → SQLite/Qdrant/Embedding API/reranker; ảnh tải trực tiếp từ host gốc." />
          <Prose>{MD_ASIS}</Prose>
        </Tabs.Content>

        <Tabs.Content value="to-be" id="to-be" className="space-y-5">
          <MermaidDoc kind="proposed" source={TO_BE} caption="Đề xuất: Nginx + media proxy approved-only, img_visual SigLIP2, KG có nguồn, admin API có phân quyền, worker nhiều GPU, k6. Nét đứt = chưa triển khai." />
        </Tabs.Content>

        <Tabs.Content value="part-a" id="part-a" className="space-y-5">
          <MermaidDoc
            kind="actual"
            source={processingDiagram(verify.data?.data)}
            caption={verify.data ? `Khối lượng từ ${verify.data.meta.path}. Nhánh VLM (nét đứt) chỉ nhận ảnh được router chọn.` : 'Chưa đọc được báo cáo verify — khối lượng hiển thị N/A.'}
          />
          <Prose>{MD_PART_A}</Prose>
        </Tabs.Content>

        <Tabs.Content value="part-b" id="part-b" className="space-y-5">
          <SectionTitle>(a) Truy vấn đơn ý định</SectionTitle>
          <MermaidDoc kind="actual" source={SEQ_SINGLE} caption="retrieval/local_search.py::run — nhánh một sub-query." />
          <SectionTitle>(b) Nhiều ý định + điều kiện chung</SectionTitle>
          <MermaidDoc kind="actual" source={SEQ_MULTI} caption="Địa danh là điều kiện áp dụng cho mọi ý định, không phải ý định thứ ba (retrieval/rule_parser.py::_split_intents). Backend chưa hỗ trợ AND trên từng ảnh." />
          <SectionTitle>(c) Nhiều bước có bằng chứng</SectionTitle>
          <MermaidDoc kind="actual" source={SEQ_HOP} caption="retrieval/hop.py + retrieval/kg_online.py — chỉ đi theo cạnh đã kiểm chứng (câu trích có nguyên văn trong nguồn); mọi nhánh thất bại trả trạng thái rõ ràng, không fallback sang ảnh “cùng nhóm”." />
        </Tabs.Content>

        <Tabs.Content value="method" id="method" className="space-y-5">
          <MermaidDoc kind="actual" source={ER} caption="Schema SQLite thực (storage/local.py, retrieval/hop.py) và liên kết point Qdrant = rownum." />
          <Prose>{MD_METHOD}</Prose>
        </Tabs.Content>

        <Tabs.Content value="gaps" id="gaps">
          <Card className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-table">
              <thead className="bg-slate-50 text-left text-caption uppercase tracking-wide text-muted">
                <tr>
                  <th className="px-3 py-2 font-medium">Hạng mục</th>
                  <th className="px-3 py-2 font-medium">Tình trạng khi khảo sát (21/10/2026)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {GAPS.map(([k, v]) => (
                  <tr key={k} className="align-top">
                    <td className="px-3 py-2 font-medium">{k}</td>
                    <td className="px-3 py-2">{v}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </Tabs.Content>
      </Tabs.Root>
    </div>
  );
}
