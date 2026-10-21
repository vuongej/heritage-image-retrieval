import { Download } from 'lucide-react';
import { Button } from './ui';

/** Downloads exactly the JSON the API served for this report — never a fixture. */
export function DownloadReport({ id, sha256, data }: { id: string; sha256: string; data: unknown }) {
  return (
    <Button
      size="sm"
      onClick={() => {
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${id}-${sha256.slice(0, 12)}.json`;
        a.click();
        URL.revokeObjectURL(url);
      }}
    >
      <Download aria-hidden className="size-3.5" />
      Tải JSON
    </Button>
  );
}
