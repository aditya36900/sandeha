import React, { useRef, useState } from 'react';

/** Drag photos in, or click to choose them. Shows how many were picked and a preview strip. */
export default function DropZone({ label, hint, files, onFiles, minimum, accent = 'var(--line)' }: {
  label: string; hint: string; files: File[]; onFiles: (f: File[]) => void; minimum?: number; accent?: string;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const add = (list: FileList | null) => {
    if (!list) return;
    const imgs = Array.from(list).filter(f => f.type.startsWith('image/'));
    onFiles([...files, ...imgs]);
  };
  const enough = minimum === undefined || files.length >= minimum;
  return (
    <div
      onDragOver={e => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={e => { e.preventDefault(); setOver(false); add(e.dataTransfer.files); }}
      className={`rounded-xl p-4 border-2 border-dashed transition ${over ? 'bg-raised' : 'bg-ink/40'}`}
      style={{ borderColor: over ? 'var(--doubt)' : accent }}>
      <div className="flex items-baseline justify-between gap-2">
        <div className="font-semibold text-sm">{label}</div>
        <div className={`text-xs num ${enough ? 'text-pass' : 'text-mist'}`}>
          {files.length}{minimum ? ` / ${minimum}+` : ''} photo{files.length === 1 ? '' : 's'}
        </div>
      </div>
      <p className="text-xs text-mist mt-1">{hint}</p>
      {files.length > 0 && (
        <div className="flex gap-1 mt-3 overflow-hidden">
          {files.slice(0, 10).map((f, i) => (
            <img key={i} src={URL.createObjectURL(f)} alt="" className="w-10 h-10 rounded object-cover shrink-0" />
          ))}
          {files.length > 10 && <span className="text-xs text-mist self-center ml-1">+{files.length - 10}</span>}
        </div>
      )}
      <div className="flex gap-3 mt-3">
        <button onClick={() => input.current?.click()} className="text-sm text-doubt font-semibold">Choose photos</button>
        {files.length > 0 && <button onClick={() => onFiles([])} className="text-sm text-mist">Clear</button>}
      </div>
      <input ref={input} type="file" accept="image/*" multiple className="hidden" onChange={e => { add(e.target.files); e.target.value = ''; }} />
    </div>
  );
}
