import { useEffect, useMemo, useState } from 'react';
import { X } from 'lucide-react';
import type { CloudNode } from '../types';

interface TopologySceneProps {
  nodes: CloudNode[];
  trafficActive: boolean;
}

const placements = [
  { id: 'igw-main', label: 'Internet gateway', x: 334, y: 26, width: 92, height: 42 },
  { id: 'lb-a', label: 'Load balancer', x: 90, y: 131, width: 98, height: 48 },
  { id: 'nat-a', label: 'NAT gateway', x: 230, y: 137, width: 90, height: 48 },
  { id: 'lb-b', label: 'Load balancer', x: 572, y: 131, width: 98, height: 48 },
  { id: 'nat-b', label: 'NAT gateway', x: 620, y: 137, width: 90, height: 48 },
  { id: 'router-a', label: 'VPC router', x: 90, y: 213, width: 98, height: 48 },
  { id: 'router-b', label: 'VPC router', x: 572, y: 213, width: 98, height: 48 },
  { id: 'app-a1', label: 'App instance', x: 44, y: 293, width: 98, height: 48 },
  { id: 'app-a2', label: 'App instance', x: 154, y: 293, width: 98, height: 48 },
  { id: 'app-b1', label: 'App instance', x: 528, y: 293, width: 98, height: 48 },
  { id: 'app-b2', label: 'App instance', x: 638, y: 293, width: 98, height: 48 },
  { id: 'db-primary-a', label: 'Database', x: 92, y: 380, width: 126, height: 48 },
  { id: 'db-replica-b', label: 'Database', x: 542, y: 380, width: 126, height: 48 },
] as const;

const edges = [
  { source: 'igw-main', target: 'lb-a', d: 'M380 68 C335 97 217 102 139 131', crossZone: false },
  { source: 'igw-main', target: 'lb-b', d: 'M380 68 C425 97 543 102 621 131', crossZone: false },
  { source: 'lb-a', target: 'router-a', d: 'M139 179 L139 213', crossZone: false },
  { source: 'lb-b', target: 'router-b', d: 'M621 179 L621 213', crossZone: false },
  { source: 'nat-a', target: 'router-a', d: 'M275 185 C257 207 218 220 188 237', crossZone: false },
  { source: 'nat-b', target: 'router-b', d: 'M665 185 C647 207 602 220 572 237', crossZone: false },
  { source: 'router-a', target: 'app-a1', d: 'M139 261 C125 275 98 281 93 293', crossZone: false },
  { source: 'router-a', target: 'app-a2', d: 'M139 261 C151 275 183 281 203 293', crossZone: false },
  { source: 'router-b', target: 'app-b1', d: 'M621 261 C606 275 569 281 577 293', crossZone: false },
  { source: 'router-b', target: 'app-b2', d: 'M621 261 C636 275 675 281 687 293', crossZone: false },
  { source: 'app-a1', target: 'db-primary-a', d: 'M93 341 C104 356 131 365 155 380', crossZone: false },
  { source: 'app-b1', target: 'db-replica-b', d: 'M577 341 C588 356 615 365 605 380', crossZone: false },
  { source: 'router-a', target: 'router-b', d: 'M188 237 C310 195 450 195 572 237', crossZone: true },
  { source: 'db-primary-a', target: 'db-replica-b', d: 'M218 403 C315 446 445 446 542 403', crossZone: true },
] as const;

function nodeGlyph(type: CloudNode['type']) {
  if (type === 'DATABASE') return 'DB';
  if (type === 'APP_INSTANCE') return 'APP';
  if (type === 'LOAD_BALANCER') return 'LB';
  if (type === 'ROUTER') return 'RTR';
  if (type === 'INTERNET_GATEWAY') return 'IGW';
  return 'NAT';
}

export default function TopologyScene({ nodes, trafficActive }: TopologySceneProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [reducedMotion, setReducedMotion] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const nodeMap = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  const selectedNode = selectedId ? nodeMap.get(selectedId) : undefined;

  useEffect(() => {
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
    const updatePreference = () => setReducedMotion(preference.matches);
    preference.addEventListener('change', updatePreference);
    return () => preference.removeEventListener('change', updatePreference);
  }, []);

  return (
    <div className="scene-shell">
      <div className="scene-region-label"><span>VPC · 10.0.0.0/16</span><span>US EAST · 2 AVAILABILITY ZONES</span></div>
      <svg className="scene-svg" viewBox="0 0 760 462" role="img" aria-label="Interactive ChaosNet topology across two availability zones">
        <defs><filter id="scene-glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2.5" result="blur" /><feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge></filter></defs>
        <rect className="scene-zone scene-zone-a" x="22" y="93" width="330" height="352" rx="14" />
        <rect className="scene-zone scene-zone-b" x="408" y="93" width="330" height="352" rx="14" />
        <text className="scene-zone-name" x="42" y="116">ZONE A <tspan>us-east-1a</tspan></text>
        <text className="scene-zone-name" x="428" y="116">ZONE B <tspan>us-east-1b</tspan></text>
        <rect className="scene-subnet scene-subnet-public" x="38" y="128" width="298" height="66" rx="8" />
        <rect className="scene-subnet" x="38" y="204" width="298" height="226" rx="8" />
        <rect className="scene-subnet scene-subnet-public" x="424" y="128" width="298" height="66" rx="8" />
        <rect className="scene-subnet" x="424" y="204" width="298" height="226" rx="8" />
        <text className="scene-subnet-label" x="50" y="143">PUBLIC SUBNET</text>
        <text className="scene-subnet-label" x="50" y="219">PRIVATE SUBNET</text>
        <text className="scene-subnet-label" x="436" y="143">PUBLIC SUBNET</text>
        <text className="scene-subnet-label" x="436" y="219">PRIVATE SUBNET</text>
        {edges.map((edge) => {
          const source = nodeMap.get(edge.source);
          const destination = nodeMap.get(edge.target);
          const down = source?.status === 'DOWN' || destination?.status === 'DOWN';
          return <g key={`${edge.source}-${edge.target}`} className={`scene-edge ${down ? 'is-down' : ''} ${edge.crossZone ? 'is-cross-zone' : ''}`}>
            <path d={edge.d} />
            {!down && trafficActive && !reducedMotion && <circle r="2.7" className="scene-particle"><animateMotion dur={`${2.2 + (edge.source.length % 3) * 0.4}s`} repeatCount="indefinite" path={edge.d} /></circle>}
          </g>;
        })}
        {placements.map((placement) => {
          const node = nodeMap.get(placement.id);
          if (!node) return null;
          const status = node.status.toLowerCase();
          return <g key={node.id} className={`scene-node status-${status}`} transform={`translate(${placement.x} ${placement.y})`} onClick={() => setSelectedId(node.id)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelectedId(node.id); } }} role="button" tabIndex={0} aria-label={`${node.id}: ${node.status}`}>
            <title>{`${node.id} · ${node.status} · ${node.latency_ms} ms`}</title>
            <rect className="scene-node-shell" width={placement.width} height={placement.height} rx="9" />
            <circle className="scene-node-led" cx="11" cy="13" r="3" />
            <text className="scene-node-kind" x="20" y="16">{nodeGlyph(node.type)}</text>
            <text className="scene-node-id" x="10" y="34">{node.id}</text>
            {node.type === 'DATABASE' && node.db_role && <g className={`scene-db-role ${node.db_role === 'PRIMARY' ? 'is-primary' : 'is-replica'}`} transform={`translate(${placement.width - 37} 4)`}><rect width="32" height="14" rx="4"/><text x="16" y="10" textAnchor="middle">{node.db_role === 'PRIMARY' ? '♛ PRI' : '◈ RPL'}</text></g>}
          </g>;
        })}
        <text className="scene-outside-label" x="380" y="20" textAnchor="middle">INTERNET GATEWAY</text>
      </svg>
      {selectedNode && <div className="scene-node-popover" role="status"><span className={`scene-status-dot status-${selectedNode.status.toLowerCase()}`} />
        <div><strong>{selectedNode.id}</strong><span>{selectedNode.status} · {selectedNode.latency_ms} ms · {selectedNode.active_connections} connections</span></div>
        <button type="button" onClick={() => setSelectedId(null)} aria-label="Close node details"><X size={14} /></button>
      </div>}
      <div className="scene-legend"><span><i className="legend-healthy" />Healthy</span><span><i className="legend-degraded" />Detected</span><span><i className="legend-failed" />Failed</span><span className="legend-flow"><i />Request flow</span></div>
    </div>
  );
}
