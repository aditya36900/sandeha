import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, BackendEvent, Cloud, InspectionRecord, Policy, Question, Role, StationState, Summary, api, setApiRole, subscribe } from './api';

export type Act = 'choose' | 'genesis' | 'interview' | 'line' | 'chaos' | 'trust' | 'beyond'
  | 'overview' | 'pipeline' | 'products' | 'memory' | 'analytics' | 'hardware' | 'history' | 'settings'
  | 'approval' | 'smt' | 'quality' | 'spc' | 'rework' | 'materials' | 'bom' | 'xray' | 'pulse' | 'sentinel';
export type Theme = 'press' | 'lab' | 'industrial' | 'midnight' | 'paper';
export const THEMES: { id: Theme; title: string; hint: string }[] = [
  { id: 'press', title: 'Press', hint: 'editorial bento: paper, bold type, lime pop' },
  { id: 'lab', title: 'Lab bench', hint: 'graphite, cyan, scan effects' },
  { id: 'industrial', title: 'Industrial', hint: 'neutral dark, quiet blue' },
  { id: 'midnight', title: 'Midnight', hint: 'navy and amber' },
  { id: 'paper', title: 'Paper', hint: 'plain light' },
];
const THEME_IDS: Theme[] = ['press', 'lab', 'industrial', 'midnight', 'paper'];
const normTheme = (t: string | null): Theme => (t === 'dark' ? 'lab' : t === 'light' ? 'paper' : THEME_IDS.includes(t as Theme) ? (t as Theme) : 'press');

export interface Narration {
  t: number;
  text: string;
  tone?: 'pass' | 'fail' | 'doubt' | 'plain';
}

interface SessionView {
  id: string;
  photos: string[];
  cloud: (Cloud & { step?: number; total?: number }) | null;
  imagined: { kind: string; sizePct: number; score: number; thumb: string }[];
  questions: Question[];
  policy: Policy | null;
  records: InspectionRecord[];
  narration: Narration[];
  stage: string;
  alarm: boolean;
  patches?: number;
  summary?: Summary;
}

interface Store {
  act: Act;
  setAct: (a: Act) => void;
  live: boolean;
  sessionId: string | null;
  setSessionId: (id: string | null) => void;
  view: SessionView | null;
  views: Record<string, SessionView>;
  role: Role;
  setRole: (r: Role) => void;
  station: StationState | null;
  alerts: Alert[];
  reloadAlerts: () => void;
  theme: Theme;
  setTheme: (t: Theme) => void;
  reviewer: string;
  error: string | null;
  setError: (e: string | null) => void;
  start: (source: string, name: string, plant?: string, seed?: number, focus?: boolean) => Promise<string>;
  refresh: (id?: string) => Promise<void>;
  selectedRecord: string | null;
  setSelectedRecord: (id: string | null) => void;
  toasts: Toast[];
  dismissToast: (id: number) => void;
  notify: (text: string, tone?: Toast['tone']) => void;
}

export interface Toast {
  id: number;
  text: string;
  tone: 'pass' | 'fail' | 'doubt' | 'plain';
}

const Ctx = createContext<Store | null>(null);

const empty = (id: string): SessionView => ({
  id, photos: [], cloud: null, imagined: [], questions: [], policy: null, records: [], narration: [], stage: 'CREATED', alarm: false
});

function upsert(list: InspectionRecord[], r: InspectionRecord) {
  const i = list.findIndex(x => x.id === r.id);
  if (i === -1) return [...list, r].slice(-400);
  const next = list.slice();
  next[i] = r;
  return next;
}

export const StoreProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  // the page lives in the URL hash (#overview, #line …) so a page can be bookmarked or opened directly
  const PAGES: Act[] = ['choose', 'genesis', 'interview', 'line', 'chaos', 'trust', 'beyond', 'overview', 'pipeline', 'products',
    'memory', 'analytics', 'hardware', 'history', 'settings', 'approval', 'smt', 'quality', 'spc', 'rework', 'materials', 'bom', 'xray', 'pulse', 'sentinel'];
  const fromHash = (): Act => { const h = window.location.hash.slice(1) as Act; return PAGES.includes(h) ? h : 'choose'; };
  const [act, setActState] = useState<Act>(fromHash);
  const setAct = useCallback((a: Act) => {
    setActState(a);
    if (window.location.hash.slice(1) !== a) window.history.replaceState(null, '', `#${a}`);
  }, []);
  useEffect(() => {
    const on = () => setActState(fromHash());
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const [live, setLive] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [views, setViews] = useState<Record<string, SessionView>>({});
  const [role, setRoleState] = useState<Role>(() => {
    try { return (localStorage.getItem('sandeha.role') as Role) || 'INSPECTOR'; } catch { return 'INSPECTOR'; }
  });
  setApiRole(role);
  const setRole = useCallback((r: Role) => {
    setApiRole(r);
    setRoleState(r);
    try { localStorage.setItem('sandeha.role', r); } catch { /* private mode */ }
  }, []);
  const [theme, setThemeState] = useState<Theme>(() => {
    const q = new URLSearchParams(window.location.search).get('theme');
    if (q) return normTheme(q);
    try { return normTheme(localStorage.getItem('sandeha.theme')); } catch { return 'press'; }
  });
  const setTheme = useCallback((t: Theme) => {
    setThemeState(t);
    try { localStorage.setItem('sandeha.theme', t); } catch { /* private mode */ }
  }, []);
  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);
  const [station, setStation] = useState<StationState | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const reloadAlerts = useCallback(() => {
    api.alerts().then(setAlerts).catch(() => {});
    api.station().then(setStation).catch(() => {});
  }, []);
  useEffect(() => { reloadAlerts(); }, [reloadAlerts]);
  const [error, setError] = useState<string | null>(null);
  const [selectedRecord, setSelectedRecord] = useState<string | null>(null);
  const reviewer = ({ OPERATOR: 'Line operator', INSPECTOR: 'Rajesh K.', QUALITY_MANAGER: 'Sunita M.', ADMIN: 'Station admin' } as const)[role];
  const [toasts, setToasts] = useState<Toast[]>([]);
  const toastSeq = useRef(0);
  const toast = useCallback((text: string, tone: Toast['tone'] = 'plain') => {
    const id = ++toastSeq.current;
    setToasts(t => [...t.slice(-3), { id, text, tone }]);
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 7000);
  }, []);
  const dismissToast = useCallback((id: number) => setToasts(t => t.filter(x => x.id !== id)), []);

  const patch = useCallback((id: string, fn: (v: SessionView) => SessionView) => {
    setViews(prev => ({ ...prev, [id]: fn(prev[id] ?? empty(id)) }));
  }, []);

  const say = (v: SessionView, text: string, tone: Narration['tone'] = 'plain'): SessionView => ({
    ...v, narration: [...v.narration, { t: Date.now(), text, tone }].slice(-60)
  });

  const onEvent = useCallback((e: BackendEvent) => {
    const p = e.payload ?? {};
    const id: string | undefined = p.session;
    if (e.type === 'sessions.restored') {  // the station finished restoring saved product lines
      rehydrateRef.current();
      return;
    }
    if (e.type === 'station') {
      setStation(p as StationState);
      return;
    }
    if (e.type === 'alert') {
      const a = p as Alert;
      setAlerts(list => [a, ...list.filter(x => x.id !== a.id)].slice(0, 300));
      if (!a.acknowledged && !a.resolved && a.severity !== 'INFO') toast(`${a.title}: ${a.message}`, a.severity === 'CRITICAL' ? 'fail' : 'doubt');
      api.station().then(setStation).catch(() => {});
      return;
    }
    if (e.type === 'reset') {
      setViews({});
      setSessionId(null);
      setAct('choose');
      setAlerts([]);
      toast('Station reset. Re-seeding the demo product lines in the background.', 'plain');
      return;
    }
    if (e.type === 'board.ready' || e.type === 'board.skipped' || e.type === 'board.error') {
      toast(p.message, e.type === 'board.ready' ? 'pass' : 'doubt');
      return;
    }
    if (e.type === 'ai.ready') {
      toast(p.message, 'plain');
      return;
    }
    if (e.type === 'error') {
      setError(p.message);
      return;
    }
    if (e.type === 'shift.alarm') toast('The line changed. I stopped approving parts on my own until you show me 5 good ones.', 'doubt');
    if (e.type === 'shift.adapted') toast('Adapted to the new conditions. Nothing I knew before was forgotten.', 'pass');
    if (e.type === 'line.review' && /learned|added/.test(p.message ?? '')) toast(`Two people agreed, so I ${p.message.split(' - ')[1] ?? 'learned from it'}.`, 'pass');
    if (e.type === 'line.review' && /disagree/.test(p.message ?? '')) toast('Reviewers disagree. Escalated to the quality manager; I learned nothing.', 'doubt');
    if (e.type === 'hive.received') toast(p.message, 'pass');
    if (id && (e.type === 'line.exhausted' || e.type === 'line.batch_done')) {
      api.session(id).then(s => patch(id, v => ({ ...v, summary: s }))).catch(() => {});
    }
    if (e.type === 'line.exhausted') toast('All uploaded photos are inspected. Drop more under "Inspect your own photos".', 'plain');
    if (!id) return;
    switch (e.type) {
      case 'genesis.photos':
        patch(id, v => say({ ...v, photos: p.thumbs, stage: 'GENESIS' }, p.message));
        break;
      case 'genesis.carve':
        patch(id, v => say(p.cloud ? { ...v, cloud: { ...p.cloud, step: p.step, total: p.total } } : v, p.message));
        break;
      case 'genesis.features':
        patch(id, v => say({ ...v, patches: p.patches }, p.message));
        break;
      case 'genesis.imagination':
        patch(id, v => say(v, p.message, 'doubt'));
        break;
      case 'genesis.imagined':
        patch(id, v => say({ ...v, imagined: p.gallery }, p.message));
        break;
      case 'genesis.calibration':
        patch(id, v => say({ ...v, policy: p.policy }, p.message));
        break;
      case 'genesis.interview':
        patch(id, v => say({ ...v, questions: p.questions, stage: 'INTERVIEW' }, p.message, 'doubt'));
        break;
      case 'genesis.ready':
        patch(id, v => say({ ...v, summary: p.summary, stage: p.summary?.stage ?? v.stage }, p.message, 'pass'));
        break;
      case 'interview.answer':
        patch(id, v => say({ ...v, policy: p.policy, questions: v.questions.map(q => (q.id === p.qid ? { ...q, effect: p.effect, answered: 'yes' } : q)) }, p.effect));
        break;
      case 'line.record':
      case 'line.review':
        patch(id, v => ({ ...v, records: upsert(v.records, p.record) }));
        if (e.type === 'line.review') patch(id, v => say(v, p.message));
        break;
      case 'shift.alarm':
        patch(id, v => say({ ...v, alarm: true }, p.message, 'doubt'));
        break;
      case 'shift.adapted':
        patch(id, v => say({ ...v, alarm: false, policy: p.policy }, p.message, 'pass'));
        break;
      case 'trust.policy':
        patch(id, v => ({ ...v, policy: p.policy }));
        break;
      case 'chaos.conditions':
      case 'hive.received':
        patch(id, v => say(v, p.message));
        break;
    }
  }, [patch, toast]);

  useEffect(() => subscribe(onEvent, setLive), [onEvent]);

  // Rebuild every session the station already holds (page refresh mid-demo loses nothing).
  const rehydrate = useCallback(async () => {
      try {
        const list = await api.sessions();
        if (!list.length) return;
        const states = await Promise.all(list.map(x => api.state(x.id)));
        setViews(prev => {
          const next = { ...prev };
          states.forEach(st => {
            const id = st.summary.id;
            next[id] = {
              id, photos: st.photos, cloud: st.cloud, imagined: st.imagined, questions: st.summary.questions,
              policy: st.summary.policy, records: st.records, narration: st.narration, stage: st.summary.stage,
              alarm: st.summary.shiftAlarm, patches: st.patches ?? undefined, summary: st.summary
            };
          });
          return next;
        });
        const want = new URLSearchParams(window.location.search).get('session');
        const elec = list.filter(x => x.source !== 'MAD-Sim');
        setSessionId(cur => cur ?? (want && list.some(x => x.id === want) ? want : (elec[elec.length - 1] ?? list[list.length - 1]).id));
      } catch {
        /* station offline: the banner shows it */
      }
  }, []);
  const rehydrateRef = useRef(rehydrate);
  rehydrateRef.current = rehydrate;
  useEffect(() => { rehydrate(); }, [rehydrate]);

  const refresh = useCallback(async (id?: string) => {
    const sid = id ?? sessionId;
    if (!sid) return;
    const [s, recs] = await Promise.all([api.session(sid), api.records(sid)]);
    patch(sid, v => ({ ...v, summary: s, policy: s.policy ?? v.policy, questions: s.questions.length ? s.questions : v.questions,
      stage: s.stage, alarm: s.shiftAlarm, records: recs }));
  }, [sessionId, patch]);

  const start = useCallback(async (source: string, name: string, plant = 'Plant A', seed = 0, focus = true) => {
    const { id } = await api.create(source, name, plant, seed);
    patch(id, v => say(v, `Started ${name} at ${plant}`));
    if (focus) {
      setSessionId(id);
      setAct('genesis');
    }
    return id;
  }, [patch]);

  const value = useMemo<Store>(() => ({
    act, setAct, live, sessionId, setSessionId, view: sessionId ? views[sessionId] ?? null : null, views,
    role, setRole, reviewer, error, setError, start, refresh, selectedRecord, setSelectedRecord, toasts, dismissToast,
    station, alerts, reloadAlerts, theme, setTheme, notify: toast
  }), [act, live, sessionId, views, role, setRole, reviewer, error, start, refresh, selectedRecord, toasts, dismissToast,
    station, alerts, reloadAlerts, theme, setTheme, toast]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
};

export function useStore() {
  const c = useContext(Ctx);
  if (!c) throw new Error('useStore outside provider');
  return c;
}

export function useInterval(fn: () => void, ms: number, deps: unknown[] = []) {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => {
    const t = setInterval(() => ref.current(), ms);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}
