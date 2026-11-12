import React from 'react';
import { motion } from 'framer-motion';
import { Decision } from '../api';
import { decisionColor } from './bits';

/** The product's core idea as one picture: where a part's unusualness sits relative to the
 *  calibrated pass line and fail line. */
export default function DoubtGauge({ score, tauPass, tauFail, decision, sweep = false, compact = false }: {
  score?: number; tauPass: number; tauFail: number; decision?: Decision; sweep?: boolean; compact?: boolean;
}) {
  const max = tauFail * 1.7;
  const pos = (v: number) => Math.max(0, Math.min(1, v / max)) * 100;
  const p = pos(tauPass);
  const f = pos(tauFail);
  const x = score !== undefined ? pos(score) : undefined;
  const h = compact ? 'h-3' : 'h-5';
  return (
    <div className="w-full" role="img" aria-label={score !== undefined ? `Unusualness ${score.toFixed(3)}; pass line ${tauPass.toFixed(3)}, fail line ${tauFail.toFixed(3)}` : 'Pass, doubt and fail zones'}>
      <div className={`relative ${h} rounded-full overflow-hidden flex`}>
        <div style={{ width: `${p}%`, background: 'var(--pass)' }} className="opacity-80" />
        <div style={{ width: `${f - p}%`, background: 'var(--doubt)' }} className="opacity-90" />
        <div style={{ width: `${100 - f}%`, background: 'var(--fail)' }} className="opacity-80" />
      </div>
      <div className="relative h-0">
        {sweep ? (
          <motion.div className="absolute -top-[30px] w-1.5 h-[34px] rounded-full bg-bone shadow"
            initial={{ left: '4%' }} animate={{ left: ['4%', '45%', '62%', '88%', '30%', '58%'] }}
            transition={{ duration: 9, repeat: Infinity, ease: 'easeInOut' }} />
        ) : x !== undefined && (
          <motion.div className={`absolute ${compact ? '-top-[18px] h-[22px]' : '-top-[26px] h-[30px]'} w-1.5 rounded-full shadow`}
            style={{ background: 'var(--bone)', boxShadow: decision ? `0 0 0 3px ${decisionColor[decision]}55` : undefined }}
            initial={false} animate={{ left: `calc(${x}% - 3px)` }} transition={{ type: 'spring', stiffness: 160, damping: 20 }} />
        )}
      </div>
      {!compact && (
        <div className="grid text-xs mt-2 text-mist" style={{ gridTemplateColumns: `${p}% ${f - p}% ${100 - f}%` }}>
          <span>approve on my own</span>
          <span className="text-doubt pl-1">ask a person</span>
          <span className="pl-1">reject on my own</span>
        </div>
      )}
    </div>
  );
}
