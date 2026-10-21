import * as RT from '@radix-ui/react-tooltip';
import clsx from 'clsx';
import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { forwardRef } from 'react';

export function cn(...args: Parameters<typeof clsx>) {
  return clsx(...args);
}

type Variant = 'primary' | 'secondary' | 'ghost';
export const Button = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: 'sm' | 'md' }>(
  function Button({ variant = 'secondary', size = 'md', className, ...props }, ref) {
    return (
      <button
        ref={ref}
        className={cn(
          'inline-flex items-center justify-center gap-1.5 rounded-[var(--radius-input)] font-medium transition-colors duration-[120ms]',
          'disabled:cursor-not-allowed disabled:opacity-50',
          size === 'sm' ? 'h-8 px-2.5 text-[13px]' : 'h-10 px-3.5 text-sm',
          variant === 'primary' && 'bg-brand-600 text-white hover:bg-brand-700',
          variant === 'secondary' && 'border border-border bg-surface text-text hover:bg-slate-50',
          variant === 'ghost' && 'text-muted hover:bg-slate-100 hover:text-text',
          className,
        )}
        {...props}
      />
    );
  },
);

export function Card({ className, children, as: As = 'section', ...rest }: { className?: string; children: ReactNode; as?: 'section' | 'div' | 'article'; 'aria-labelledby'?: string }) {
  return (
    <As className={cn('rounded-[var(--radius-card)] border border-border bg-surface', className)} {...rest}>
      {children}
    </As>
  );
}

export function SectionTitle({ id, children, aside }: { id?: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
      <h2 id={id} className="text-h2 font-semibold tracking-tight">
        {children}
      </h2>
      {aside}
    </div>
  );
}

export function Tip({ content, children }: { content: ReactNode; children: ReactNode }) {
  return (
    <RT.Root delayDuration={200}>
      <RT.Trigger asChild>{children}</RT.Trigger>
      <RT.Portal>
        <RT.Content
          sideOffset={6}
          className="z-50 max-w-xs rounded-md bg-slate-900 px-2.5 py-1.5 text-caption leading-relaxed text-white shadow-lg"
        >
          {content}
          <RT.Arrow className="fill-slate-900" />
        </RT.Content>
      </RT.Portal>
    </RT.Root>
  );
}

export function Mono({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn('font-mono text-[12.5px] tabular', className)}>{children}</span>;
}

/** Inline definition-list row used in sidebars and stat footers. */
export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 py-1.5">
      <dt className="text-caption font-medium uppercase leading-[1.4] tracking-wide text-muted">{label}</dt>
      <dd className="break-words text-body">{children}</dd>
    </div>
  );
}
