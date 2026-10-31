import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  Activity, AlertTriangle, ArrowDownRight, ArrowUpRight, Bolt, Check, ChevronDown,
  CircleDot, Clock3, Cloud, Cpu, Database, Gauge, Globe2, Layers3, Link2,
  Network, Pause, Play, Radio, RotateCcw, Search, Server, ShieldCheck,
  SlidersHorizontal, Sparkles, StepForward, Terminal, Wifi, WifiOff, X, Zap,
} from 'lucide-react';
import { API_BASE, WS_URL, getMetrics, getTopology, mergeLinks, mergeNodes, metricRecord, normalizeEvents, normalizeMetric, postChaos, postSimulation, readChartSeries } from './api';
import { demoLinks, demoNodes, type Category, type ChartPoint, type ChaosAction, type CloudLink, type CloudNode, type NodeStatus, type Strategy, type TickMetric, type TimelineEvent } from './types';

const initialMetric: TickMetric = {
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

const seedChart: ChartPoint[] = Array.from({ length: 28 }, (_, index) => {
  const avg = 39 + Math.sin(index * 0.68) * 5 + (index > 20 ? index - 20 : 0) * 0.7;
  return { tick: 27 + index, avg, p95: avg * 1.92 + Math.cos(index) * 4 };
});

const makeSeedEvents = (): TimelineEvent[] => [
  { id: 'seed-1', tick: 54, category: 'TRAFFIC', event_type: 'request_batch', description: '240 requests processed · 99.6% success rate', timestamp: new Date(Date.now() - 13000).toISOString() },
  { id: 'seed-2', tick: 53, category: 'HEALTH', event_type: 'health_check', description: 'All AZ health checks passing', timestamp: new Date(Date.now() - 29000).toISOString() },
  { id: 'seed-3', tick: 52, category: 'FAILOVER', event_type: 'replication_sync', description: 'db-replica-b replication lag 4ms', timestamp: new Date(Date.now() - 46000).toISOString() },
  { id: 'seed-4', tick: 51, category: 'CHAOS', event_type: 'recovery', target: 'app-a2', description: 'Manual recovery completed · node healthy', timestamp: new Date(Date.now() - 67000).toISOString() },
  { id: 'seed-5', tick: 50, category: 'TRAFFIC', event_type: 'request_batch', description: '238 requests routed across 2 availability zones', timestamp: new Date(Date.now() - 84000).toISOString() },
];

const topologyNodes = [
  { id: 'igw-main', x: 434, y: 30, type: 'Gateway' },
  { id: 'lb-a', x: 62, y: 165, type: 'Load balancer' },
  { id: 'nat-a', x: 337, y: 165, type: 'NAT gateway' },
  { id: 'router-a', x: 52, y: 325, type: 'VPC router' },
  { id: 'app-a1', x: 160, y: 325, type: 'App instance' },
  { id: 'app-a2', x: 267, y: 325, type: 'App instance' },
  { id: 'db-primary-a', x: 371, y: 421, type: 'Database' },
  { id: 'lb-b', x: 548, y: 165, type: 'Load balancer' },
  { id: 'nat-b', x: 823, y: 165, type: 'NAT gateway' },
  { id: 'router-b', x: 508, y: 325, type: 'VPC router' },
  { id: 'app-b1', x: 616, y: 325, type: 'App instance' },
  { id: 'app-b2', x: 723, y: 325, type: 'App instance' },
  { id: 'db-replica-b', x: 827, y: 421, type: 'Database' },
] as const;

const edgePaths = [
  { source: 'igw-main', target: 'lb-a', path: 'M480 86 C400 106 240 111 111 165', flow: true },
  { source: 'igw-main', target: 'lb-b', path: 'M498 86 C575 106 705 111 597 165', flow: true },
  { source: 'lb-a', target: 'router-a', path: 'M111 227 L101 325', flow: true },
  { source: 'router-a', target: 'nat-a', path: 'M143 335 C210 273 320 254 384 227', flow: false },
  { source: 'router-a', target: 'app-a1', path: 'M150 357 L160 357', flow: true },
  { source: 'router-a', target: 'app-a2', path: 'M150 356 C192 386 228 386 267 356', flow: true },
  { source: 'app-a1', target: 'db-primary-a', path: 'M255 376 C303 394 363 398 415 421', flow: true },
  { source: 'app-a2', target: 'db-primary-a', path: 'M362 376 L415 421', flow: true },
  { source: 'lb-b', target: 'router-b', path: 'M597 227 L557 325', flow: true },
  { source: 'router-b', target: 'nat-b', path: 'M601 335 C680 273 805 254 870 227', flow: false },
  { source: 'router-b', target: 'app-b1', path: 'M606 357 L616 357', flow: true },
  { source: 'router-b', target: 'app-b2', path: 'M606 356 C650 386 686 386 723 356', flow: true },
  { source: 'app-b1', target: 'db-replica-b', path: 'M711 376 C760 394 820 398 871 421', flow: true },
  { source: 'app-b2', target: 'db-replica-b', path: 'M818 376 L871 421', flow: true },
  { source: 'router-a', target: 'router-b', path: 'M150 373 C280 471 417 471 508 373', cross: true, flow: false },
  { source: 'db-primary-a', target: 'db-replica-b', path: 'M467 451 C575 504 735 504 827 451', cross: true, flow: true },
] as const;

const actionOptions: { id: ChaosAction; title: string; description: string; icon: typeof Zap }[] = [
  { id: 'kill_node', title: 'Kill node', description: 'Force an instance offline', icon: X },
  { id: 'kill_az', title: 'Kill availability zone', description: 'Take an entire AZ offline', icon: AlertTriangle },
  { id: 'db_primary_failure', title: 'Crash primary DB', description: 'Trigger replica promotion', icon: Database },
  { id: 'network_partition', title: 'Network partition', description: 'Sever cross-AZ traffic', icon: Link2 },
  { id: 'latency_spike', title: 'Latency spike', description: 'Add 100ms processing delay', icon: Activity },
  { id: 'packet_loss', title: 'Packet loss', description: 'Drop 30% of link traffic', icon: ArrowDownRight },
  { id: 'drop_link', title: 'Drop link', description: 'Take a network link offline', icon: Link2 },
  { id: 'recover', title: 'Manual recovery', description: 'Restore a failed target', icon: RotateCcw },
];

const nodeStatusLabel: Record<NodeStatus, string> = { UP: 'Operational', DEGRADED: 'Degraded', DOWN: 'Offline' };

function formatNumber(value: number, decimals = 0) {
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: decimals, minimumFractionDigits: decimals }).format(value);
}

function timeLabel(value: string) {
  return new Date(value).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function PanelHeading({ icon, eyebrow, title, action }: { icon: ReactNode; eyebrow: string; title: string; action?: ReactNode }) {
  return (
    <div className="panel-heading">
      <div className="panel-heading-icon">{icon}</div>
      <div className="panel-heading-copy"><div className="eyebrow">{eyebrow}</div><h2>{title}</h2></div>
      {action && <div className="panel-heading-action">{action}</div>}
    </div>
  );
}

function StatusDot({ status }: { status: NodeStatus }) {
  return <span className={`status-dot status-${status.toLowerCase()}`} />;
}

function TopologyNode({ node, layout, selected, onSelect }: {
  node: CloudNode;
  layout: typeof topologyNodes[number];
  selected: boolean;
  onSelect: (node: CloudNode) => void;
}) {
  const isPrimary = node.db_role === 'PRIMARY';
  const isReplica = node.db_role === 'REPLICA';
  const serviceTag = node.type === 'DATABASE' ? 'DB' : node.type === 'APP_INSTANCE' ? 'APP' : node.type === 'LOAD_BALANCER' ? 'LB' : node.type === 'NAT_GATEWAY' ? 'NAT' : node.type === 'ROUTER' ? 'RTR' : 'IGW';
  return (
    <g className={`topology-node status-${node.status.toLowerCase()} ${selected ? 'is-selected' : ''}`} transform={`translate(${layout.x} ${layout.y})`} onClick={() => onSelect(node)} role="button" tabIndex={0} aria-label={`${node.id}, ${nodeStatusLabel[node.status]}`} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') onSelect(node); }}>
      <title>{`${node.id} · ${nodeStatusLabel[node.status]} · ${node.latency_ms}ms`}</title>
      <rect className="node-shell" width="96" height="62" rx="11" />
      <rect className="node-topline" x="1" y="1" width="94" height="2" rx="1" />
      <circle className="node-health" cx="12" cy="15" r="3.2" />
      <text className="node-tag" x="21" y="18">{serviceTag}</text>
      <text className="node-label" x="10" y="37">{node.id}</text>
      <text className="node-latency" x="10" y="52">{node.status === 'DOWN' ? 'NO SIGNAL' : `${formatNumber(node.latency_ms)} ms`}<tspan className="node-capacity"> · {node.active_connections} conn</tspan></text>
      {(isPrimary || isReplica) && <g className={`db-role ${isPrimary ? 'primary' : 'replica'}`} transform="translate(64 1)"><rect width="31" height="15" rx="5" /><text x="15.5" y="10.7" textAnchor="middle">{isPrimary ? '♛ PRI' : '◈ RPL'}</text></g>}
    </g>
  );
}

function Sparkline({ points }: { points: ChartPoint[] }) {
  const max = Math.max(100, ...points.map((point) => point.p95 * 1.12));
  const xy = (value: number, index: number) => `${12 + index * (296 / Math.max(1, points.length - 1))},${68 - (value / max) * 59}`;
  const avgPath = points.map((point, index) => `${index ? 'L' : 'M'}${xy(point.avg, index)}`).join(' ');
  const p95Path = points.map((point, index) => `${index ? 'L' : 'M'}${xy(point.p95, index)}`).join(' ');
  const areaPath = `${p95Path} L308,68 L12,68 Z`;
  return (
    <svg className="sparkline" viewBox="0 0 320 78" role="img" aria-label="Average and P95 latency history">
      <defs><linearGradient id="latency-fill" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="#2dd4bf" stopOpacity=".16"/><stop offset="1" stopColor="#2dd4bf" stopOpacity="0"/></linearGradient></defs>
      {[18, 42, 66].map((y) => <line key={y} x1="10" y1={y} x2="310" y2={y} className="chart-grid" />)}
      <path d={areaPath} fill="url(#latency-fill)" />
      <path d={p95Path} className="chart-line chart-p95" />
      <path d={avgPath} className="chart-line chart-avg" />
      {points.length > 0 && <><circle cx={xy(points[points.length - 1].avg, points.length - 1).split(',')[0]} cy={xy(points[points.length - 1].avg, points.length - 1).split(',')[1]} r="3" className="chart-last" /><circle cx={xy(points[points.length - 1].p95, points.length - 1).split(',')[0]} cy={xy(points[points.length - 1].p95, points.length - 1).split(',')[1]} r="3" className="chart-last-p95" /></>}
    </svg>
  );
}

export default function App() {
  const [nodes, setNodes] = useState<CloudNode[]>(demoNodes);
  const [links, setLinks] = useState<CloudLink[]>(demoLinks);
  const [tick, setTick] = useState(54);
  const [metric, setMetric] = useState<TickMetric>(initialMetric);
  const [chart, setChart] = useState<ChartPoint[]>(seedChart);
  const [events, setEvents] = useState<TimelineEvent[]>(makeSeedEvents);
  const [connected, setConnected] = useState(false);
  const [apiHealthy, setApiHealthy] = useState(false);
  const [running, setRunning] = useState(false);
  const [speed, setSpeed] = useState(2);
  const [strategy, setStrategy] = useState<Strategy>('ROUND_ROBIN');
  const [selectedNode, setSelectedNode] = useState<CloudNode | null>(null);
  const [action, setAction] = useState<ChaosAction>('kill_node');
  const [target, setTarget] = useState('app-a1');
  const [duration, setDuration] = useState(10);
  const [selectedAz, setSelectedAz] = useState<'az-a' | 'az-b'>('az-a');
  const [selectedLink, setSelectedLink] = useState('app-a1|db-primary-a');
  const [partitioned, setPartitioned] = useState(false);
  const [linkOverrides, setLinkOverrides] = useState<Record<string, NodeStatus>>({});
  const [filter, setFilter] = useState('ALL');
  const [search, setSearch] = useState('');
  const [stats, setStats] = useState({ availability: 99.98, mttr: 2.4, detection: 0.8, requestsLost: 0, totalCapacity: 1000 });
  const [temporaryFailures, setTemporaryFailures] = useState<Record<string, number>>({});
  const socketRef = useRef<WebSocket | null>(null);
  const terminalRef = useRef<HTMLDivElement | null>(null);
  const demoCounter = useRef(0);
  const tickRef = useRef(tick);
  tickRef.current = tick;

  const appendEvent = useCallback((category: Category, description: string, eventTarget?: string, eventType = 'notice') => {
    const entry: TimelineEvent = {
      id: `${Date.now()}-${Math.random().toString(16).slice(2, 7)}`,
      tick: tickRef.current,
      category,
      event_type: eventType,
      target: eventTarget,
      description,
      timestamp: new Date().toISOString(),
    };
    setEvents((current) => [entry, ...current].slice(0, 80));
  }, []);

  const applyMetric = useCallback((nextMetric: TickMetric) => {
    setTick(nextMetric.tick);
    setMetric(nextMetric);
    setChart((current) => [...current, { tick: nextMetric.tick, avg: nextMetric.avg_latency_ms, p95: nextMetric.p95_latency_ms }].slice(-28));
    if (nextMetric.active_incidents > 0) setStats((current) => ({ ...current, requestsLost: current.requestsLost + nextMetric.requests_failed }));
  }, []);

  function routeDemoTraffic(nextTick: number) {
    setNodes((current) => {
      const healthyApps = current.filter((node) => node.type === 'APP_INSTANCE' && node.status !== 'DOWN');
      if (!healthyApps.length) return current;
      const connections = new Map(healthyApps.map((node) => [node.id, Math.floor(node.active_connections * 0.94)]));
      for (let request = 0; request < 10; request += 1) {
        const receiver = strategy === 'ROUND_ROBIN'
          ? healthyApps[(nextTick * 10 + request) % healthyApps.length]
          : healthyApps.reduce((least, node) => (connections.get(node.id) ?? 0) < (connections.get(least.id) ?? 0) ? node : least, healthyApps[0]);
        connections.set(receiver.id, (connections.get(receiver.id) ?? 0) + 1);
      }
      return current.map((node) => connections.has(node.id) ? { ...node, active_connections: connections.get(node.id) ?? node.active_connections } : node);
    });
  }

  useEffect(() => {
    const expired = Object.entries(temporaryFailures).filter(([, expiryTick]) => tick >= expiryTick);
    if (!expired.length) return;
    const expiredTargets = new Set(expired.map(([eventTarget]) => eventTarget));
    setNodes((current) => current.map((node) => {
      const affectedZone = (expiredTargets.has('az-a') && node.az?.endsWith('a')) || (expiredTargets.has('az-b') && node.az?.endsWith('b'));
      return affectedZone || expiredTargets.has(node.id) ? { ...node, status: 'UP' } : node;
    }));
    setTemporaryFailures((current) => {
      const next = { ...current };
      expiredTargets.forEach((eventTarget) => delete next[eventTarget]);
      return next;
    });
    expired.forEach(([eventTarget]) => appendEvent('CHAOS', `${eventTarget} automatically recovered after its scheduled failure window`, eventTarget, 'automatic_recovery'));
  }, [tick, temporaryFailures, appendEvent]);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let reconnectTimer = 0;
    let disposed = false;

    const connect = () => {
      if (disposed) return;
      try {
        socket = new WebSocket(WS_URL);
        socketRef.current = socket;
        socket.onopen = () => {
          setConnected(true);
          setApiHealthy(true);
          appendEvent('HEALTH', 'WebSocket control channel established', undefined, 'connection');
        };
        socket.onmessage = (event) => {
          try {
            const message = JSON.parse(event.data) as Record<string, unknown>;
            const type = String(message.type ?? '').toUpperCase();
            if (type === 'INITIAL_STATE') {
              const topology = (message.topology ?? {}) as Record<string, unknown>;
              setNodes((current) => mergeNodes(topology.nodes, current));
              setLinks((current) => mergeLinks(topology.links, current));
              const initial = message.metric as Record<string, unknown> | undefined;
              if (initial) applyMetric(normalizeMetric({ ...initial, tick: message.tick ?? initial.tick }, tickRef.current));
              else if (typeof message.tick === 'number') setTick(message.tick);
              setRunning(Boolean(message.is_running));
              const summary = message.summary as Record<string, unknown> | undefined;
              if (summary) {
                setStats((current) => ({
                  ...current,
                  availability: number(summary.availability_pct ?? summary.availability, current.availability),
                  mttr: number(summary.mean_failover_time_ticks ?? summary.mttr, current.mttr),
                  detection: number(summary.mean_detection_time_ticks ?? summary.detection_lag, current.detection),
                }));
              }
              appendEvent('HEALTH', 'Initial VPC state synchronized', undefined, 'sync');
            }
            if (type === 'TICK_UPDATE') {
              const nextTick = number(message.tick, tickRef.current + 1);
              if (message.metric && typeof message.metric === 'object') applyMetric(normalizeMetric(message.metric as Record<string, unknown>, nextTick));
              else setTick(nextTick);
              if (message.topology && typeof message.topology === 'object') {
                const topology = message.topology as Record<string, unknown>;
                setNodes((current) => mergeNodes(topology.nodes, current));
                setLinks((current) => mergeLinks(topology.links, current));
              }
              if (message.topology_summary && typeof message.topology_summary === 'object') {
                const summary = message.topology_summary as Record<string, unknown>;
                setNodes((current) => mergeNodes(summary.nodes, current));
                setLinks((current) => mergeLinks(summary.links, current));
                setStats((current) => ({
                  ...current,
                  availability: number(summary.availability_pct ?? summary.availability, current.availability),
                  mttr: number(summary.mean_failover_time_ticks ?? summary.mttr, current.mttr),
                  detection: number(summary.mean_detection_time_ticks ?? summary.detection_lag, current.detection),
                }));
              }
              if (message.summary && typeof message.summary === 'object') {
                const summary = message.summary as Record<string, unknown>;
                setStats((current) => ({
                  ...current,
                  availability: number(summary.availability_pct ?? summary.availability, current.availability),
                  mttr: number(summary.mean_failover_time_ticks ?? summary.mttr, current.mttr),
                  detection: number(summary.mean_detection_time_ticks ?? summary.detection_lag, current.detection),
                }));
              }
              if (Array.isArray(message.events)) {
                const incoming = normalizeEvents(message.events, nextTick);
                if (incoming.length) setEvents((current) => [...incoming.reverse(), ...current].slice(0, 80));
              }
            }
            if (type === 'CHAOS_INJECTED') {
              if (message.topology && typeof message.topology === 'object') {
                const topology = message.topology as Record<string, unknown>;
                setNodes((current) => mergeNodes(topology.nodes, current));
                setLinks((current) => mergeLinks(topology.links, current));
              }
              if (message.summary && typeof message.summary === 'object') {
                const summary = message.summary as Record<string, unknown>;
                setStats((current) => ({
                  ...current,
                  availability: number(summary.availability_pct ?? summary.availability, current.availability),
                  mttr: number(summary.mean_failover_time_ticks ?? summary.mttr, current.mttr),
                  detection: number(summary.mean_detection_time_ticks ?? summary.detection_lag, current.detection),
                }));
              }
              const chaosEvt = message.chaos_event as Record<string, unknown> | undefined;
              if (chaosEvt) {
                const desc = `${String(chaosEvt.action ?? 'INJECT')}: ${String(chaosEvt.event_type ?? 'chaos')} on ${String(chaosEvt.target ?? 'topology')}`;
                appendEvent('CHAOS', desc, typeof chaosEvt.target === 'string' ? chaosEvt.target : undefined, String(chaosEvt.event_type ?? 'chaos'));
              }
            }
            if (type === 'SIMULATION_STATE') {
              setRunning(Boolean(message.is_running));
              if (typeof message.tick === 'number') setTick(message.tick);
            }
            if (type === 'SIMULATION_RESET') {
              setRunning(false);
              setTick(0);
              setTemporaryFailures({});
              setPartitioned(false);
              setLinkOverrides({});
              if (message.topology && typeof message.topology === 'object') {
                const topology = message.topology as Record<string, unknown>;
                setNodes((current) => mergeNodes(topology.nodes, current));
                setLinks((current) => mergeLinks(topology.links, current));
              }
              if (message.summary && typeof message.summary === 'object') {
                const summary = message.summary as Record<string, unknown>;
                setStats((current) => ({
                  ...current,
                  availability: number(summary.availability_pct ?? summary.availability, 100),
                  mttr: number(summary.mean_failover_time_ticks ?? summary.mttr, 0),
                  detection: number(summary.mean_detection_time_ticks ?? summary.detection_lag, 0),
                  requestsLost: 0,
                }));
              }
              appendEvent('HEALTH', 'Simulation reset to tick 0000', undefined, 'reset');
            }
            if (message.type === 'EVENT' || message.event) {
              const incoming = normalizeEvents([message.event ?? message], tickRef.current);
              setEvents((current) => [...incoming, ...current].slice(0, 80));
            }
          } catch {
            appendEvent('HEALTH', 'Received an unreadable WebSocket message', undefined, 'protocol_warning');
          }
        };
        socket.onclose = () => {
          setConnected(false);
          if (!disposed) reconnectTimer = window.setTimeout(connect, 2500);
        };
        socket.onerror = () => socket?.close();
      } catch {
        setConnected(false);
        reconnectTimer = window.setTimeout(connect, 2500);
      }
    };

    connect();
    void getTopology().then((response) => {
      const topology = (response.topology ?? response) as Record<string, unknown>;
      setNodes((current) => mergeNodes(topology.nodes, current));
      setLinks((current) => mergeLinks(topology.links, current));
      setApiHealthy(true);
      appendEvent('HEALTH', 'Topology loaded from REST API', undefined, 'sync');
    }).catch(() => undefined);
    void getMetrics().then((response) => {
      setApiHealthy(true);
      const series = readChartSeries(response.series ?? response.timeline);
      if (series?.length) setChart(series);
      const nextMetric = normalizeMetric(response as Record<string, unknown>, number(response.total_ticks, 54));
      if (response.avg_latency_ms !== undefined || response.total_ticks !== undefined) {
        setMetric(nextMetric);
        setTick(nextMetric.tick);
      }
      setStats((current) => ({
        ...current,
        availability: number(response.availability_pct, current.availability),
        mttr: number(response.mean_failover_time_ticks, current.mttr),
        detection: number(response.mean_detection_time_ticks, current.detection),
      }));
    }).catch(() => undefined);

    return () => {
      disposed = true;
      window.clearTimeout(reconnectTimer);
      socketRef.current = null;
      socket?.close();
    };
    // One socket is maintained for the lifetime of the dashboard.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!running) return undefined;
    if (!connected && !apiHealthy) {
      const timer = window.setInterval(() => {
        demoCounter.current += 1;
        const nextTick = tick + 1;
        const wave = Math.sin(nextTick * 0.42);
        const nextMetric: TickMetric = {
          tick: nextTick,
          requests_sent: 240 + Math.round(wave * 8),
          requests_succeeded: 238 + Math.round(wave * 6),
          requests_failed: wave < -0.7 ? 3 : 1,
          success_rate_pct: wave < -0.7 ? 98.7 : 99.58,
          avg_latency_ms: 40 + (wave + 1) * 5.5,
          p95_latency_ms: 80 + (wave + 1) * 12,
          healthy_app_capacity: nodes.filter((node) => node.type === 'APP_INSTANCE' && node.status !== 'DOWN').length * 125,
          active_incidents: nodes.some((node) => node.status === 'DOWN') ? 1 : 0,
        };
        routeDemoTraffic(nextTick);
        applyMetric(nextMetric);
        if (demoCounter.current % 3 === 0) appendEvent('TRAFFIC', `${nextMetric.requests_sent} requests routed · ${nextMetric.success_rate_pct.toFixed(1)}% success`, undefined, 'request_batch');
      }, 1000 / speed);
      return () => window.clearInterval(timer);
    }
    if (!connected && apiHealthy) {
      const timer = window.setInterval(() => {
        void getMetrics().then((response) => {
          const next = metricRecord(response, number(response.total_ticks, tick));
          setMetric(next);
          setTick(next.tick);
          setStats((current) => ({ ...current, availability: number(response.availability_pct, current.availability), mttr: number(response.mean_failover_time_ticks, current.mttr), detection: number(response.mean_detection_time_ticks, current.detection) }));
          const series = readChartSeries(response.series ?? response.timeline);
          if (series?.length) setChart(series);
        }).catch(() => setApiHealthy(false));
      }, 2500);
      return () => window.clearInterval(timer);
    }
    return undefined;
  }, [running, connected, apiHealthy, speed, tick, nodes, strategy, applyMetric, appendEvent]);

  useEffect(() => {
    if (terminalRef.current) terminalRef.current.scrollTop = 0;
  }, [events.length]);

  const nodeById = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  const selected = selectedNode ? nodeById.get(selectedNode.id) ?? selectedNode : null;
  const visibleEvents = useMemo(() => events.filter((event) => {
    const matchesCategory = filter === 'ALL' || event.category === filter;
    const query = search.trim().toLowerCase();
    return matchesCategory && (!query || `${event.description} ${event.target ?? ''} ${event.event_type}`.toLowerCase().includes(query));
  }), [events, filter, search]);
  const healthyApps = nodes.filter((node) => node.type === 'APP_INSTANCE' && node.status !== 'DOWN').length;
  const availability = Math.max(0, Math.min(100, stats.availability));
  const appCapacity = metric.healthy_app_capacity || healthyApps * 125;
  const capacityPct = Math.min(100, (appCapacity / stats.totalCapacity) * 100);

  async function control(actionName: 'start' | 'pause' | 'step' | 'reset') {
    const ws = socketRef.current;
    const requestBody = actionName === 'start' ? { tick_rate_hz: speed, requests_per_tick: 10 } : {};
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ action: actionName, ...(actionName === 'start' ? { tick_rate_hz: speed } : {}) }));
      setApiHealthy(true);
      if (actionName === 'start') setRunning(true);
      if (actionName === 'pause') setRunning(false);
      if (actionName === 'reset') { setRunning(false); setTick(0); setTemporaryFailures({}); }
      if (actionName === 'step') appendEvent('TRAFFIC', 'Single simulation tick requested', undefined, 'step');
      return;
    }

    const endpoint = `/simulation/${actionName}`;
    let response: Record<string, unknown> | null = null;
    try {
      response = await postSimulation(endpoint, requestBody);
      setApiHealthy(true);
    } catch {
      setApiHealthy(false);
    }
    if (actionName === 'start') {
      setRunning(true);
      appendEvent('HEALTH', response ? `Simulation started at ${speed.toFixed(1)} ticks/sec` : 'Demo simulation started · backend not connected', undefined, 'simulation_start');
    } else if (actionName === 'pause') {
      setRunning(false);
      appendEvent('HEALTH', 'Simulation paused', undefined, 'simulation_pause');
    } else if (actionName === 'step') {
      const nextTick = number(response?.tick, tick + 1);
      setTick(nextTick);
      if (response?.metric && typeof response.metric === 'object') applyMetric(normalizeMetric(response.metric as Record<string, unknown>, nextTick));
      else if (!response) {
        applyMetric({ ...metric, tick: nextTick, active_incidents: nodes.some((node) => node.status === 'DOWN') ? 1 : 0, healthy_app_capacity: nodes.filter((node) => node.type === 'APP_INSTANCE' && node.status !== 'DOWN').length * 125 });
        routeDemoTraffic(nextTick);
      }
      appendEvent('TRAFFIC', response ? `Advanced to tick ${String(nextTick).padStart(4, '0')}` : `Demo step advanced to tick ${String(nextTick).padStart(4, '0')}`, undefined, 'step');
    } else {
      setRunning(false);
      setTick(0);
      setMetric({ ...initialMetric, tick: 0 });
      setChart([]);
      setNodes(demoNodes);
      setLinks(demoLinks);
      setPartitioned(false);
      setLinkOverrides({});
      setTemporaryFailures({});
      setStats((current) => ({ ...current, requestsLost: 0, availability: 100 }));
      appendEvent('HEALTH', 'Simulation state reset to tick 0000', undefined, 'reset');
    }
  }

  function applyChaosLocally(eventType: ChaosAction, eventTarget: string, demoMode = false) {
    if (eventType === 'network_partition') {
      setPartitioned(true);
      appendEvent('CHAOS', 'Cross-AZ links severed · traffic isolated by zone', 'az-a ↔ az-b', eventType);
      return;
    }
    if (eventType === 'drop_link') {
      setLinkOverrides((current) => ({ ...current, [eventTarget]: 'DEGRADED' }));
      appendEvent('CHAOS', `30% packet loss injected on ${eventTarget.replace('|', ' ↔ ')}`, eventTarget.replace('|', ' ↔ '), eventType);
      return;
    }
    if (eventType === 'db_primary_failure') {
      setNodes((current) => current.map((node) => {
        if (node.id === 'db-primary-a') return { ...node, status: 'DOWN', db_role: 'REPLICA' };
        if (node.id === 'db-replica-b') return { ...node, status: 'UP', db_role: 'PRIMARY' };
        return node;
      }));
      appendEvent('FAILOVER', 'Primary DB unavailable · replica promotion initiated', 'db-primary-a', eventType);
      window.setTimeout(() => appendEvent('FAILOVER', 'db-replica-b promoted to PRIMARY · writes restored', 'db-replica-b', 'db_promotion'), 1200);
      return;
    }
    if (eventType === 'kill_az') {
      const azKey = eventTarget === 'az-b' ? 'b' : 'a';
      setNodes((current) => current.map((node) => node.az?.endsWith(azKey) ? { ...node, status: 'DOWN' } : node));
      if (demoMode) setTemporaryFailures((current) => ({ ...current, [eventTarget]: tickRef.current + duration }));
      appendEvent('CHAOS', `${eventTarget.toUpperCase()} isolated for ${duration} ticks`, eventTarget, eventType);
      appendEvent('FAILOVER', `Traffic rerouted to ${eventTarget === 'az-a' ? 'us-east-1b' : 'us-east-1a'}`, eventTarget, 'az_reroute');
      return;
    }
    if (eventType === 'recover') {
      if (eventTarget === 'az-a' || eventTarget === 'az-b') {
        const suffix = eventTarget === 'az-a' ? 'a' : 'b';
        setNodes((current) => current.map((node) => node.az?.endsWith(suffix) ? { ...node, status: 'UP' } : node));
      } else {
        setNodes((current) => current.map((node) => node.id === eventTarget ? { ...node, status: 'UP', latency_ms: Math.min(node.latency_ms, 40) } : node));
      }
      setPartitioned(false);
      setLinkOverrides({});
      setTemporaryFailures((current) => {
        const next = { ...current };
        delete next[eventTarget];
        return next;
      });
      appendEvent('CHAOS', `Manual recovery completed · ${eventTarget} restored`, eventTarget, eventType);
      return;
    }
    setNodes((current) => current.map((node) => {
      if (node.id !== eventTarget) return node;
      return eventType === 'kill_node'
        ? { ...node, status: 'DOWN' }
        : { ...node, status: 'DEGRADED', latency_ms: node.latency_ms + 100 };
    }));
    if (eventType === 'kill_node') {
      if (demoMode) setTemporaryFailures((current) => ({ ...current, [eventTarget]: tickRef.current + duration }));
      appendEvent('CHAOS', `${eventTarget} terminated for ${duration} ticks`, eventTarget, eventType);
    }
    else appendEvent('HEALTH', `+100ms processing delay injected on ${eventTarget}`, eventTarget, eventType);
  }

  async function injectChaos(eventType = action, eventTarget?: string) {
    const finalTarget = eventTarget ?? (eventType === 'kill_az' ? selectedAz : eventType === 'packet_loss' ? selectedLink : eventType === 'db_primary_failure' || eventType === 'network_partition' ? '' : target);
    const body: Record<string, unknown> = {};
    if (finalTarget) body.target = finalTarget;
    if (eventType === 'kill_node' || eventType === 'kill_az') body.duration = duration;
    if (eventType === 'latency_spike') body.magnitude = 100;
    if (eventType === 'packet_loss') body.magnitude = 0.3;
    const ws = socketRef.current;
    let backendAccepted = false;
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ action: 'inject', event_type: eventType, ...(finalTarget ? { target: finalTarget } : {}), ...(body.duration ? { duration: body.duration } : {}), ...(body.magnitude ? { magnitude: body.magnitude } : {}) }));
      setApiHealthy(true);
      backendAccepted = true;
    } else {
      try {
        await postChaos(eventType, body);
        setApiHealthy(true);
        backendAccepted = true;
      } catch {
        setApiHealthy(false);
      }
    }
    applyChaosLocally(eventType, finalTarget, !backendAccepted);
  }

  function setTickRate(value: number) {
    setSpeed(value);
    const ws = socketRef.current;
    if (running && ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ action: 'start', tick_rate_hz: value }));
    else if (running && apiHealthy) void postSimulation('/simulation/start', { tick_rate_hz: value, requests_per_tick: 10 }).catch(() => setApiHealthy(false));
  }

  function chooseAction(next: ChaosAction) {
    setAction(next);
    if (next === 'kill_az') setTarget(selectedAz);
    else if (next === 'packet_loss') setTarget(selectedLink);
    else if (next !== 'network_partition' && next !== 'db_primary_failure' && (target === 'az-a' || target === 'az-b' || target.includes('|'))) setTarget('app-a1');
  }

  const availableTargets = action === 'kill_az'
    ? ['az-a', 'az-b']
    : action === 'packet_loss'
      ? demoLinks.map((link) => `${link.source}|${link.target}`)
      : nodes.filter((node) => node.id !== 'igw-main').map((node) => node.id);
  const targetLabel = action === 'kill_az' ? 'Availability zone' : action === 'packet_loss' ? 'Network link' : 'Target node';
  const actionTitle = actionOptions.find((option) => option.id === action)?.title ?? 'Kill node';
  const selectedAction = actionOptions.find((option) => option.id === action);
  const ActionIcon = selectedAction?.icon ?? X;

  function keyForLink(source: string, destination: string) {
    return `${source}|${destination}`;
  }

  function edgeIsDown(source: string, destination: string, cross?: boolean) {
    const edge = links.find((link) => (link.source === source && link.target === destination) || (link.bidirectional && link.source === destination && link.target === source));
    return (cross && partitioned) || nodeById.get(source)?.status === 'DOWN' || nodeById.get(destination)?.status === 'DOWN' || linkOverrides[keyForLink(source, destination)] === 'DOWN' || edge?.status === 'DOWN';
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <div className="brand-mark"><Network size={18} strokeWidth={2.2} /><span className="brand-mark-core" /></div>
          <div className="brand-name">CHAOS<span>NET</span><div className="brand-caption">RESILIENCE LAB</div></div>
          <div className="brand-divider" />
          <div className="product-label"><span className="product-label-top">CLOUD NETWORK</span><span>CONTROL ROOM <span className="release-tag">BETA</span></span></div>
        </div>
        <div className="topbar-center"><span className={`connection-indicator ${connected ? 'is-connected' : 'is-disconnected'}`} /><span className="connection-state">{connected ? <Wifi size={11} /> : <WifiOff size={11} />}{connected ? ' LIVE LINK' : apiHealthy ? ' REST LINK' : ' DEMO MODE'}</span><span className="connection-separator">/</span><span className="endpoint-label">{connected ? 'WEBSOCKET SYNCHRONIZED' : apiHealthy ? 'REST API READY' : 'AWAITING BACKEND'}</span></div>
        <div className="topbar-right">
          <div className="region-chip"><Globe2 size={14} /><span>US EAST</span><span className="region-dot" /></div>
          <button className="icon-button" aria-label="Notifications"><Radio size={16} /><span className="notification-dot" /></button>
          <div className="avatar">CN</div>
        </div>
      </header>

      <main className="dashboard">
        <section className="page-intro">
          <div><div className="breadcrumb"><span>WORKSPACE</span><span className="breadcrumb-slash">/</span><span>CHAOS SIMULATOR</span><span className="breadcrumb-slash">/</span><span className="breadcrumb-current">VPC LAB 01</span></div><h1>Resilience <span>control room</span><Sparkles size={18} /></h1><p>Inject failure. Observe the cascade. Measure recovery.</p></div>
          <div className="intro-meta"><div className="simulation-id"><span className="subtle-label">SIMULATION ID</span><span className="mono">CN-7F3A-09</span></div><span className="intro-meta-divider" /><div className="uptime-badge"><ShieldCheck size={14} /><span>PROTECTED VPC</span></div></div>
        </section>

        <section className="control-deck glass-panel">
          <div className="tick-display"><div className="tick-caption"><span className="tick-live-dot" /> SIMULATION TICK</div><div className="tick-digits"><span>TICK</span><strong>{String(tick).padStart(4, '0')}</strong></div></div>
          <div className="deck-divider" />
          <div className="transport-controls" aria-label="Simulation controls">
            <button className={`transport-button play-button ${running ? 'is-active' : ''}`} aria-label="Start simulation" title="Start simulation" onClick={() => void control('start')}><Play size={15} fill="currentColor" /></button>
            <button className="transport-button" aria-label="Pause simulation" title="Pause" onClick={() => void control('pause')}><Pause size={15} fill="currentColor" /></button>
            <button className="transport-button" aria-label="Step one tick" title="Step one tick" onClick={() => void control('step')}><StepForward size={16} /></button>
            <button className="transport-button reset-button" aria-label="Reset simulation" title="Reset" onClick={() => void control('reset')}><RotateCcw size={15} /></button>
          </div>
          <div className="deck-divider deck-divider-small" />
          <div className="speed-control"><div className="speed-label"><span>TICK RATE</span><strong>{speed.toFixed(1)} <small>Hz</small></strong></div><input aria-label="Tick rate" type="range" min="0.5" max="10" step="0.5" value={speed} onChange={(event) => setTickRate(Number(event.target.value))} /><div className="range-limits"><span>0.5</span><span>10.0</span></div></div>
          <div className="deck-divider deck-divider-small" />
          <label className="strategy-control"><span className="strategy-icon"><SlidersHorizontal size={15} /></span><span className="strategy-copy"><small>ROUTING STRATEGY</small><strong>{strategy === 'ROUND_ROBIN' ? 'Round robin' : 'Least connections'}</strong></span><ChevronDown size={14} className="chevron" /><select aria-label="Routing strategy" value={strategy} onChange={(event) => setStrategy(event.target.value as Strategy)}><option value="ROUND_ROBIN">Round robin</option><option value="LEAST_CONNECTIONS">Least connections</option></select></label>
          <div className="deck-status"><span className={`deck-status-dot ${running ? 'is-running' : ''}`} /><span>{running ? 'RUNNING' : 'PAUSED'}</span></div>
        </section>

        <div className="workspace-grid">
          <aside className="left-rail glass-panel">
            <PanelHeading icon={<Bolt size={15} />} eyebrow="FAULT INJECTION" title="Chaos studio" action={<span className="live-pill"><span /> READY</span>} />
            <div className="studio-intro"><span className="studio-glyph"><Zap size={18} /></span><div><strong>Break things safely.</strong><p>Test your recovery posture.</p></div></div>
            <label className="field-label">CHAOS SCENARIO</label>
            <div className="select-wrap scenario-select"><ActionIcon size={15} /><select aria-label="Chaos scenario" value={action} onChange={(event) => chooseAction(event.target.value as ChaosAction)}>{actionOptions.map((option) => <option key={option.id} value={option.id}>{option.title}</option>)}</select><ChevronDown size={14} /></div>
            <p className="scenario-description">{selectedAction?.description}</p>
            {action !== 'network_partition' && action !== 'db_primary_failure' && <>
              <div className="field-label-row"><label className="field-label" htmlFor="chaos-target">{targetLabel.toUpperCase()}</label>{action === 'kill_az' && <span className="target-count">2 ZONES</span>}</div>
              <div className="select-wrap target-select"><TargetIcon action={action} /><select id="chaos-target" value={action === 'kill_az' ? selectedAz : action === 'packet_loss' ? selectedLink : target} onChange={(event) => { const value = event.target.value; if (action === 'kill_az') { setSelectedAz(value as 'az-a' | 'az-b'); setTarget(value); } else if (action === 'packet_loss') { setSelectedLink(value); setTarget(value); } else setTarget(value); }}>
                {availableTargets.map((option) => <option key={option} value={option}>{option.includes('|') ? option.replace('|', ' ↔ ') : option}</option>)}
              </select><ChevronDown size={14} /></div>
            </>}
            {(action === 'kill_node' || action === 'kill_az') && <div className="duration-control"><div className="field-label-row"><label className="field-label">FAILURE DURATION</label><span className="duration-value">{duration}<small> ticks</small></span></div><input aria-label="Failure duration in ticks" type="range" min="1" max="60" value={duration} onChange={(event) => setDuration(Number(event.target.value))} /><div className="range-limits"><span>1 tick</span><span>60 ticks</span></div></div>}
            {action === 'latency_spike' && <div className="effect-note"><Activity size={14} /><span>INJECTING <strong>+100 ms</strong> PROCESSING DELAY</span></div>}
            {action === 'packet_loss' && <div className="effect-note"><ArrowDownRight size={14} /><span>PACKET DROP RATE <strong>30%</strong></span></div>}
            {action === 'db_primary_failure' && <div className="effect-note effect-warning"><Database size={14} /><span>REPLICA PROMOTION WILL BE OBSERVED</span></div>}
            {action === 'network_partition' && <div className="effect-note effect-warning"><Link2 size={14} /><span>SEVER ALL CROSS-AZ ROUTES</span></div>}
            <button className="inject-button" onClick={() => void injectChaos()}><ActionIcon size={16} /><span>{action === 'recover' ? 'Restore target' : `Inject ${actionTitle.toLowerCase()}`}</span><span className="inject-shortcut">↵</span></button>
            <div className="studio-rule" />
            <div className="quick-action-title"><span>QUICK INJECT</span><span className="quick-action-hint">ONE CLICK</span></div>
            <button className="quick-action" onClick={() => void injectChaos('db_primary_failure')}><span className="quick-action-icon db-action"><Database size={14} /></span><span><strong>Crash primary DB</strong><small>Promote replica automatically</small></span><ArrowDownRight size={14} /></button>
            <button className={`quick-action ${partitioned ? 'quick-action-active' : ''}`} onClick={() => partitioned ? void injectChaos('recover', 'az-a') : void injectChaos('network_partition')}><span className="quick-action-icon net-action"><Link2 size={14} /></span><span><strong>{partitioned ? 'Restore network' : 'Network partition'}</strong><small>{partitioned ? 'Reconnect cross-AZ links' : 'Isolate availability zones'}</small></span>{partitioned ? <Check size={14} /> : <ArrowDownRight size={14} />}</button>
            <div className="chaos-footnote"><ShieldCheck size={12} /><span>ISOLATED SIMULATION ENVIRONMENT</span></div>
          </aside>

          <section className="topology-panel glass-panel">
            <div className="topology-head">
              <PanelHeading icon={<Network size={15} />} eyebrow="LIVE INFRASTRUCTURE" title="VPC topology" action={<button className="icon-button small" aria-label="Refresh topology" title="Refresh topology" onClick={() => void getTopology().then((response) => { const top = (response.topology ?? response) as Record<string, unknown>; setNodes((current) => mergeNodes(top.nodes, current)); setLinks((current) => mergeLinks(top.links, current)); setApiHealthy(true); }).catch(() => appendEvent('HEALTH', 'Topology refresh unavailable · showing simulator state'))}><RotateCcw size={14} /></button>} />
              <div className="vpc-meta"><span className="vpc-cidr">10.0.0.0/16</span><span className="vpc-meta-dot" /><span>2 AVAILABILITY ZONES</span><span className="vpc-meta-dot" /><span>{healthyApps}/4 APP NODES HEALTHY</span></div>
            </div>
            <div className="topology-legend"><span><i className="legend-dot legend-up" />UP</span><span><i className="legend-dot legend-degraded" />DEGRADED</span><span><i className="legend-dot legend-down" />DOWN</span><span className="legend-flow"><i />REQUEST FLOW</span></div>
            <div className="topology-canvas-wrap">
              <div className="topology-topline"><span><Globe2 size={12} /> INTERNET GATEWAY</span><span className="routing-chip"><span className="routing-dot" />{strategy.replace('_', ' ')}</span></div>
              <svg className="topology-canvas" viewBox="0 0 980 610" role="img" aria-label="Interactive VPC network topology showing two availability zones">
                <defs>
                  <filter id="soft-glow" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="3" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
                  <linearGradient id="flow-stroke"><stop offset="0" stopColor="#22d3ee" stopOpacity="0"/><stop offset="50%" stopColor="#4fdaef"/><stop offset="100%" stopColor="#22d3ee" stopOpacity="0"/></linearGradient>
                </defs>
                <rect className="vpc-boundary" x="14" y="106" width="952" height="489" rx="17" />
                <text className="vpc-label" x="31" y="124">VIRTUAL PRIVATE CLOUD</text>
                <text className="vpc-label vpc-label-right" x="947" y="124" textAnchor="end">REGION · US-EAST-1</text>
                <rect className="az-zone" x="26" y="136" width="458" height="441" rx="13" />
                <rect className="az-zone az-zone-b" x="496" y="136" width="458" height="441" rx="13" />
                <text className="az-title" x="43" y="155">AZ-A <tspan>us-east-1a</tspan></text>
                <text className="az-title" x="513" y="155">AZ-B <tspan>us-east-1b</tspan></text>
                <rect className="subnet-public" x="39" y="167" width="432" height="90" rx="9" />
                <rect className="subnet-public" x="509" y="167" width="432" height="90" rx="9" />
                <text className="subnet-label" x="52" y="182">PUBLIC SUBNET <tspan>10.0.1.0/24</tspan></text>
                <text className="subnet-label" x="522" y="182">PUBLIC SUBNET <tspan>10.0.2.0/24</tspan></text>
                <rect className="subnet-private" x="39" y="272" width="432" height="292" rx="9" />
                <rect className="subnet-private" x="509" y="272" width="432" height="292" rx="9" />
                <text className="subnet-label" x="52" y="289">PRIVATE SUBNET <tspan>10.0.11.0/24</tspan></text>
                <text className="subnet-label" x="522" y="289">PRIVATE SUBNET <tspan>10.0.12.0/24</tspan></text>
                {edgePaths.map((edge) => {
                  const key = keyForLink(edge.source, edge.target);
                  const isCross = 'cross' in edge && edge.cross;
                  const down = edgeIsDown(edge.source, edge.target, isCross);
                  const degraded = !down && (nodeById.get(edge.source)?.status === 'DEGRADED' || nodeById.get(edge.target)?.status === 'DEGRADED' || linkOverrides[key] === 'DEGRADED' || links.find((item) => item.source === edge.source && item.target === edge.target)?.status === 'DEGRADED');
                  return <g key={key} className={`edge-group ${down ? 'edge-down' : degraded ? 'edge-degraded' : ''} ${isCross ? 'edge-cross' : ''}`}>
                    <path d={edge.path} className="topology-edge" />
                    {edge.flow && !down && <><path d={edge.path} className="topology-edge-flow" />{(running || connected) && <circle r="2.6" className="traffic-particle"><animateMotion dur={`${2.2 + (edge.source.length % 4) * 0.35}s`} repeatCount="indefinite" path={edge.path} /></circle>}</>}
                    {down && isCross && <g className="link-break"><circle cx="490" cy="470" r="4" /><text x="490" y="473">×</text></g>}
                  </g>;
                })}
                <g className={`topology-node status-${nodeById.get('igw-main')?.status.toLowerCase() ?? 'up'} gateway-node`} transform="translate(434 30)" onClick={() => { const gateway = nodeById.get('igw-main'); if (gateway) setSelectedNode(gateway); }} role="button" tabIndex={0} aria-label="Internet gateway igw-main" onKeyDown={(event) => { if (event.key === 'Enter') { const gateway = nodeById.get('igw-main'); if (gateway) setSelectedNode(gateway); } }}>
                  <rect className="gateway-shell" width="112" height="56" rx="12" /><circle className="gateway-signal" cx="17" cy="28" r="5" /><text className="gateway-id" x="30" y="25">igw-main</text><text className="gateway-sub" x="30" y="40">INTERNET GATEWAY</text>
                </g>
                {topologyNodes.filter((layout) => layout.id !== 'igw-main').map((layout) => {
                  const node = nodeById.get(layout.id);
                  return node ? <TopologyNode key={node.id} node={node} layout={layout} selected={selected?.id === node.id} onSelect={setSelectedNode} /> : null;
                })}
                <text className="route-note" x="53" y="548">INTRA-AZ ROUTING · PRIVATE</text>
                <text className="route-note route-note-b" x="524" y="548">INTRA-AZ ROUTING · PRIVATE</text>
              </svg>
              {selected && <div className="node-detail-card">
                <button className="detail-close" onClick={() => setSelectedNode(null)} aria-label="Close node details"><X size={14} /></button>
                <div className="detail-card-title"><span className={`detail-node-icon status-${selected.status.toLowerCase()}`}>{selected.type === 'DATABASE' ? <Database size={15} /> : selected.type === 'APP_INSTANCE' ? <Cpu size={15} /> : selected.type === 'ROUTER' ? <Network size={15} /> : <Cloud size={15} />}</span><div><strong>{selected.id}</strong><span>{selected.type.replace(/_/g, ' ')}</span></div><span className={`node-status-chip status-${selected.status.toLowerCase()}`}><StatusDot status={selected.status} />{nodeStatusLabel[selected.status]}</span></div>
                <div className="detail-stats"><div><span>LATENCY</span><strong>{selected.latency_ms}<small>ms</small></strong></div><div><span>CAPACITY</span><strong>{formatNumber(selected.capacity)}</strong></div><div><span>CONNECTIONS</span><strong>{formatNumber(selected.active_connections)}</strong></div></div>
                <div className="detail-actions"><button onClick={() => void injectChaos('kill_node', selected.id)}><X size={13} />Kill node</button><button onClick={() => void injectChaos('latency_spike', selected.id)}><Activity size={13} />Spike latency</button></div>
              </div>}
            </div>
            <div className="topology-footer"><span><Layers3 size={13} />VPC PEERING ACTIVE</span><span className="topology-footer-sep" /><span><CircleDot size={11} />{nodes.filter((node) => node.status === 'UP').length} NODES ONLINE</span><span className="topology-footer-sep" /><span className="latency-footer"><Activity size={12} />CROSS-AZ RTT <strong>18 ms</strong></span></div>
          </section>

          <aside className="right-rail glass-panel">
            <PanelHeading icon={<Gauge size={15} />} eyebrow="SYSTEM TELEMETRY" title="Health overview" action={<button className="refresh-metrics" aria-label="Refresh metrics" title="Refresh metrics" onClick={() => void getMetrics().then((response) => { const next = normalizeMetric(response, tick); setMetric(next); setTick(next.tick); setApiHealthy(true); }).catch(() => undefined)}><RotateCcw size={13} /></button>} />
            <div className="availability-card">
              <div className="gauge-wrap"><svg viewBox="0 0 110 110" className="availability-gauge"><circle className="gauge-track" cx="55" cy="55" r="45" /><circle className="gauge-value" cx="55" cy="55" r="45" style={{ strokeDasharray: `${(availability / 100) * 282.7} 282.7` }} /><circle className="gauge-center-dot" cx="55" cy="10" r="2.3" /></svg><div className="gauge-copy"><strong>{availability.toFixed(2)}<span>%</span></strong><small>AVAILABILITY</small></div></div>
              <div className="availability-meta"><span className="availability-pulse" /><strong>Within SLO</strong><small>30-day objective <b>99.95%</b></small><div className="slo-line"><span style={{ width: `${Math.min(100, availability)}%` }} /></div></div>
            </div>
            <div className="telemetry-divider" />
            <div className="stat-pair-grid">
              <div className="stat-tile"><div className="stat-tile-head"><span>MEAN TIME TO RECOVER</span><Clock3 size={13} /></div><strong>{stats.mttr.toFixed(1)} <small>ticks</small></strong><span className="stat-trend trend-good"><ArrowDownRight size={12} /> −0.4 <i>vs. avg</i></span></div>
              <div className="stat-tile"><div className="stat-tile-head"><span>DETECTION LAG</span><Radio size={13} /></div><strong>{stats.detection.toFixed(1)} <small>ticks</small></strong><span className="stat-trend"><span className="trend-dot" /> HEALTH CHECKS</span></div>
              <div className="stat-tile stat-lost"><div className="stat-tile-head"><span>REQUESTS LOST</span><ArrowDownRight size={13} /></div><strong>{formatNumber(stats.requestsLost)}</strong><span className="stat-trend"><span className="trend-dot trend-amber" /> DURING FAILOVER</span></div>
              <div className="stat-tile"><div className="stat-tile-head"><span>ACTIVE INCIDENTS</span><AlertTriangle size={13} /></div><strong>{metric.active_incidents.toString().padStart(2, '0')}</strong><span className="stat-trend trend-good"><span className="trend-dot" /> MITIGATED</span></div>
            </div>
            <div className="capacity-panel"><div className="capacity-heading"><div><span>HEALTHY APP CAPACITY</span><strong>{formatNumber(appCapacity)}<small> / {formatNumber(stats.totalCapacity)} units</small></strong></div><span className="capacity-pct"><ArrowUpRight size={11} />{capacityPct.toFixed(0)}%</span></div><div className="capacity-track"><span style={{ width: `${capacityPct}%` }} /></div><div className="capacity-labels"><span>{healthyApps} healthy instances</span><span>4 total</span></div></div>
            <div className="latency-panel"><div className="latency-head"><span>LATENCY OVER TIME</span><span className="chart-legend"><i />AVG <i className="p95-legend" />P95</span></div><div className="latency-current"><div><small>AVG</small><strong>{metric.avg_latency_ms.toFixed(1)}<i>ms</i></strong></div><div><small>P95</small><strong>{metric.p95_latency_ms.toFixed(1)}<i>ms</i></strong></div><span className="chart-tick">T-{chart.length}</span></div><Sparkline points={chart.length ? chart : seedChart.slice(0, 1)} /><div className="chart-axis"><span>TICK {String(chart[0]?.tick ?? 27).padStart(4, '0')}</span><span>LIVE <i /></span></div></div>
            <div className="right-rail-footer"><span>{connected ? <Wifi size={12} /> : <WifiOff size={12} />}METRICS STREAM</span><span>{connected ? 'LIVE' : apiHealthy ? 'POLLING' : 'DEMO'}</span></div>
          </aside>

          <section className="event-terminal glass-panel">
            <div className="terminal-head">
              <PanelHeading icon={<Terminal size={15} />} eyebrow="LIVE AUDIT STREAM" title="Event terminal" action={<span className="terminal-event-count"><span className="terminal-pulse" />{visibleEvents.length} EVENTS</span>} />
              <div className="terminal-tools">
                <div className="event-filters">{['ALL', 'CHAOS', 'HEALTH', 'FAILOVER', 'TRAFFIC'].map((category) => <button key={category} className={filter === category ? 'filter-active' : ''} onClick={() => setFilter(category)}>{category}</button>)}</div>
                <label className="event-search"><Search size={13} /><input placeholder="Filter events..." value={search} onChange={(event) => setSearch(event.target.value)} aria-label="Search events" />{search && <button onClick={() => setSearch('')} aria-label="Clear search"><X size={12} /></button>}</label>
              </div>
            </div>
            <div className="terminal-columns"><span>TIME</span><span>TICK</span><span>SUBSYSTEM</span><span>EVENT DETAIL</span><span>TARGET</span><span>STATE</span></div>
            <div className="terminal-body" ref={terminalRef}>
              {visibleEvents.length ? visibleEvents.map((event, index) => <div className={`event-row ${index === 0 ? 'event-row-new' : ''}`} key={event.id}><span className="event-time">{timeLabel(event.timestamp)}</span><span className="event-tick">{String(event.tick).padStart(4, '0')}</span><span><span className={`event-category category-${event.category.toLowerCase()}`}>{event.category}</span></span><span className="event-description">{event.description}</span><span className="event-target">{event.target ?? '—'}</span><span className="event-state"><span className={`event-state-dot ${event.category === 'CHAOS' ? 'state-purple' : event.category === 'HEALTH' ? 'state-amber' : event.category === 'FAILOVER' ? 'state-cyan' : 'state-green'}`} />{event.category === 'CHAOS' ? 'INJECTED' : event.category === 'HEALTH' ? 'OBSERVED' : event.category === 'FAILOVER' ? 'ROUTED' : 'PROCESSED'}</span></div>) : <div className="terminal-empty">No events match this filter. Waiting for the next signal…</div>}
            </div>
            <div className="terminal-footer"><span><span className="terminal-pulse" />STREAMING IN REAL TIME</span><span>{API_BASE.replace('http://', '')}/ws<span className="footer-slash"> · </span><span className={connected ? 'text-green' : 'text-muted'}>{connected ? 'CONNECTED' : 'RECONNECTING'}</span></span><button onClick={() => setEvents([])} title="Clear event log">CLEAR LOG <X size={11} /></button></div>
          </section>
        </div>
        <footer className="page-footer"><span><span className="footer-logo"><Network size={12} /></span>CHAOSNET <span>RESILIENCE LAB</span></span><span>VPC <b>10.0.0.0/16</b> <i /> REGION <b>US-EAST-1</b></span><span>SIMULATOR BUILD <b>0.9.4</b> <i /> API <b>{API_BASE.replace('http://', '')}</b></span></footer>
      </main>
    </div>
  );
}

function TargetIcon({ action }: { action: ChaosAction }) {
  if (action === 'kill_az') return <Globe2 size={14} />;
  if (action === 'packet_loss') return <Link2 size={14} />;
  return <Server size={14} />;
}

function number(value: unknown, fallback: number) {
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}
