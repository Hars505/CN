import { demoNodes, type CloudNode, type TickMetric } from '../types';

export const guidedSteps = [
  { id: 'healthy', label: 'Healthy system', headline: 'Two zones. One healthy VPC.', detail: 'Requests are flowing across both availability zones.' },
  { id: 'failure', label: 'Failure injected', headline: 'Zone A is offline.', detail: 'A single zone failure is injected into the simulator.' },
  { id: 'detection', label: 'Detection lag', headline: 'Health checks confirm the failure.', detail: 'Failure detection takes time; the timeline makes that gap visible.' },
  { id: 'reroute', label: 'Traffic reroutes', headline: 'Traffic is moving through Zone B.', detail: 'The surviving availability zone continues to serve requests.' },
  { id: 'promotion', label: 'Database promotion', headline: 'Replica promoted to primary.', detail: 'The surviving replica takes the write role while the old primary is offline.' },
  { id: 'recovery', label: 'Recovery', headline: 'Zone A returns without split-brain.', detail: 'The returning database rejoins as a replica; there is still exactly one primary.' },
  { id: 'proof', label: 'Measured proof', headline: 'Recovery is measurable.', detail: 'Availability, latency and lost requests show the cost and the recovery.' },
] as const;

export type GuidedStepIndex = 0 | 1 | 2 | 3 | 4 | 5 | 6;

export interface DemoSummary {
  availability: number;
  detectionLag: number;
  requestsLost: number;
  healthyZones: number;
}

const localMetrics: TickMetric[] = [
  { tick: 0, requests_sent: 240, requests_succeeded: 240, requests_failed: 0, success_rate_pct: 100, avg_latency_ms: 34.2, p95_latency_ms: 68.4, healthy_app_capacity: 500, active_incidents: 0 },
  { tick: 1, requests_sent: 240, requests_succeeded: 236, requests_failed: 4, success_rate_pct: 98.33, avg_latency_ms: 49.8, p95_latency_ms: 121.5, healthy_app_capacity: 250, active_incidents: 1 },
  { tick: 2, requests_sent: 240, requests_succeeded: 233, requests_failed: 7, success_rate_pct: 97.08, avg_latency_ms: 55.1, p95_latency_ms: 148.2, healthy_app_capacity: 250, active_incidents: 1 },
  { tick: 3, requests_sent: 240, requests_succeeded: 237, requests_failed: 3, success_rate_pct: 98.75, avg_latency_ms: 44.3, p95_latency_ms: 102.6, healthy_app_capacity: 250, active_incidents: 1 },
  { tick: 4, requests_sent: 240, requests_succeeded: 238, requests_failed: 2, success_rate_pct: 99.17, avg_latency_ms: 40.2, p95_latency_ms: 88.1, healthy_app_capacity: 250, active_incidents: 1 },
  { tick: 5, requests_sent: 240, requests_succeeded: 239, requests_failed: 1, success_rate_pct: 99.58, avg_latency_ms: 38.6, p95_latency_ms: 79.3, healthy_app_capacity: 250, active_incidents: 0 },
  { tick: 6, requests_sent: 240, requests_succeeded: 240, requests_failed: 0, success_rate_pct: 100, avg_latency_ms: 35.1, p95_latency_ms: 70.7, healthy_app_capacity: 500, active_incidents: 0 },
];

const localSummaries: DemoSummary[] = [
  { availability: 100, detectionLag: 0, requestsLost: 0, healthyZones: 2 },
  { availability: 99.92, detectionLag: 0, requestsLost: 4, healthyZones: 1 },
  { availability: 99.81, detectionLag: 0.8, requestsLost: 11, healthyZones: 1 },
  { availability: 99.84, detectionLag: 0.8, requestsLost: 14, healthyZones: 1 },
  { availability: 99.84, detectionLag: 0.8, requestsLost: 16, healthyZones: 1 },
  { availability: 99.96, detectionLag: 0.8, requestsLost: 17, healthyZones: 2 },
  { availability: 99.98, detectionLag: 0.8, requestsLost: 17, healthyZones: 2 },
];

export function localMetricAt(step: number): TickMetric {
  return { ...localMetrics[Math.max(0, Math.min(6, step))] };
}

export function localSummaryAt(step: number): DemoSummary {
  return { ...localSummaries[Math.max(0, Math.min(6, step))] };
}

export function localNodesAt(step: number): CloudNode[] {
  return demoNodes.map((node) => {
    const inZoneA = node.az?.endsWith('a') ?? false;
    let status: CloudNode['status'] = node.status;
    let dbRole = node.db_role;
    let activeConnections = node.active_connections;

    if (step >= 1 && step <= 4 && inZoneA) status = 'DOWN';
    if (step >= 3 && node.type === 'APP_INSTANCE') {
      activeConnections = inZoneA ? 0 : node.id === 'app-b1' ? 82 : node.id === 'app-b2' ? 79 : node.active_connections;
    }
    if (step >= 4 && node.id === 'db-primary-a') {
      status = step >= 5 ? 'UP' : 'DOWN';
      dbRole = 'REPLICA';
    }
    if (step >= 4 && node.id === 'db-replica-b') dbRole = 'PRIMARY';
    if (step >= 5 && inZoneA && node.id !== 'db-primary-a') status = 'UP';
    if (step >= 5 && node.id === 'app-a1') activeConnections = 48;
    if (step >= 5 && node.id === 'app-a2') activeConnections = 42;
    if (step >= 5 && node.id === 'app-b1') activeConnections = 43;
    if (step >= 5 && node.id === 'app-b2') activeConnections = 40;

    return { ...node, status, db_role: dbRole, active_connections: activeConnections };
  });
}

export function isZoneADegraded(nodes: CloudNode[]): boolean {
  const zoneNodes = nodes.filter((node) => node.az?.endsWith('a'));
  return zoneNodes.length > 0 && zoneNodes.every((node) => node.status === 'DOWN');
}

export function isRecoveredWithoutSplitBrain(nodes: CloudNode[]): boolean {
  const zoneA = nodes.filter((node) => node.az?.endsWith('a'));
  const primaries = nodes.filter((node) => node.type === 'DATABASE' && node.db_role === 'PRIMARY');
  return zoneA.length > 0 && zoneA.every((node) => node.status === 'UP') && primaries.length === 1 && nodes.every((node) => node.status !== 'DOWN');
}
