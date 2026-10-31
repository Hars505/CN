import { useEffect, useRef, useState } from 'react';
import {
  getMetrics,
  getTopology,
  mergeNodes,
  normalizeEvents,
  normalizeMetric,
  postChaos,
  postSimulation,
  WS_URL,
} from '../api';
import { demoNodes, type Category, type CloudNode, type TickMetric } from '../types';
import {
  guidedSteps,
  isRecoveredWithoutSplitBrain,
  isZoneADegraded,
  localMetricAt,
  localNodesAt,
  localSummaryAt,
  type DemoSummary,
} from './demoModel';

export type DemoSource = 'checking' | 'live' | 'local';

export interface DemoLogEntry {
  id: string;
  tick: number;
  category: Category;
  eventType: string;
  target: string;
  change: string;
  description: string;
}

const defaultSummary: DemoSummary = { availability: 100, detectionLag: 0, requestsLost: 0, healthyZones: 2 };
const defaultMetric: TickMetric = localMetricAt(0);

function numberValue(value: unknown, fallback: number): number {
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? value as Record<string, unknown> : {};
}

export function useGuidedDemo() {
  const [nodes, setNodes] = useState<CloudNode[]>(demoNodes);
  const [metric, setMetric] = useState<TickMetric>(defaultMetric);
  const [summary, setSummary] = useState<DemoSummary>(defaultSummary);
  const [feed, setFeed] = useState<DemoLogEntry[]>([]);
  const [phase, setPhase] = useState(0);
  const [source, setSource] = useState<DemoSource>('checking');
  const [socketConnected, setSocketConnected] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [technicalOpen, setTechnicalOpen] = useState(false);
  const [notice, setNotice] = useState('Checking the ChaosNet simulator connection…');

  const nodesRef = useRef(nodes);
  const metricRef = useRef(metric);
  const sourceRef = useRef(source);
  const socketRef = useRef<WebSocket | null>(null);
  const runToken = useRef(0);
  const pausedRef = useRef(false);
  const mountedRef = useRef(true);
  const healthCheckEvidenceRef = useRef(false);
  const rerouteEvidenceRef = useRef(false);
  nodesRef.current = nodes;
  metricRef.current = metric;
  sourceRef.current = source;

  function pushLog(category: Category, eventType: string, target: string, description: string, change = '—', tick = metricRef.current.tick) {
    const row: DemoLogEntry = {
      id: `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
      tick,
      category,
      eventType,
      target,
      description,
      change,
    };
    setFeed((current) => [row, ...current].slice(0, 12));
  }

  async function simulationControl(action: 'reset' | 'start' | 'pause', body: Record<string, unknown> = {}) {
    const socket = socketRef.current;
    if (socket?.readyState === WebSocket.OPEN) {
      const message = action === 'start' ? { action, tick_rate_hz: numberValue(body.tick_rate_hz, 2) } : { action };
      try {
        socket.send(JSON.stringify(message));
        return;
      } catch {
        // Fall back to REST if the socket closes during a send.
      }
    }
    await postSimulation(`/simulation/${action}`, body);
  }

  async function injectControl(eventType: string, body: Record<string, unknown>) {
    const socket = socketRef.current;
    if (socket?.readyState === WebSocket.OPEN) {
      try {
        socket.send(JSON.stringify({ action: 'inject', event_type: eventType, ...body }));
        return;
      } catch {
        // Fall back to REST if the socket closes during a send.
      }
    }
    await postChaos(eventType, body);
  }

  async function syncBackend() {
    const [topologyResponse, metricResponse] = await Promise.all([getTopology(), getMetrics()]);
    const topology = recordValue(topologyResponse.topology ?? topologyResponse);
    const nodeRows = topology.nodes;
    const hasNodes = Array.isArray(nodeRows) ? nodeRows.length > 0 : Boolean(nodeRows && typeof nodeRows === 'object' && Object.keys(nodeRows).length > 0);
    if (!hasNodes || Object.keys(metricResponse).length === 0) throw new Error('Backend did not return a complete topology and metric snapshot.');
    const nextNodes = mergeNodes(topology.nodes, nodesRef.current);
    const nextMetric = normalizeMetric(metricResponse, numberValue(metricResponse.total_ticks, metricRef.current.tick));
    const nextSummary: DemoSummary = {
      availability: numberValue(metricResponse.availability_pct ?? recordValue(topology.summary).availability_pct, nextMetric.success_rate_pct),
      detectionLag: numberValue(metricResponse.mean_detection_time_ticks ?? metricResponse.detection_lag_ticks, summary.detectionLag),
      requestsLost: numberValue(metricResponse.requests_lost ?? metricResponse.requests_lost_during_failover, summary.requestsLost),
      healthyZones: nextNodes.some((node) => node.az?.endsWith('a') && node.status !== 'DOWN') && nextNodes.some((node) => node.az?.endsWith('b') && node.status !== 'DOWN') ? 2 : 1,
    };
    if (mountedRef.current) {
      setNodes(nextNodes);
      nodesRef.current = nextNodes;
      setMetric(nextMetric);
      metricRef.current = nextMetric;
      setSummary(nextSummary);
      setSource('live');
      sourceRef.current = 'live';
    }
    return { nodes: nextNodes, metric: nextMetric, summary: nextSummary };
  }

  function absorbWebSocketMessage(raw: unknown) {
    const message = recordValue(raw);
    const messageType = String(message.type ?? '').toUpperCase();
    const rawTopology = recordValue(message.topology);
    const summaryTopology = recordValue(message.topology_summary);
    const topology = rawTopology.nodes ? rawTopology : summaryTopology;
    const hasNodes = Array.isArray(topology.nodes) ? topology.nodes.length > 0 : Boolean(topology.nodes && typeof topology.nodes === 'object' && Object.keys(topology.nodes).length > 0);
    if (hasNodes) {
      setNodes((current) => {
        const next = mergeNodes(topology.nodes, current);
        nodesRef.current = next;
        return next;
      });
      if (messageType === 'INITIAL_STATE' || messageType === 'TICK_UPDATE') {
        setSource('live');
        sourceRef.current = 'live';
      }
    }
    const incomingMetric = recordValue(message.metric);
    if (Object.keys(incomingMetric).length) {
      const nextMetric = normalizeMetric(incomingMetric, numberValue(message.tick, metricRef.current.tick));
      setMetric(nextMetric);
      metricRef.current = nextMetric;
      setSummary((current) => ({
        ...current,
        availability: numberValue(recordValue(message.topology_summary).availability_pct, nextMetric.success_rate_pct),
        healthyZones: nodesRef.current.some((node) => node.az?.endsWith('a') && node.status !== 'DOWN') && nodesRef.current.some((node) => node.az?.endsWith('b') && node.status !== 'DOWN') ? 2 : 1,
      }));
    }
    const liveSummary = recordValue(message.summary ?? message.topology_summary);
    if (Object.keys(liveSummary).length) {
      setSummary((current) => ({
        ...current,
        availability: numberValue(liveSummary.availability_pct ?? liveSummary.availability, current.availability),
        detectionLag: numberValue(liveSummary.mean_detection_time_ticks ?? liveSummary.detection_lag, current.detectionLag),
      }));
    }
    const events = Array.isArray(message.events)
      ? message.events
      : message.event
        ? [message.event]
        : messageType === 'EVENT'
          ? [message]
          : [];
    const normalized = normalizeEvents(events, numberValue(message.tick, metricRef.current.tick));
    normalized.forEach((event) => {
      const evidence = `${event.event_type} ${event.target ?? ''} ${event.description}`;
      if ((event.category === 'HEALTH' && /health.?check/i.test(evidence) && /fail|down|unhealthy|detect/i.test(evidence)) || /failure[_\s-]?detect/i.test(event.event_type)) {
        healthCheckEvidenceRef.current = true;
      }
      if (/rerout/i.test(evidence) && /az-b|zone\s*b|us-east-1b/i.test(evidence)) rerouteEvidenceRef.current = true;
      pushLog(event.category, event.event_type, event.target ?? 'VPC', event.description, 'WebSocket event', event.tick);
    });
  }

  useEffect(() => {
    mountedRef.current = true;
    let socket: WebSocket | null = null;
    let alive = true;
    let reconnectTimer: number | undefined;

    const connect = () => {
      try {
        const nextSocket = new WebSocket(WS_URL);
        socket = nextSocket;
        socketRef.current = nextSocket;
        nextSocket.onopen = () => {
          if (alive) setSocketConnected(true);
        };
        nextSocket.onmessage = (event) => {
          try {
            absorbWebSocketMessage(JSON.parse(event.data));
          } catch {
            pushLog('HEALTH', 'protocol_warning', 'WebSocket', 'Received an unreadable live message.');
          }
        };
        nextSocket.onclose = () => {
          if (!alive) return;
          setSocketConnected(false);
          if (socketRef.current === nextSocket) socketRef.current = null;
          reconnectTimer = window.setTimeout(connect, 2500);
        };
        nextSocket.onerror = () => nextSocket.close();
      } catch {
        setSocketConnected(false);
        reconnectTimer = window.setTimeout(connect, 2500);
      }
    };
    connect();

    void syncBackend().catch(() => {
      if (alive && sourceRef.current !== 'live') {
        setSource('local');
        sourceRef.current = 'local';
        setNotice('Backend unavailable here. A deterministic local demo is ready.');
      }
    });

    return () => {
      alive = false;
      mountedRef.current = false;
      runToken.current += 1;
      window.clearTimeout(reconnectTimer);
      socketRef.current = null;
      socket?.close();
    };
    // One live connection is maintained for the lifetime of this route.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function pauseAwareDelay(milliseconds: number, token: number): Promise<boolean> {
    let elapsed = 0;
    while (elapsed < milliseconds && token === runToken.current) {
      await new Promise((resolve) => window.setTimeout(resolve, 80));
      if (!pausedRef.current) elapsed += 80;
    }
    return token === runToken.current;
  }

  async function waitForLiveState(token: number, condition: (items: CloudNode[]) => boolean, attempts = 5): Promise<boolean> {
    for (let attempt = 0; attempt < attempts && token === runToken.current; attempt += 1) {
      if (condition(nodesRef.current)) return true;
      if (!(await pauseAwareDelay(600, token))) return false;
      try {
        const latest = await syncBackend();
        if (condition(latest.nodes)) return true;
      } catch {
        // WebSocket data may still arrive even if REST polling is temporarily unavailable.
      }
    }
    return condition(nodesRef.current);
  }

  async function runLocalDemo(token: number) {
    setSource('local');
    sourceRef.current = 'local';
    setNotice('Deterministic local demo · illustrative metrics, not backend measurements.');
    setNodes(localNodesAt(0));
    setMetric(localMetricAt(0));
    setSummary(localSummaryAt(0));
    for (let nextStep = 1; nextStep < guidedSteps.length; nextStep += 1) {
      if (!(await pauseAwareDelay(1050, token))) return;
      const nextMetric = localMetricAt(nextStep);
      const previousMetric = metricRef.current;
      const nextNodes = localNodesAt(nextStep);
      setPhase(nextStep);
      setNodes(nextNodes);
      nodesRef.current = nextNodes;
      setMetric(nextMetric);
      metricRef.current = nextMetric;
      setSummary(localSummaryAt(nextStep));
      setNotice(guidedSteps[nextStep].detail);
      const change = `availability ${localSummaryAt(nextStep - 1).availability.toFixed(2)}% → ${localSummaryAt(nextStep).availability.toFixed(2)}%; P95 ${previousMetric.p95_latency_ms.toFixed(1)} → ${nextMetric.p95_latency_ms.toFixed(1)} ms`;
      const category: Category = nextStep === 1 || nextStep === 5 ? 'CHAOS' : nextStep === 4 ? 'FAILOVER' : nextStep === 3 ? 'TRAFFIC' : 'HEALTH';
      const target = nextStep === 1 || nextStep === 2 || nextStep === 5 ? 'az-a' : nextStep === 4 ? 'db-replica-b' : 'VPC';
      pushLog(category, guidedSteps[nextStep].id, target, guidedSteps[nextStep].headline, change, nextMetric.tick);
    }
    if (token === runToken.current) setIsRunning(false);
  }

  async function runLiveDemo(token: number): Promise<boolean> {
    try {
      await simulationControl('reset');
      await simulationControl('start', { tick_rate_hz: 2, requests_per_tick: 10 });
    } catch {
      return false;
    }
    await syncBackend().catch(() => undefined);

    setSource('live');
    sourceRef.current = 'live';
    setNotice('Live simulator started. Preparing the controlled zone failure…');
    pushLog('HEALTH', 'simulation_start', 'VPC', 'Live ChaosNet simulation started.', 'tick rate 2.0/sec');
    if (!(await pauseAwareDelay(450, token))) return true;

    try {
      await injectControl('kill_az', { target: 'az-a', duration: 60 });
      if (token !== runToken.current) return true;
      setPhase(1);
      setNotice('Zone A failure injected. Waiting for live topology confirmation…');
      pushLog('CHAOS', 'kill_az', 'az-a', 'Zone A failure requested.', 'duration 60 ticks');

      const zoneConfirmed = await waitForLiveState(token, isZoneADegraded, 5);
      if (token !== runToken.current) return true;
      if (zoneConfirmed) {
        setPhase(1);
        setNotice('Zone A is offline.');
        if (!(await pauseAwareDelay(500, token))) return true;
      }
      setPhase(2);
      const detectionConfirmed = zoneConfirmed && healthCheckEvidenceRef.current;
      setNotice(detectionConfirmed ? 'Health checks confirm the failure.' : zoneConfirmed ? 'Zone A is offline; waiting for health-check confirmation.' : 'The failure was sent; waiting for health-check/topology confirmation.');
      pushLog('HEALTH', detectionConfirmed ? 'failure_detected' : 'detection_pending', 'az-a', detectionConfirmed ? 'Health-check failure event observed.' : 'A health-check failure event has not been observed yet.', detectionConfirmed ? 'health-check event received' : 'awaiting backend event');

      if (!(await pauseAwareDelay(700, token))) return true;
      const rerouteObserved = zoneConfirmed && rerouteEvidenceRef.current;
      setPhase(3);
      setNotice(rerouteObserved ? 'Traffic is moving through Zone B.' : 'Traffic reroute requested; waiting for live telemetry.');
      pushLog('TRAFFIC', rerouteObserved ? 'az_reroute' : 'reroute_pending', 'az-b', rerouteObserved ? 'The surviving zone remains available for successful requests.' : 'The latest backend state does not yet confirm the reroute.', rerouteObserved ? `${metricRef.current.requests_succeeded} requests succeeded` : 'awaiting backend state');

      const promoted = await waitForLiveState(token, (items) => items.some((node) => node.id === 'db-replica-b' && node.db_role === 'PRIMARY'), 4);
      if (token !== runToken.current) return true;
      setPhase(4);
      setNotice(promoted ? 'Replica promoted to primary.' : 'Replica promotion is not yet reported by the live topology.');
      pushLog('FAILOVER', promoted ? 'db_promotion' : 'promotion_pending', 'db-replica-b', promoted ? 'Replica primary role confirmed by live topology.' : 'Waiting for live replica-role confirmation.', promoted ? 'role REPLICA → PRIMARY' : 'awaiting backend state');

      if (!(await pauseAwareDelay(700, token))) return true;
      await injectControl('recover', { target: 'az-a' });
      if (token !== runToken.current) return true;
      setPhase(5);
      setNotice('Recovery requested. Checking that Zone A rejoins with one database primary…');
      pushLog('CHAOS', 'recover', 'az-a', 'Manual recovery requested for Zone A.', 'checking AZ health and database roles');
      const recovered = promoted && await waitForLiveState(token, isRecoveredWithoutSplitBrain, 5);
      if (token !== runToken.current) return true;
      setPhase(6);
      setNotice(recovered ? 'Service recovered. Live topology reports exactly one primary.' : 'Recovery is still converging; the values below show the latest live measurements.');
      const latest = await syncBackend().catch(() => null);
      if (latest) {
        setSummary((current) => ({ ...current, ...latest.summary }));
        setMetric(latest.metric);
      }
      pushLog('HEALTH', recovered ? 'recovery_verified' : 'recovery_pending', 'VPC', recovered ? 'Recovery confirmed without split-brain.' : 'Final recovery state was not confirmed before the demo ended.', recovered ? 'one PRIMARY database' : 'latest API snapshot shown');
      await simulationControl('pause').catch(() => undefined);
      if (token === runToken.current) setIsRunning(false);
      return true;
    } catch (error) {
      const detail = error instanceof Error ? error.message : 'Backend request failed.';
      setNotice(`The live sequence stopped: ${detail} Open the full simulator to inspect or recover the environment.`);
      pushLog('HEALTH', 'sequence_stopped', 'VPC', detail, 'live backend request failed');
      await simulationControl('pause').catch(() => undefined);
      if (token === runToken.current) setIsRunning(false);
      return true;
    }
  }

  async function runDemo() {
    const token = ++runToken.current;
    pausedRef.current = false;
    setIsPaused(false);
    setIsRunning(true);
    setPhase(0);
    setFeed([]);
    healthCheckEvidenceRef.current = false;
    rerouteEvidenceRef.current = false;
    setNotice('Starting from a healthy two-zone baseline…');
    setNodes(demoNodes);
    nodesRef.current = demoNodes;
    setMetric(defaultMetric);
    metricRef.current = defaultMetric;
    setSummary(defaultSummary);

    let liveReady = sourceRef.current === 'live';
    if (!liveReady && sourceRef.current === 'checking') {
      try {
        await syncBackend();
        liveReady = true;
      } catch {
        liveReady = false;
      }
    }
    if (token !== runToken.current) return;
    if (liveReady) {
      const handled = await runLiveDemo(token);
      if (!handled && token === runToken.current) {
        await runLocalDemo(token);
      }
    } else {
      await runLocalDemo(token);
    }
  }

  async function togglePause() {
    if (!isRunning) return;
    const nextPaused = !pausedRef.current;
    pausedRef.current = nextPaused;
    setIsPaused(nextPaused);
    if (sourceRef.current === 'live') {
      const action = nextPaused ? 'pause' : 'start';
      const body = nextPaused ? {} : { tick_rate_hz: 2, requests_per_tick: 10 };
      await simulationControl(action, body).catch(() => setNotice('The live pause/resume request could not be confirmed.'));
    }
  }

  return {
    nodes,
    metric,
    summary,
    feed,
    phase,
    source,
    socketConnected,
    isRunning,
    isPaused,
    technicalOpen,
    setTechnicalOpen,
    notice,
    currentStep: guidedSteps[phase],
    runDemo,
    togglePause,
  };
}
