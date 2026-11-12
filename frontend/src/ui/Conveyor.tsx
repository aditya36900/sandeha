import React from 'react';
import { InspectionRecord } from '../api';
import { decisionColor } from './bits';

/** The most recent parts as a conveyor of thumbnails; escaped defects are marked so nobody misses them. */
export default function Conveyor({ records, selected, onSelect, count = 14 }: {
  records: InspectionRecord[]; selected?: string; onSelect: (id: string) => void; count?: number;
}) {
  const recent = records.slice(-count);
  if (!recent.length) return null;
  return (
    <div className="flex gap-2 overflow-x-auto pb-1" aria-label="Recent parts">
      {recent.map(r => {
        const escaped = r.truth === 1 && r.decision === 'PASS';
        const on = selected === r.id;
        return (
          <button key={r.id} onClick={() => onSelect(r.id)} title={`${r.id}: ${r.decision}${escaped ? ' (missed defect)' : ''}`}
            className={`relative shrink-0 w-[68px] rounded-lg overflow-hidden transition ${on ? 'ring-2 ring-bone' : 'opacity-80 hover:opacity-100'}`}>
            <img src={r.image_url} alt="" className="w-[68px] h-[68px] object-cover" loading="lazy" />
            <span className="absolute inset-x-0 bottom-0 h-1.5" style={{ background: decisionColor[r.decision] }} />
            {escaped && <span className="absolute top-1 left-1 text-[10px] font-semibold bg-fail text-ink rounded px-1">missed</span>}
            {r.ghost && <span className="absolute top-1 right-1 text-[10px] font-semibold bg-raised text-mist rounded px-1">check</span>}
          </button>
        );
      })}
    </div>
  );
}
