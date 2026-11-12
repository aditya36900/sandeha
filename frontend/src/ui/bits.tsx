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
  const cls = size === 'xl' ? 'text-7xl font-semibold tracking-tight' : size === 'md' ? 'text-lg font-semibold' : 'text-xs font-semibold';
  const word = d === 'DOUBT' ? 'Doubt' : d === 'PASS' ? 'Pass' : d === 'HOLD' ? 'Hold' : 'Fail';
  return <span className={cls} style={{ color: decisionColor[d] }}>{word}</span>;
}

export function Dot({ d }: { d: Decision }) {
  return <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ background: decisionColor[d] }} aria-label={d} />;
}

export function Panel({ title, children, className = '', aside }: { title?: string; children: React.ReactNode; className?: string; aside?: React.ReactNode }) {
  return (
    <section className={`bg-surface rounded-2xl p-5 ${className}`}>
      {(title || aside) && (
        <header className="flex items-baseline justify-between gap-3 mb-3">
          {title && <h2 className="text-[15px] font-semibold text-bone">{title}</h2>}
          {aside}
        </header>
      )}
      {children}
    </section>
  );
}

export function Btn({ children, onClick, tone = 'plain', disabled, title }: {
  children: React.ReactNode; onClick?: () => void; tone?: 'plain' | 'doubt' | 'pass' | 'fail' | 'ghost'; disabled?: boolean; title?: string;
}) {
  const styles: Record<string, string> = {
    plain: 'bg-raised hover:bg-line text-bone',
    doubt: 'bg-doubt text-ink hover:brightness-110',
    pass: 'bg-pass text-ink hover:brightness-110',
    fail: 'bg-fail text-ink hover:brightness-110',
    ghost: 'bg-transparent text-mist hover:text-bone border border-line'
  };
  return (
    <button title={title} disabled={disabled} onClick={onClick}
      className={`px-4 py-2 rounded-xl text-sm font-semibold transition disabled:opacity-40 disabled:cursor-not-allowed ${styles[tone]}`}>
      {children}
    </button>
  );
}

export function Stat({ value, label, tone }: { value: React.ReactNode; label: string; tone?: Decision }) {
  return (
    <div>
      <div className="text-3xl font-semibold num" style={tone ? { color: decisionColor[tone] } : undefined}>{value}</div>
      <div className="text-mist text-sm">{label}</div>
    </div>
  );
}

export function Voice({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return <p className={`voice text-[22px] leading-snug text-bone ${className}`}>{children}</p>;
}

export const pct = (x: number | undefined, d = 1) => (x === undefined || Number.isNaN(x) ? '–' : `${(100 * x).toFixed(d)}%`);
export const rupees = (x: number) => `₹${Math.round(x).toLocaleString('en-IN')}`;
