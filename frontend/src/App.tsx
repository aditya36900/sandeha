import React, { useEffect, useState } from 'react';
import { api } from './api';
import { Act, StoreProvider, useStore } from './store';
import Choose from './acts/Choose';
import Genesis from './acts/Genesis';
import Interview from './acts/Interview';
import Line from './acts/Line';
import Chaos from './acts/Chaos';
import Trust from './acts/Trust';
import Beyond from './acts/Beyond';
import Toasts from './ui/Toasts';
import TopBar from './ui/TopBar';
import Overview from './room/Overview';
import Pipeline from './room/Pipeline';
import ProductsPage from './room/ProductsPage';
import Memory from './room/Memory';
import Analytics from './room/Analytics';
import Hardware from './room/Hardware';
import History from './room/History';
import Settings from './room/Settings';
import FlowBar from './ui/FlowBar';
import Approval from './line/Approval';
import SmtLine from './line/SmtLine';
import Quality from './line/Quality';
import Spc from './line/Spc';
import Rework from './line/Rework';
import Materials from './line/Materials';
import Bom from './line/Bom';
import XRay from './line/XRay';

// the main journey, in order: what an operator actually does, start to finish
const ACTS: { id: Act; title: string; sub: string }[] = [
  { id: 'choose', title: 'Choose a board', sub: 'public circuit boards or your own' },
  { id: 'genesis', title: 'Learn it', sub: '30 good boards, every component' },
  { id: 'interview', title: 'Answer questions', sub: 'before I inspect anything' },
  { id: 'line', title: 'Scan boards', sub: 'live, part by part, in 3D' },
  { id: 'approval', title: 'Approve', sub: 'the bench sign-off dossier' },
  { id: 'rework', title: 'Rework', sub: 'repair tickets' },
  { id: 'quality', title: 'Quality report', sub: 'FPY, DPMO, false calls' }
];

// deeper views of the line and the factory around it
const FACTORY: { id: Act; title: string }[] = [
  { id: 'xray', title: 'Board X-ray' },
  { id: 'smt', title: 'Line flow' },
  { id: 'spc', title: 'Process control' },
  { id: 'materials', title: 'Materials' },
  { id: 'bom', title: 'Component library' },
  { id: 'chaos', title: 'Change conditions' },
  { id: 'trust', title: 'Guarantee' },
  { id: 'beyond', title: 'Look ahead' }
];

const ROOM: { id: Act; title: string }[] = [
  { id: 'overview', title: 'Overview' },
  { id: 'pipeline', title: 'Pipeline' },
  { id: 'products', title: 'Products' },
  { id: 'memory', title: 'Memory' },
  { id: 'analytics', title: 'Analytics' },
  { id: 'hardware', title: 'Hardware' },
  { id: 'history', title: 'History' },
  { id: 'settings', title: 'Settings' }
];

const shortName = (n: string) => n.replace(/^\d+/, '');

function Products() {
  const { views, sessionId, setSessionId, setAct } = useStore();
  // electronics only: product lines from other sources stay on disk but are not shown
  // electronics only, and no empty leftovers: a line shows once it has scanned something, or if it is the one open now
  const list = Object.values(views).filter(v => (v.summary || v.photos.length) && v.summary?.source !== 'MAD-Sim' && (v.records.length > 0 || v.id === sessionId || v.stage === 'GENESIS'));
  const counts = list.reduce<Record<string, number>>((a, v) => { const n = shortName(v.summary?.displayName ?? v.summary?.name ?? v.id); a[n] = (a[n] ?? 0) + 1; return a; }, {});
  const dup = new Set(Object.keys(counts).filter(k => counts[k] > 1));
  if (!list.length) return null;
  return (
    <div className="hidden lg:block">
      <div className="label mb-1.5">Product lines</div>
      <ul className="space-y-1">
        {/* same product opened twice: show which line is which */}
        {list.map(v => {
          const name = v.summary?.displayName ?? v.summary?.name ?? v.narration[0]?.text.replace(/^Started /, '').split(' at ')[0] ?? v.id;
          return (
            <li key={v.id}>
              <button onClick={() => { setSessionId(v.id); if (v.stage === 'GENESIS') setAct('genesis'); }}
                className={`w-full text-left rounded-lg px-3 py-1.5 text-[13px] ${v.id === sessionId ? 'bg-raised text-bone' : 'text-mist hover:text-bone'}`}>
                {shortName(name)}
                <span className="text-xs text-mist"> · {v.summary?.plant ? `${v.summary.plant} · ` : ''}{v.records.length} boards{dup.has(shortName(name)) ? ` · ${v.id.split('-')[0]}` : ''}</span>
              </button>
            </li>
          );
        })}
      </ul>
      <button onClick={() => setAct('choose')} className="text-xs text-accent mt-2 px-3">+ open another board</button>
    </div>
  );
}

function Rail() {
  const { act, setAct, sessionId, live } = useStore();
  const Item = ({ id, title, sub, n, enabled = true }: { id: Act; title: string; sub?: string; n?: number; enabled?: boolean }) => {
    const on = act === id;
    return (
      <button disabled={!enabled} onClick={() => setAct(id)} aria-current={on ? 'page' : undefined}
        className={`relative w-full text-left rounded-lg pl-3 pr-2 py-1.5 flex gap-2.5 items-center transition disabled:opacity-30 ${on ? 'bg-raised text-bone' : 'text-mist hover:text-bone hover:bg-surface'}`}>
        {on && <span className="absolute left-0 top-1.5 bottom-1.5 w-0.5 rounded bg-accent" style={{ boxShadow: '0 0 8px var(--accent)' }} />}
        {n !== undefined && <span className={`mono text-[11px] w-4 ${on ? 'text-accent' : ''}`}>{String(n).padStart(2, '0')}</span>}
        <span className="min-w-0">
          <span className="block text-[13px] font-medium whitespace-nowrap">{title}</span>
          {sub && <span className="hidden lg:block text-[11px] text-mist leading-tight">{sub}</span>}
        </span>
      </button>
    );
  };
  return (
    <nav className="w-full lg:w-64 shrink-0 lg:h-screen lg:sticky lg:top-0 lg:overflow-y-auto px-4 py-5 flex flex-col gap-5 border-r border-line bg-ink/60 backdrop-blur [&>*]:shrink-0" aria-label="Navigation">
      <div className="flex items-center gap-3">
        <svg width="30" height="30" viewBox="0 0 32 32" aria-hidden><rect x="3" y="3" width="26" height="26" rx="7" fill="var(--accent)" /><circle cx="16" cy="16" r="5" fill="var(--ink)" /></svg>
        <div>
          <div className="display text-lg font-bold leading-none">Sandeha</div>
          <div className="label mt-1">knows when it doesn't know</div>
        </div>
      </div>
      <div>
        <div className="label mb-1.5 hidden lg:block">Journey</div>
        <ol className="flex lg:flex-col gap-0.5 overflow-x-auto lg:overflow-visible">
          {ACTS.map((a, i) => <li key={a.id}><Item id={a.id} title={a.title} sub={a.sub} n={i + 1} enabled={a.id === 'choose' || !!sessionId} /></li>)}
        </ol>
      </div>
      <div>
        <div className="label mb-1.5 hidden lg:block">Line &amp; factory</div>
        <ul className="flex lg:grid lg:grid-cols-2 gap-0.5 overflow-x-auto">
          {FACTORY.map(r => <li key={r.id}><Item id={r.id} title={r.title} enabled={!!sessionId} /></li>)}
        </ul>
      </div>
      <div>
        <div className="label mb-1.5 hidden lg:block">Control room</div>
        <ul className="flex lg:grid lg:grid-cols-2 gap-0.5 overflow-x-auto">
          {ROOM.map(r => <li key={r.id}><Item id={r.id} title={r.title} /></li>)}
        </ul>
      </div>
      <Products />
      <div className="mt-auto hidden lg:flex label items-center gap-2">
        <span className={`w-1.5 h-1.5 rounded-full ${live ? 'bg-pass' : 'bg-fail'}`} style={{ boxShadow: live ? '0 0 8px var(--pass)' : undefined }} />
        {live ? 'station online' : 'reconnecting'}
      </div>
    </nav>
  );
}

const SPEECH_LANG: Record<string, string> = { en: 'en-IN', hi: 'hi-IN', te: 'te-IN' };

function speak(text: string, lang: string) {
  if (!('speechSynthesis' in window)) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text.replace(/\[[^\]]*\]/g, ''));  // citations are for reading, not listening
  u.lang = SPEECH_LANG[lang] ?? 'en-IN';
  const v = window.speechSynthesis.getVoices().find(x => x.lang === u.lang) ?? window.speechSynthesis.getVoices().find(x => x.lang.startsWith(lang));
  if (v) u.voice = v;
  u.rate = 0.98;
  window.speechSynthesis.speak(u);
}

function AskBar() {
  const { sessionId, selectedRecord, view } = useStore();
  const [q, setQ] = useState('');
  const [lang, setLang] = useState('en');
  const [a, setA] = useState<{ answer: string; mode: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const [aloud, setAloud] = useState(true);
  const Rec: any = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
  if (!sessionId) return null;
  const rid = selectedRecord ?? view?.records[view.records.length - 1]?.id ?? null;
  const send = async (question: string) => {
    if (!question.trim()) return;
    setBusy(true);
    try {
      const res = await api.ask(sessionId, question, rid, lang);
      setA(res);
      if (aloud) speak(res.answer, lang);
    } catch (err: any) {
      setA({ answer: err.message, mode: 'error' });
    } finally {
      setBusy(false);
    }
  };
  const ask = (e: React.FormEvent) => { e.preventDefault(); send(q); };
  const listen = () => {
    if (!Rec) return;
    const r = new Rec();
    r.lang = SPEECH_LANG[lang];
    r.interimResults = false;
    r.onresult = (ev: any) => { const text = ev.results[0][0].transcript; setQ(text); send(text); };
    r.onend = () => setListening(false);
    r.onerror = () => setListening(false);
    setListening(true);
    r.start();
  };
  return (
    <div className="sticky bottom-0 z-20 mt-8 -mx-5 lg:-mx-8 px-5 lg:px-8 py-4 bg-ink/95 backdrop-blur border-t border-line">
      {a && (
        <div className="mb-3 max-w-4xl">
          <p className="voice text-xl leading-snug">{a.answer}</p>
          <p className="text-mist text-xs mt-1">Answered from the inspection evidence only · {a.mode}
            <button type="button" onClick={() => speak(a.answer, lang)} className="ml-3 text-doubt">Read aloud</button></p>
        </div>
      )}
      <form onSubmit={ask} className="flex gap-2 max-w-4xl">
        <input value={q} onChange={e => setQ(e.target.value)} placeholder={rid ? `Ask about ${rid}, e.g. "why did you doubt this part?"` : 'Ask Sandeha about the line'}
          className="flex-1 bg-surface rounded-xl px-4 py-2.5 text-bone placeholder:text-mist" aria-label="Question" />
        <select value={lang} onChange={e => setLang(e.target.value)} className="bg-surface rounded-xl px-3" aria-label="Answer language">
          <option value="en">English</option>
          <option value="hi">हिन्दी</option>
          <option value="te">తెలుగు</option>
        </select>
        {Rec && (
          <button type="button" onClick={listen} disabled={busy || listening} aria-label="Ask by voice"
            title="Ask by voice (uses your browser's speech service)"
            className={`px-3 rounded-xl font-semibold ${listening ? 'bg-fail text-ink' : 'bg-surface text-bone'}`}>
            {listening ? 'Listening…' : 'Speak'}
          </button>
        )}
        <label className="hidden md:flex items-center gap-1.5 text-xs text-mist px-1">
          <input type="checkbox" checked={aloud} onChange={e => setAloud(e.target.checked)} /> read answers
        </label>
        <button disabled={busy} className="px-4 rounded-xl bg-doubt text-ink font-semibold disabled:opacity-50">{busy ? 'Thinking…' : 'Ask'}</button>
      </form>
    </div>
  );
}

function Shell() {
  const { act, error, setError } = useStore();
  useEffect(() => { window.scrollTo({ top: 0 }); }, [act]);
  const Page = {
    choose: Choose, genesis: Genesis, interview: Interview, line: Line, chaos: Chaos, trust: Trust, beyond: Beyond,
    overview: Overview, pipeline: Pipeline, products: ProductsPage, memory: Memory, analytics: Analytics, hardware: Hardware,
    history: History, settings: Settings, approval: Approval, smt: SmtLine, quality: Quality, spc: Spc, rework: Rework,
    materials: Materials, bom: Bom, xray: XRay
  }[act];
  return (
    <div className="min-h-screen flex flex-col lg:flex-row">
      <Toasts />
      <Rail />
      <main className="flex-1 min-w-0 px-4 lg:px-7 flex flex-col">
        <TopBar />
        {act !== 'choose' && <FlowBar />}
        <div className="h-5" />
        {error && (
          <div role="alert" className="mb-4 bg-fail/15 text-fail rounded-xl px-4 py-2 flex justify-between gap-3">
            <span>{error}</span><button onClick={() => setError(null)} className="underline">Dismiss</button>
          </div>
        )}
        <div className="flex-1"><Page /></div>
        {act !== 'choose' && <AskBar />}
      </main>
    </div>
  );
}

export default function App() {
  return (
    <StoreProvider>
      <Shell />
    </StoreProvider>
  );
}
