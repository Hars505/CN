import type { ApiErrorShape, ChartPoint, CloudLink, CloudNode, TickMetric, TimelineEvent, TopologyResponse } from './types';
import { demoLinks, demoNodes } from './types';

const configuredApi = String(import.meta.env.VITE_API_BASE_URL ?? '').trim();
const sameOriginBackend = typeof window !== 'undefined' && window.location.port === '8000';
export const API_BASE = (configuredApi || (sameOriginBackend ? window.location.origin : 'http://127.0.0.1:8000')).replace(/\/$/, '');

const configuredWs = String(import.meta.env.VITE_WS_URL ?? '').trim();
export const WS_URL = configuredWs || (sameOriginBackend
  ? `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`
  : 'ws://127.0.0.1:8000/ws');

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 4000);
  try {
    const headers = new Headers(init?.headers);
    if (init?.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
    const response = await fetch(`${API_BASE}${path}`, {
      ...init,
      signal: controller.signal,
      headers,
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({} as ApiErrorShape));
      throw new Error(String(body.detail ?? body.message ?? `Backend returned ${response.status}`));
    }
    const responseText = await response.text();
    return (responseText ? JSON.parse(responseText) : {}) as T;
  } finally {
    window.clearTimeout(timeout);
  }
}

export const getTopology = () => request<TopologyResponse & Record<string, unknown>>('/topology');
export const getMetrics = () => request<Record<string, unknown>>('/metrics');
export const postSimulation = (endpoint: string, body: Record<string, unknown> = {}) =>
  request<Record<string, unknown>>(endpoint, { method: 'POST', body: JSON.stringify(body) });
export const postChaos = (eventType: string, body: Record<string, unknown>) =>
  request<Record<string, unknown>>(`/chaos/${eventType}`, { method: 'POST', body: JSON.stringify(body) });

const statuses = new Set(['UP', 'DEGRADED', 'DOWN']);

export function mergeNodes(input: unknown, current: CloudNode[] = demoNodes): CloudNode[] {
  const rows = Array.isArray(input)
    ? input
    : input && typeof input === 'object'
      ? Object.entries(input as Record<string, unknown>).map(([id, node]) => ({ id, ...(node as object) }))
      : [];
  if (!rows.length) return current;
  const incoming = new Map<string, Record<string, unknown>>();
  rows.forEach((row) => {
    if (row && typeof row === 'object' && 'id' in row) incoming.set(String((row as { id: unknown }).id), row as Record<string, unknown>);
  });

  const seenIds = new Set<string>();
  const updated = current.map((node) => {
    seenIds.add(node.id);
    const row = incoming.get(node.id);
    if (!row) return node;
    const rawStatus = String(row.status ?? node.status).toUpperCase();
    const role = String(row.db_role ?? node.db_role ?? '').toUpperCase();
    return {
      ...node,
      status: (statuses.has(rawStatus) ? rawStatus : node.status) as CloudNode['status'],
      latency_ms: numberFrom(row.latency_ms ?? row.latency, node.latency_ms),
      capacity: numberFrom(row.capacity, node.capacity),
      active_connections: numberFrom(row.active_connections ?? row.connections, node.active_connections),
      db_role: role === 'PRIMARY' || role === 'REPLICA' ? role : (role === 'NONE' || role === '' ? null : node.db_role),
    };
  });

  // Append any newly spawned dynamic instances (e.g. from AutoScaling)
  incoming.forEach((row, id) => {
    if (!seenIds.has(id)) {
      seenIds.add(id);
      const rawStatus = String(row.status ?? 'UP').toUpperCase();
      const role = String(row.db_role ?? '').toUpperCase();
      updated.push({
        id,
        type: String(row.type ?? 'APP_INSTANCE') as CloudNode['type'],
        az: typeof row.az === 'string' ? row.az : null,
        subnet: typeof row.subnet === 'string' ? row.subnet : null,
        status: (statuses.has(rawStatus) ? rawStatus : 'UP') as CloudNode['status'],
        latency_ms: numberFrom(row.latency_ms ?? row.latency, 25),
        capacity: numberFrom(row.capacity, 125),
        active_connections: numberFrom(row.active_connections ?? row.connections, 0),
        db_role: role === 'PRIMARY' || role === 'REPLICA' ? role : null,
      });
    }
  });

  return updated;
}

export function mergeLinks(input: unknown, current: CloudLink[] = demoLinks): CloudLink[] {
  if (!Array.isArray(input)) return current;
  const rows = input as Array<Record<string, unknown>>;
  if (!rows.length) return current;

  const seenKeys = new Set<string>();
  const updated = current.map((link) => {
    seenKeys.add(`${link.source}->${link.target}`);
    seenKeys.add(`${link.target}->${link.source}`);
    const row = rows.find((item) =>
      (String(item.source) === link.source && String(item.target) === link.target) ||
      (Boolean(item.bidirectional) && String(item.source) === link.target && String(item.target) === link.source),
    );
    if (!row) return link;
    const status = String(row.status ?? link.status).toUpperCase();
    return {
      ...link,
      status: (statuses.has(status) ? status : link.status) as CloudLink['status'],
      latency: numberFrom(row.latency, link.latency),
      bandwidth: numberFrom(row.bandwidth, link.bandwidth),
      packet_loss: numberFrom(row.packet_loss, link.packet_loss),
    };
  });

  // Append any newly added links
  rows.forEach((row) => {
    const src = String(row.source ?? '');
    const tgt = String(row.target ?? '');
    if (src && tgt && !seenKeys.has(`${src}->${tgt}`)) {
      seenKeys.add(`${src}->${tgt}`);
      seenKeys.add(`${tgt}->${src}`);
      const status = String(row.status ?? 'UP').toUpperCase();
      updated.push({
        source: src,
        target: tgt,
        latency: numberFrom(row.latency, 2),
        bandwidth: numberFrom(row.bandwidth, 10),
        status: (statuses.has(status) ? status : 'UP') as CloudLink['status'],
        packet_loss: numberFrom(row.packet_loss, 0),
        bidirectional: Boolean(row.bidirectional ?? true),
      });
    }
  });

  return updated;
}

const demoMetric: TickMetric = {
  tick: 54,
  requests_sent: 240,
  requests_succeeded: 239,
  requests_failed: 1,
  success_rate_pct: 99.58,
  avg_latency_ms: 42.6,
  p95_latency_ms: 86.2,
  healthy_app_capacity: 750,
  active_incidents: 0,
};
let lastMetric = demoMetric;

export function normalizeMetric(
  input: Record<string, unknown>,
  tickFallback = 0,
  fallback: TickMetric = lastMetric,
): TickMetric {
  const sent = numberFrom(input.requests_sent, fallback.requests_sent);
  const succeeded = numberFrom(input.requests_succeeded, fallback.requests_succeeded);
  const metric = {
    tick: numberFrom(input.tick, tickFallback),
    requests_sent: sent,
    requests_succeeded: succeeded,
    requests_failed: numberFrom(input.requests_failed, Math.max(0, sent - succeeded)),
    success_rate_pct: numberFrom(input.success_rate_pct, sent ? (succeeded / sent) * 100 : fallback.success_rate_pct),
    avg_latency_ms: numberFrom(input.avg_latency_ms, fallback.avg_latency_ms),
    p95_latency_ms: numberFrom(input.p95_latency_ms, fallback.p95_latency_ms),
    healthy_app_capacity: numberFrom(input.healthy_app_capacity, fallback.healthy_app_capacity),
    active_incidents: numberFrom(input.active_incidents, fallback.active_incidents),
  };
  lastMetric = metric;
  return metric;
}

export function metricRecord(input: Record<string, unknown>, tick: number, fallback?: TickMetric): TickMetric {
  return normalizeMetric(input, tick, fallback);
}

export function readChartSeries(input: unknown): ChartPoint[] | null {
  if (!Array.isArray(input)) return null;
  return input.slice(-28).map((point, index) => {
    const row = point as Record<string, unknown>;
    return {
      tick: numberFrom(row.tick, index),
      avg: numberFrom(row.avg_latency_ms ?? row.avg, 40),
      p95: numberFrom(row.p95_latency_ms ?? row.p95, 85),
    };
  });
}

export function normalizeEvents(input: unknown, tick: number): TimelineEvent[] {
  if (!Array.isArray(input)) return [];
  return input.map((entry, index) => {
    const event = entry as Record<string, unknown>;
    const category = String(event.category ?? 'TRAFFIC').toUpperCase();
    const allowed = new Set(['CHAOS', 'HEALTH', 'FAILOVER', 'TRAFFIC']);
    return {
      id: `${tick}-${index}-${Date.now()}`,
      tick: numberFrom(event.tick, tick),
      category: (allowed.has(category) ? category : 'TRAFFIC') as TimelineEvent['category'],
      event_type: String(event.event_type ?? 'event'),
      target: typeof event.target === 'string' ? event.target : undefined,
      description: String(event.description ?? event.message ?? 'Simulation event received'),
      timestamp: new Date().toISOString(),
    };
  });
}

function numberFrom(value: unknown, fallback: number): number {
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}
