export type NodeStatus = 'UP' | 'DEGRADED' | 'DOWN';
export type LinkStatus = NodeStatus;
export type NodeType = 'INTERNET_GATEWAY' | 'LOAD_BALANCER' | 'ROUTER' | 'NAT_GATEWAY' | 'APP_INSTANCE' | 'DATABASE';
export type DBRole = 'PRIMARY' | 'REPLICA';
export type Category = 'CHAOS' | 'HEALTH' | 'FAILOVER' | 'TRAFFIC';
export type Strategy = 'ROUND_ROBIN' | 'LEAST_CONNECTIONS';
export type ChaosAction = 'kill_node' | 'kill_az' | 'drop_link' | 'latency_spike' | 'packet_loss' | 'network_partition' | 'db_primary_failure' | 'recover';
export type SimulationAction = 'step' | 'start' | 'pause' | 'reset';

export interface TopologyResponse {
  vpc?: Record<string, unknown>;
  nodes?: unknown;
  links?: unknown;
  summary?: Record<string, unknown>;
}

export interface ApiErrorShape {
  detail?: string;
  message?: string;
}

export interface CloudNode {
  id: string;
  type: NodeType;
  az: string | null;
  subnet: string | null;
  status: NodeStatus;
  latency_ms: number;
  capacity: number;
  active_connections: number;
  db_role: DBRole | null;
}

export interface CloudLink {
  source: string;
  target: string;
  latency: number;
  bandwidth: number;
  status: LinkStatus;
  packet_loss: number;
  bidirectional: boolean;
}

export interface TickMetric {
  tick: number;
  requests_sent: number;
  requests_succeeded: number;
  requests_failed: number;
  success_rate_pct: number;
  avg_latency_ms: number;
  p95_latency_ms: number;
  healthy_app_capacity: number;
  active_incidents: number;
}

export interface TimelineEvent {
  id: string;
  tick: number;
  category: Category;
  event_type: string;
  target?: string;
  description: string;
  timestamp: string;
}

export interface ChartPoint {
  tick: number;
  avg: number;
  p95: number;
}

export const demoNodes: CloudNode[] = [
  { id: 'igw-main', type: 'INTERNET_GATEWAY', az: null, subnet: null, status: 'UP', latency_ms: 2, capacity: 1000, active_connections: 246, db_role: null },
  { id: 'lb-a', type: 'LOAD_BALANCER', az: 'us-east-1a', subnet: 'public-a', status: 'UP', latency_ms: 4, capacity: 500, active_connections: 132, db_role: null },
  { id: 'nat-a', type: 'NAT_GATEWAY', az: 'us-east-1a', subnet: 'public-a', status: 'UP', latency_ms: 7, capacity: 400, active_connections: 18, db_role: null },
  { id: 'router-a', type: 'ROUTER', az: 'us-east-1a', subnet: 'private-a', status: 'UP', latency_ms: 3, capacity: 500, active_connections: 132, db_role: null },
  { id: 'app-a1', type: 'APP_INSTANCE', az: 'us-east-1a', subnet: 'private-a', status: 'UP', latency_ms: 28, capacity: 125, active_connections: 48, db_role: null },
  { id: 'app-a2', type: 'APP_INSTANCE', az: 'us-east-1a', subnet: 'private-a', status: 'UP', latency_ms: 31, capacity: 125, active_connections: 42, db_role: null },
  { id: 'db-primary-a', type: 'DATABASE', az: 'us-east-1a', subnet: 'private-a', status: 'UP', latency_ms: 12, capacity: 250, active_connections: 84, db_role: 'PRIMARY' },
  { id: 'lb-b', type: 'LOAD_BALANCER', az: 'us-east-1b', subnet: 'public-b', status: 'UP', latency_ms: 4, capacity: 500, active_connections: 114, db_role: null },
  { id: 'nat-b', type: 'NAT_GATEWAY', az: 'us-east-1b', subnet: 'public-b', status: 'UP', latency_ms: 8, capacity: 400, active_connections: 14, db_role: null },
  { id: 'router-b', type: 'ROUTER', az: 'us-east-1b', subnet: 'private-b', status: 'UP', latency_ms: 3, capacity: 500, active_connections: 114, db_role: null },
  { id: 'app-b1', type: 'APP_INSTANCE', az: 'us-east-1b', subnet: 'private-b', status: 'UP', latency_ms: 29, capacity: 125, active_connections: 39, db_role: null },
  { id: 'app-b2', type: 'APP_INSTANCE', az: 'us-east-1b', subnet: 'private-b', status: 'UP', latency_ms: 30, capacity: 125, active_connections: 35, db_role: null },
  { id: 'db-replica-b', type: 'DATABASE', az: 'us-east-1b', subnet: 'private-b', status: 'UP', latency_ms: 14, capacity: 250, active_connections: 54, db_role: 'REPLICA' },
];

export const demoLinks: CloudLink[] = [
  { source: 'igw-main', target: 'lb-a', latency: 3, bandwidth: 10, status: 'UP', packet_loss: 0, bidirectional: false },
  { source: 'igw-main', target: 'lb-b', latency: 3, bandwidth: 10, status: 'UP', packet_loss: 0, bidirectional: false },
  { source: 'lb-a', target: 'router-a', latency: 2, bandwidth: 10, status: 'UP', packet_loss: 0, bidirectional: true },
  { source: 'router-a', target: 'nat-a', latency: 2, bandwidth: 8, status: 'UP', packet_loss: 0, bidirectional: true },
  { source: 'router-a', target: 'app-a1', latency: 1, bandwidth: 10, status: 'UP', packet_loss: 0, bidirectional: true },
  { source: 'router-a', target: 'app-a2', latency: 1, bandwidth: 10, status: 'UP', packet_loss: 0, bidirectional: true },
  { source: 'app-a1', target: 'db-primary-a', latency: 4, bandwidth: 10, status: 'UP', packet_loss: 0, bidirectional: true },
  { source: 'app-a2', target: 'db-primary-a', latency: 4, bandwidth: 10, status: 'UP', packet_loss: 0, bidirectional: true },
  { source: 'lb-b', target: 'router-b', latency: 2, bandwidth: 10, status: 'UP', packet_loss: 0, bidirectional: true },
  { source: 'router-b', target: 'nat-b', latency: 2, bandwidth: 8, status: 'UP', packet_loss: 0, bidirectional: true },
  { source: 'router-b', target: 'app-b1', latency: 1, bandwidth: 10, status: 'UP', packet_loss: 0, bidirectional: true },
  { source: 'router-b', target: 'app-b2', latency: 1, bandwidth: 10, status: 'UP', packet_loss: 0, bidirectional: true },
  { source: 'app-b1', target: 'db-replica-b', latency: 4, bandwidth: 10, status: 'UP', packet_loss: 0, bidirectional: true },
  { source: 'app-b2', target: 'db-replica-b', latency: 4, bandwidth: 10, status: 'UP', packet_loss: 0, bidirectional: true },
  { source: 'router-a', target: 'router-b', latency: 12, bandwidth: 5, status: 'UP', packet_loss: 0, bidirectional: true },
  { source: 'db-primary-a', target: 'db-replica-b', latency: 18, bandwidth: 5, status: 'UP', packet_loss: 0, bidirectional: true },
];
