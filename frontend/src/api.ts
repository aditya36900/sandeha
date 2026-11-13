export type Decision = 'PASS' | 'FAIL' | 'DOUBT' | 'HOLD';

export interface Policy {
  tau_pass: number;
  tau_fail: number;
  alpha_fr: number;
  beta: number;
  budget: number;
  expected_review_good: number;
  promised_escape: number;
  escape_upper_90: number;
  n_good_calib: number;
  n_defect_calib: number;
  budget_limited: boolean;
}

export interface Question {
  id: string;
  type: 'SUSPECT_REFERENCE' | 'VARIATION_ZONE' | 'COVERAGE_GAP' | 'SUFFICIENCY' | 'CRITICAL_ZONES';
  question: string;
  why: string;
  image?: string;
  crops?: string[];
  options: string[];
  answered?: string;
  effect?: string;
  zScore?: number;
  x?: number;
  y?: number;
}

export interface Precedent {
  kind: 'reference' | 'precedent';
  label: string;
  similarity: number;
  thumb?: string;
  image?: string;
  record?: string;
}

export interface InspectionRecord {
  id: string;
  session: string;
  index: number;
  decision: Decision;
  doubt_reason: 'BAD_IMAGE' | 'CONDITIONS_CHANGED' | 'NEVER_SEEN' | 'BORDERLINE' | null;
  score: number;
  uncertainty: number;
  naive_decision: 'PASS' | 'FAIL';
  truth: number | null;
  defect_type: string | null;
  image_url: string;
  heat_url: string;
  hotspot: { x: number; y: number; value: number };
  precedents: Precedent[];
  counterfactual: { query: string; reference: string; text: string } | null;
  explanation: string;
  conditions: Record<string, number>;
  martingale: number;
  p_value: number;
  novelty_p: number;
  created: string;
  review: { votes?: { by: string; verdict: string; reliability: number }[]; final?: string; status?: string; by?: string };
  ghost: boolean;
  twin_heat: number[] | null;
  pass_line: number | null;
  has_twin_heat?: boolean;
  hive_match: { label: string; from: string; similarity: number } | null;
  regions?: DefectRegion[] | null;
  signals?: { patchMemory: number; goldenDeviation: number; fused: number; gain: number; detectors: number } | null;
  diff_url?: string | null;
  board?: BoardCheck | null;
  synthetic?: string | null;
  quality?: { sharpness: number; exposure: number; glarePct: number } | null;
  stage_ms?: Record<string, number> | null;
  latency_ms?: number | null;
  hold_reason?: string | null;
}

export interface DefectRegion {
  id: string;
  label: string;
  similarity: number;
  namedBy: string;
  alternatives: { label: string; similarity: number }[];
  bbox: [number, number, number, number];
  centroid: [number, number];
  areaPct: number;
  extentPct: number;
  peak: number;
  relPeak: number;
  unusualness: number;
  severity: 'minor' | 'major' | 'critical';
  realOdds: number | null;
  crop?: string;
  anchor: [number, number, number] | null;
  component?: { id: string; kind: string };
}

export type CompStatus = 'OK' | 'MISSING' | 'ROTATED' | 'SHIFTED' | 'BURNT' | 'SOLDER' | 'WRONG_PART' | 'DAMAGED' | 'EXTRA';

export interface CompFault {
  id: string; kind: string; status: CompStatus; why: string[]; level: 'fault' | 'watch';
  measured?: Record<string, number | string>; bbox?: [number, number, number, number]; centroid?: [number, number];
}

export interface BoardCheck { checked: number; ok: number; faults: CompFault[]; summary: Record<string, number>; aligned?: string | null; chipCrops?: Record<string, string> }

export interface BoardComponent {
  id: string; kind: string; kindConfidence: number; namedBy: string;
  bbox: [number, number, number, number]; centroid: [number, number]; areaPct: number;
  box3d: { center: [number, number, number]; size: [number, number, number] } | null;
  history: Record<string, number>;
}

export interface BoardMapT {
  status: 'ready' | 'building' | 'none'; electronics: boolean;
  components?: BoardComponent[]; kinds?: Record<string, number>; golden?: string; calibration?: string;
  boardsChecked?: number; statusText?: Record<string, string>;
  classifier?: { holdoutAccuracy: number; holdout: number; train: number; perClassRecall: Record<string, number>; dataset: string } | null;
}

export interface LotPart { token: string; thumb: string }

export interface Cloud {
  positions: number[];
  colors: number[];
  normals: number[];
  count: number;
  cameras: { position: number[] }[];
  fg?: number[];
  grid?: number;
}

export interface Performance {
  n: number;
  defects?: number;
  good?: number;
  ours?: { escapes: number; falseRejects: number; reviewed: number };
  naive?: { escapes: number; falseRejects: number; reviewed: number };
  ourEscapeRate?: number;
  naiveEscapeRate?: number;
  ourReviewRate?: number;
  riskCoverage?: { review: number[]; escape: number[]; aurc: number } | null;
}

export interface Summary {
  id: string;
  source: string;
  name: string;
  plant: string;
  stage: string;
  refs: number;
  policy: Policy | null;
  shiftAlarm: boolean;
  records: number;
  questions: Question[];
  performance: Performance;
  forecast: Forecast;
  hasTwin: boolean;
  displayName?: string;
  relief?: boolean;
  uploadsLeft?: number | null;
  reviewers?: Record<string, { ghosts: number; ghostCorrect: number; reviews: number }>;
  learnedDefects: string[];
  hiveLibrary: string[];
  conditions: Record<string, number>;
  budget?: number;
  autopilot?: boolean;
  goldenUrl?: string | null;
  detectors?: number;
}

export interface Forecast {
  ready?: boolean;
  ewma?: number[];
  tauPass?: number;
  baseline?: number;
  partsUntilStorm?: number | null;
  drift?: number;
  status?: 'CLEAR' | 'DRIFTING' | 'STORM_COMING';
  hotspot?: { x: number; y: number; message: string } | null;
}

export interface CatalogItem {
  source: string;
  name: string;
  good: number;
  test: number;
  defects: number;
  defectTypes: string[];
  thumb: string;
}

export interface BackendEvent {
  type: string;
  ts: number;
  payload: any;
}

export type Role = 'OPERATOR' | 'INSPECTOR' | 'QUALITY_MANAGER' | 'ADMIN';
let ROLE: Role = 'INSPECTOR';
export const setApiRole = (r: Role) => { ROLE = r; };

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: { 'X-Role': ROLE, ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* not JSON */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

async function form<T>(path: string, fd: FormData): Promise<T> {
  const res = await fetch(path, { method: 'POST', body: fd, headers: { 'X-Role': ROLE } });
  if (!res.ok) {
    let detail = res.statusText;
    try { const j = await res.json(); detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail); } catch { /* not JSON */ }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export interface UploadResult { uid: string; saved: number; counts: { good: number; defect: number; test: number }; name: string }

export const api = {
  upload: (files: File[], kind: 'good' | 'defect' | 'test', uid?: string, name?: string, defectLabel?: string) => {
    const fd = new FormData();
    files.forEach(f => fd.append('files', f));
    const q = new URLSearchParams({ kind, ...(uid ? { uid } : {}), ...(name ? { name } : {}), ...(defectLabel ? { defectLabel } : {}) });
    return form<UploadResult>(`/api/uploads?${q}`, fd);
  },
  inspectBatch: (id: string, files: File[]) => {
    const fd = new FormData();
    files.forEach(f => fd.append('files', f));
    return form<{ accepted: number }>(`/api/sessions/${id}/inspect-batch`, fd);
  },
  inspect: (id: string, file: File) => { const fd = new FormData(); fd.append('file', file); return form<InspectionRecord>(`/api/sessions/${id}/inspect`, fd); },
  profile: () => req<any>('GET', '/api/profile'),
  version: () => req<{ commit: string; uiBuilt: string | null }>('GET', '/api/version'),
  vlmWarm: () => req<{ status: string }>('POST', '/api/vlm/warm'),
  fewshot: () => req<any>('GET', '/api/fewshot'),
  sentinel: (id: string) => req<any>('GET', `/api/sessions/${id}/sentinel`),
  sentinelReset: (id: string) => req<{ cleared: number }>('POST', `/api/sessions/${id}/sentinel/reset`),
  sentinelRun: (id: string, n = 6) => req<any>('POST', `/api/sessions/${id}/sentinel/run?n=${n}`),
  heat: (id: string, rid: string) => req<{ heat: number[] | null }>('GET', `/api/sessions/${id}/records/${rid}/heat`),
  queue: (id: string) => req<{ id: string; teachValue: number; why: string }[]>('GET', `/api/sessions/${id}/queue`),
  deleteSession: (id: string) => req('DELETE', `/api/sessions/${id}`),
  reportUrl: (id: string, download = false) => `/api/sessions/${id}/report${download ? '?download=true' : ''}`,
  csvUrl: (id: string) => `/api/sessions/${id}/decisions.csv`,
  catalog: () => req<CatalogItem[]>('GET', '/api/catalog'),
  create: (source: string, name: string, plant = 'Plant A', seed = 0) =>
    req<{ id: string }>('POST', '/api/sessions', { source, name, plant, seed }),
  sessions: () => req<Summary[]>('GET', '/api/sessions'),
  session: (id: string) => req<Summary>('GET', `/api/sessions/${id}`),
  state: (id: string) => req<SessionState>('GET', `/api/sessions/${id}/state`),
  twin: (id: string) => req<Cloud & { coverage: { covered: number } }>('GET', `/api/sessions/${id}/twin`),
  answer: (id: string, qid: string, option: string) => req<{ effect: string; policy: Policy }>('POST', `/api/sessions/${id}/answer`, { qid, option }),
  zones: (id: string, points: { x: number; y: number; r: number; strictness: number }[]) => req('POST', `/api/sessions/${id}/zones`, { points }),
  stream: (id: string, n: number, defectRate = 0.15, delay = 0.15) => req('POST', `/api/sessions/${id}/stream`, { n, defectRate, delay }),
  records: (id: string) => req<InspectionRecord[]>('GET', `/api/sessions/${id}/records`),
  review: (id: string, rid: string, verdict: 'GOOD' | 'DEFECT', reviewer: string, role: string) =>
    req<{ status: string; record: InspectionRecord }>('POST', `/api/sessions/${id}/records/${rid}/review`, { verdict, reviewer, role }),
  presets: () => req<Record<string, Record<string, number>>>('GET', '/api/chaos/presets'),
  conditions: (id: string, body: Record<string, number | string>) => req('POST', `/api/sessions/${id}/conditions`, body),
  preview: (id: string, conditions: Record<string, number>) => req<{ before: string; after: string }>('POST', `/api/sessions/${id}/preview`, conditions),
  adapt: (id: string, n = 5) => req<{ message: string }>('POST', `/api/sessions/${id}/adapt`, { n }),
  trust: (id: string, q = '') => req<TrustCurve>('GET', `/api/sessions/${id}/trust${q}`),
  setTarget: (id: string, targetEscape: number, budget = 0.1) => req<Policy>('POST', `/api/sessions/${id}/trust`, { targetEscape, budget }),
  performance: (id: string) => req<Performance>('GET', `/api/sessions/${id}/performance`),
  certificate: (id: string) => req<Certificate>('POST', `/api/sessions/${id}/certificate`),
  wear: (id: string, n = 60) => req('POST', `/api/sessions/${id}/wear?n=${n}`),
  hiveShare: (from: string, to: string) => req<{ shared: number; labels: string[]; bytesPerFingerprint: number }>('POST', `/api/sessions/${from}/hive/share`, { to }),
  galaxy: () => req<Galaxy>('GET', '/api/galaxy'),
  ask: (id: string, question: string, recordId: string | null, lang: string) =>
    req<{ answer: string; citations: string[]; mode: string }>('POST', `/api/sessions/${id}/ask`, { question, recordId, lang }),
  results: () => req<Record<string, any[]>>('GET', '/api/results'),
  blindSpots: (id: string, kind = 'scratch') => req<BlindSpots>('POST', `/api/sessions/${id}/blindspots?kind=${kind}`),
  edge: () => req<Edge>('GET', '/api/edge'),
  // ---- control room (station, alerts, analytics, history, hardware, settings, demos)
  station: () => req<StationState>('GET', '/api/station'),
  hold: (on: boolean, reason = '') => req<StationState>('POST', '/api/station/hold', { on, reason }),
  fault: (fault: string) => req<StationState>('POST', '/api/station/fault', { fault }),
  restore: () => req<StationState>('POST', '/api/station/restore'),
  telemetry: () => req<Telemetry>('GET', '/api/telemetry'),
  outbox: (limit = 60) => req<OutboxMsg[]>('GET', `/api/outbox?limit=${limit}`),
  audit: (limit = 200) => req<AuditRow[]>('GET', `/api/audit?limit=${limit}`),
  alerts: (openOnly = false) => req<Alert[]>('GET', `/api/alerts?open_only=${openOnly}`),
  ack: (id: string) => req<Alert>('POST', `/api/alerts/${id}/ack`),
  resolveAlert: (id: string) => req<Alert>('POST', `/api/alerts/${id}/resolve`),
  overview: () => req<Overview>('GET', '/api/overview'),
  analytics: (session?: string | null) => req<Analytics>('GET', `/api/analytics${session ? `?session=${session}` : ''}`),
  history: (q: Record<string, string | number | undefined>) => {
    const p = new URLSearchParams();
    Object.entries(q).forEach(([k, v]) => { if (v !== undefined && v !== '') p.set(k, String(v)); });
    return req<{ total: number; rows: HistoryRow[] }>('GET', `/api/history?${p}`);
  },
  historyCsvUrl: '/api/history.csv',
  passport: (rid: string) => req<Passport>('GET', `/api/passport/${rid}`),
  trace: (sid: string, rid: string) => req<Trace>('GET', `/api/sessions/${sid}/trace/${rid}`),
  memory: (sid: string) => req<MemorySummary>('GET', `/api/sessions/${sid}/memory`),
  forgetting: (sid: string) => req<{ history: ForgetRow[]; latest: ForgetRow; baseline: ForgetRow }>('POST', `/api/sessions/${sid}/forgetting`),
  productSettings: (sid: string, body: { budget?: number; falseRejectGuarantee?: number; autopilot?: boolean }) =>
    req<{ policy: Policy; budget: number; autopilot: boolean }>('POST', `/api/sessions/${sid}/settings`, body),
  settings: () => req<StationSettings>('GET', '/api/settings'),
  putSettings: (body: { name?: string; settings?: Record<string, number> }) => req<StationSettings>('PUT', '/api/settings', body),
  reset: (reseed = true) => req<{ ok: boolean }>('POST', `/api/system/reset?reseed=${reseed}`),
  demos: () => req<Demo[]>('GET', '/api/demo'),
  runDemo: (n: number, session: string | null) =>
    req<Demo & { message: string; decision?: string; record?: string; session?: string }>('POST', `/api/demo/${n}`, { session }),
  board: (id: string) => req<BoardMapT>('GET', `/api/sessions/${id}/board`),
  faultLab: (id: string, component: string, kind: string) => req<InspectionRecord>('POST', `/api/sessions/${id}/faultlab`, { component, kind }),
  smtLine: (id: string) => req<any>('GET', `/api/sessions/${id}/line`),
  spc: (id: string, comp: string) => req<any>('GET', `/api/sessions/${id}/spc/${comp}`),
  materials: (id: string) => req<any>('GET', `/api/sessions/${id}/materials`),
  rework: (id: string) => req<any[]>('GET', `/api/sessions/${id}/rework`),
  closeRework: (id: string, rid: string, outcome: string) => req<any>('POST', `/api/sessions/${id}/rework/${rid}`, { outcome }),
  setIpc: (id: string, klass: number) => req<{ ipcClass: number }>('POST', `/api/sessions/${id}/ipc`, { klass }),
  pulse: (id: string, n = 80) => req<any>('GET', `/api/sessions/${id}/pulse?n=${n}`),
  xray: (id: string) => req<any>('GET', `/api/sessions/${id}/xray`),
  chips: (id: string, rid: string) => req<any>('GET', `/api/sessions/${id}/chips/${rid}`),
  approvalQueue: (id: string) => req<any[]>('GET', `/api/sessions/${id}/approval`),
  dossier: (id: string, rid: string) => req<any>('GET', `/api/sessions/${id}/dossier/${rid}`),
  dossierVlm: (id: string, rid: string) => req<any>('GET', `/api/sessions/${id}/dossier/${rid}/vlm`),
  newLot: (id: string, n = 12) => req<{ lot: LotPart[] }>('POST', `/api/sessions/${id}/lot`, { n }),
  lot: (id: string) => req<{ lot: LotPart[] }>('GET', `/api/sessions/${id}/lot`),
  explain: (id: string, rid: string) =>
    req<{ facts: string; citations: string[]; vision: { region: string; text: string }[]; mode: string | null }>('POST', `/api/sessions/${id}/records/${rid}/explain`),
  scan: (id: string, token: string) => req<InspectionRecord>('POST', `/api/sessions/${id}/scan`, { token }),
};

export interface TrustRow {
  targetEscape: number;
  tauPass: number;
  reviewRate: number;
  escapeRate: number;
  escapeUpper90: number;
  ppm: number;
  inspectorHours: number;
  rupeesPerShift: number;
}

export interface TrustCurve {
  rows: TrustRow[];
  naive: { escapeRate: number; ppm: number; rupeesPerShift: number };
  assumptions: { prevalence: number; partsPerShift: number; reviewSeconds: number; costPerEscape: number; costPerReview: number };
  calibration: { good: number; realDefects: number; imaginedDefects: number };
}

export interface Certificate {
  claim: Record<string, any>;
  signature: string;
  publicKey: string;
  verifyUrl: string;
  qr: string;
}

export interface Galaxy {
  points: { session: string; product: string; kind: 'reference' | 'part'; decision?: Decision; truth?: number; position: number[]; productIndex: number; image?: string }[];
  products: { session: string; name: string; source: string; plant: string }[];
}

export function subscribe(onEvent: (e: BackendEvent) => void, onStatus: (ok: boolean) => void): () => void {
  let ws: WebSocket | null = null;
  let closed = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const connect = () => {
    ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
    ws.onopen = () => onStatus(true);
    ws.onmessage = m => {
      try {
        onEvent(JSON.parse(m.data));
      } catch {
        /* ignore */
      }
    };
    ws.onclose = () => {
      onStatus(false);
      if (!closed) timer = setTimeout(connect, 1500);
    };
    ws.onerror = () => ws?.close();
  };
  connect();
  return () => {
    closed = true;
    if (timer) clearTimeout(timer);
    ws?.close();
  };
}

export interface BlindSpots {
  image: string;
  cells: { x: number; y: number; state: 'sharp' | 'medium' | 'large' | 'blind' | 'untestable'; minSizePct: number | null }[];
  sizesPct: number[];
  kind: string;
  regions: number;
  blindCells: number;
  untestableCells: number;
  sharpCells: number;
  vlmChecked: number;
  method: string;
  medianMinSizePct: number | null;
  tested: number;
}

export interface Edge {
  measured: boolean;
  device?: string;
  sizeMBfp32?: number;
  sizeMBint8?: number;
  rows?: { precision: string; resolution: number; fps: number; msPerPart: number }[];
  note?: string;
}

export interface SessionState {
  summary: Summary;
  photos: string[];
  imagined: { kind: string; sizePct: number; score: number; thumb: string }[];
  cloud: Cloud | null;
  records: InspectionRecord[];
  narration: { t: number; text: string; tone: 'pass' | 'fail' | 'doubt' | 'plain' }[];
  patches: number | null;
}


// ------------------------------------------------------------------ control room types
export interface StationState {
  name: string; hold: boolean; holdReason: string | null; holdSince: string | null; faults: string[];
  settings: Record<string, number>; alertsOpen: number; alertsUnacknowledged: number;
}
export interface Alert {
  id: string; title: string; message: string; severity: 'INFO' | 'WARNING' | 'CRITICAL'; category: string;
  session: string | null; created: string; acknowledged: boolean; acknowledged_by: string | null; resolved: boolean; action: string | null;
}
export interface Telemetry {
  measured: {
    cpuPercent: number; cpuCores: number; ramPercent: number; ramUsedGB: number; ramTotalGB: number;
    gpu: Record<string, any> | null;
    diskFreeGB: number; savedSessionsMB: number; uptimeMin: number; inferenceMsP50: number | null; partsPerSecond: number | null;
    productLines: number; partsInspected: number;
  };
  simulated: Record<string, { status: string; [k: string]: any }>;
  [k: string]: any;
}
export interface OutboxMsg { t: string; channel: string; status: string; payload: Record<string, any> }
export interface AuditRow { t: string; who: string; role: string; action: string; target: string; detail: Record<string, any> }
export interface HistoryRow {
  id: string; session: string; product: string; decision: Decision; reason: string | null; score: number; truth: number | null;
  defectType: string | null; image: string; created: string; review: string | undefined; naive: string; latencyMs: number | null;
}
export interface Overview {
  totals: { parts: number; pass: number; fail: number; doubt: number; hold: number; reviewRate: number; holdRate: number };
  measured: { defectsSeen: number; escapes: number; escapesTypicalAI: number; falseRejects: number; falseRejectsTypicalAI: number; cost: number; costTypicalAI: number };
  latencyMsP50: number | null;
  trend: { minute: number; PASS: number; FAIL: number; DOUBT: number; HOLD: number }[];
  recent: HistoryRow[];
  products: { session: string; name: string; source: string; plant: string; stage: string; parts: number; pass: number; fail: number; doubt: number; hold: number; alarm: boolean; thumb: string | null }[];
  station: StationState;
  alerts: Alert[];
}
export interface Analytics {
  pareto: { type: string; caught: number; asked: number; escaped: number; held: number; escapedTypicalAI: number; total: number }[];
  spots: { x: number; y: number; decision: Decision; id: string; session: string }[];
  doubtReasons: Record<string, number>; holdReasons: Record<string, number>;
  timeline: { block: number; PASS: number; FAIL: number; DOUBT: number; HOLD: number }[];
  conditions: { normal: Record<string, number>; changed: Record<string, number>; nNormal: number; nChanged: number };
  productImage: string | null; forecast: Record<string, any> | null;
}
export interface Passport {
  record: InspectionRecord & { routing?: string };
  product: string; source: string; plant: string; session: string; policy: Policy; station: string;
  certificate: { certificate: string; hash: string; verifyUrl: string } | null;
}
export interface Trace {
  stages: { key: string; title: string; what: string; image?: string; facts: Record<string, any> }[];
  [k: string]: any;
}
export interface ForgetRow { label: string; goods: number; goodsPassed: number; defects: number; defectsFlagged: number; [k: string]: any }
export interface MemorySummary {
  normal: { references: number; patchMemories: number; learnedGood: { id: string; image: string; by: string }[]; adaptations: any[] };
  defect: { real: number; imagined: number; learned: { label: string; from: string; record: string | null; image: string | null }[]; hive: { label: string; from: string }[] };
  pending: { id: string; image: string; votes: { by: string; verdict: string }[] }[];
  forgetting: ForgetRow[];
}
export interface StationSettings {
  name: string; settings: Record<string, number>; roles: Role[]; names: Record<Role, string>; copilot: string;
  models: Record<string, string | null>;
}
export interface Demo { n: number; title: string; expect: string; goTo: string }
