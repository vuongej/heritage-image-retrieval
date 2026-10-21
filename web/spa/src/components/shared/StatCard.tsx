import type { ReactNode } from 'react';
import type { DataProvenance } from '@/types/search';
import { DataSourceBadge } from './badges';
import { Card } from './ui';

export function StatCard({
  label,
  value,
  unit,
  provenance,
  children,
  footnote,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  provenance?: DataProvenance;
  children?: ReactNode;
  footnote?: ReactNode;
}) {
  return (
    <Card as="article" className="flex flex-col gap-2 p-4">
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-caption font-medium uppercase leading-[1.4] tracking-wide text-muted">{label}</h3>
        {provenance && <DataSourceBadge kind={provenance} />}
      </div>
      <p className="flex items-baseline gap-1.5">
        <span className="font-mono text-[26px] font-semibold leading-none tracking-tight tabular">{value}</span>
        {unit && <span className="text-[13px] text-muted">{unit}</span>}
      </p>
      {children && <div className="text-[13px] leading-relaxed text-slate-700">{children}</div>}
      {footnote && <p className="mt-auto border-t border-border pt-2 text-caption leading-relaxed text-muted">{footnote}</p>}
    </Card>
  );
}
