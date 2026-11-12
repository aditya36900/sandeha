import React from 'react';
import { Decision } from '../api';

export const decisionColor: Record<Decision, string> = { PASS: 'var(--pass)', FAIL: 'var(--fail)', DOUBT: 'var(--doubt)', HOLD: 'var(--hold)' };

export const reasonText: Record<string, string> = {
  BAD_IMAGE: 'Image unreliable',
  CONDITIONS_CHANGED: 'Conditions changed',
  NEVER_SEEN: 'Never seen anything like it',
  BORDERLINE: 'Borderline'
};

export function Verdict({ d, size = 'md' }: { d: Decision; size?: 'sm' | 'md' | 'xl' }) {
  const cls = size === 'xl' ? 'display text-6xl font-bold tracking-tight' : size === 'md' ? 'display text-lg font-semibold' : 'mono text-[11px] font-semibold tracking-wider';
  const word = size === 'sm' ? d : d === 'DOUBT' ? 'Doubt' : d === 'PASS' ? 'Pass' : d === 'HOLD' ? 'Hold' : 'Fail';
  return <span className={cls} style={{ color: decisionColor[d] }}>{word}</span>;
}

export function Dot({ d }: { d: Decision }) {
  return <span className="inline-block w-2 h-2 rounded-full" style={{ background: decisionColor[d], boxShadow: `0 0 8px ${decisionColor[d]}` }} aria-label={d} />;
}

export function Panel({ title, children, className = '', aside, tone }: { title?: string; children: React.ReactNode; className?: string; aside?: React.ReactNode; tone?: 'pass' | 'fail' | 'doubt' | 'accent' }) {
  return (
    <section className={`panel p-4 lg:p-5 ${tone ? `glow-${tone}` : ''} ${className}`}>
      {(title || aside) && (
        <header className="flex items-baseline justify-between gap-3 mb-3">
          {title && <h2 className="label !text-bone/80 whitespace-nowrap">{title}</h2>}
          {aside}
        </header>
      )}
      {children}
    </section>
  );
}

export function Btn({ children, onClick, tone = 'plain', disabled, title }: {
  children: React.ReactNode; onClick?: () => void; tone?: 'plain' | 'doubt' | 'pass' | 'fail' | 'ghost' | 'accent'; disabled?: boolean; title?: string;
}) {
  const styles: Record<string, string> = {
    plain: 'bg-raised hover:bg-line text-bone border border-line',
    accent: 'bg-accent text-ink hover:brightness-110 font-semibold',
    doubt: 'bg-doubt text-ink hover:brightness-110 font-semibold',
    pass: 'bg-pass text-ink hover:brightness-110 font-semibold',
    fail: 'bg-fail text-ink hover:brightness-110 font-semibold',
    ghost: 'bg-transparent text-mist hover:text-bone border border-line hover:border-mist'
  };
  return (
    <button title={title} disabled={disabled} onClick={onClick}
      className={`px-3.5 py-2 rounded-lg text-[13px] font-medium transition disabled:opacity-40 disabled:cursor-not-allowed ${styles[tone]}`}>
      {children}
    </button>
  );
}

export function Stat({ value, label, tone }: { value: React.ReactNode; label: string; tone?: Decision }) {
  return (
    <div>
      <div className="text-3xl font-semibold num" style={tone ? { color: decisionColor[tone] } : undefined}>{value}</div>
      <div className="label mt-0.5">{label}</div>
    </div>
  );
}

export function Voice({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return <p className={`voice text-[20px] leading-snug text-bone ${className}`}>{children}</p>;
}

export const pct = (x: number | undefined, d = 1) => (x === undefined || Number.isNaN(x) ? '–' : `${(100 * x).toFixed(d)}%`);
export const rupees = (x: number) => `₹${Math.round(x).toLocaleString('en-IN')}`;
