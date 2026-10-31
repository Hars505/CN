import { useState } from 'react';
import { ArrowRight, ChevronDown, Circle, Pause, Play, RotateCcw, Signal, Wifi, WifiOff } from 'lucide-react';
import type { useGuidedDemo } from './useGuidedDemo';
import TopologyScene from './TopologyScene';

type DemoController = ReturnType<typeof useGuidedDemo>;

function formatMetric(value: number, digits = 1) {
  return Number.isFinite(value) ? value.toFixed(digits) : '—';
}

export default function GuidedFailureDemo({ demo }: { demo: DemoController }) {
  const [showDetails, setShowDetails] = useState(false);
  const sourceLabel = demo.source === 'live'
    ? demo.socketConnected ? 'LIVE API · WS' : 'LIVE API · REST'
    : demo.source === 'checking' ? 'CHECKING BACKEND' : 'DETERMINISTIC LOCAL DEMO';
  const isWaitingForConfirmation = demo.source === 'live' && /waiting|awaiting|not yet|pending|checking/i.test(demo.notice);
  const headline = isWaitingForConfirmation ? demo.notice : demo.currentStep.headline;

  return (
    <section className="guided-demo" id="run-demo" aria-labelledby="demo-title">
      <div className="demo-card-topline">
        <div className="demo-live-label"><span className={`demo-source-light source-${demo.source}`} />
          <span>{sourceLabel}</span>
        </div>
        <span className="demo-tick"><span>TICK</span><b>{String(demo.metric.tick).padStart(4, '0')}</b></span>
      </div>
      <div className="demo-card-title">
        <div><p className="demo-kicker">GUIDED FAILURE SCENARIO</p><h2 id="demo-title">{headline}</h2><p>{demo.notice}</p></div>
        <div className="demo-system-state"><span className={`state-glyph state-${demo.phase >= 5 ? 'healthy' : demo.phase >= 1 ? 'failure' : 'healthy'}`}><Signal size={16} /></span><span>{demo.phase >= 5 ? 'RECOVERING / RECOVERED' : demo.phase >= 1 ? 'FAILURE IN PROGRESS' : 'SYSTEM HEALTHY'}</span></div>
      </div>
      <TopologyScene nodes={demo.nodes} trafficActive={demo.isRunning || demo.phase === 0} />
      <div className="demo-metrics" aria-label="Simulation metrics">
        <div><span>AVAILABILITY</span><strong>{formatMetric(demo.summary.availability, 2)}<small>%</small></strong><i className="metric-bar"><b style={{ width: `${Math.min(100, Math.max(0, demo.summary.availability))}%` }} /></i></div>
        <div><span>DETECTION LAG</span><strong>{formatMetric(demo.summary.detectionLag, 1)}<small>ticks</small></strong><i className="metric-note">health-check delay</i></div>
        <div><span>MEAN LATENCY</span><strong>{formatMetric(demo.metric.avg_latency_ms)}<small>ms</small></strong><i className="metric-bar metric-bar-mint"><b style={{ width: `${Math.min(100, demo.metric.avg_latency_ms)}%` }} /></i><i className="metric-note">P95 {formatMetric(demo.metric.p95_latency_ms)} ms</i></div>
        <div><span>REQUESTS LOST</span><strong>{demo.summary.requestsLost}<small>req</small></strong><i className="metric-note">{demo.summary.healthyZones} zones responding</i></div>
      </div>
      {demo.source === 'local' && <p className="demo-local-note"><Circle size={8} fill="currentColor" /> Illustrative values from a repeatable local scenario; not live backend measurements.</p>}
      <div className="demo-story-controls">
        <div className="demo-control-buttons">
          {!demo.isRunning ? <button className="demo-run-button" type="button" onClick={() => void demo.runDemo()}><Play size={14} fill="currentColor" />{demo.phase > 0 ? 'Replay the failure demo' : 'Run the failure demo'}<ArrowRight size={15} /></button> : <button className="demo-run-button" type="button" onClick={() => void demo.togglePause()}>{demo.isPaused ? <Play size={14} fill="currentColor" /> : <Pause size={14} fill="currentColor" />}{demo.isPaused ? 'Resume demo' : 'Pause demo'}</button>}
          {demo.phase > 0 && demo.isRunning && <button className="demo-icon-button" type="button" onClick={() => void demo.runDemo()} aria-label="Replay demo" title="Replay demo"><RotateCcw size={15} /></button>}
          <a className="demo-open-simulator" href="/simulator">Open full simulator <ArrowRight size={14} /></a>
        </div>
        <div className="demo-connection-detail">{demo.source === 'live' ? <Wifi size={12} /> : demo.source === 'checking' ? <Signal size={12} /> : <WifiOff size={12} />}<span>{demo.source === 'live' ? 'API state is observed from the browser.' : demo.source === 'checking' ? 'Checking API reachability…' : 'Local state is clearly separated from live measurements.'}</span></div>
      </div>
      <div className="demo-progress" aria-label="Guided scenario progress">
        {['Healthy', 'Failure', 'Detect', 'Reroute', 'Promote', 'Recover', 'Proof'].map((label, index) => <div key={label} className={`progress-step ${demo.phase === index ? 'is-current' : demo.phase > index ? 'is-complete' : ''}`} aria-current={demo.phase === index ? 'step' : undefined}><span>{String(index + 1).padStart(2, '0')}</span><i /><b>{label}</b></div>)}
      </div>
      <div className="demo-details-wrap">
        <button className="details-toggle" type="button" aria-expanded={showDetails} onClick={() => setShowDetails((open) => !open)}><span>Show technical details</span><ChevronDown size={15} className={showDetails ? 'chevron-open' : ''} /></button>
        {showDetails && <div className="technical-details">
          <div className="technical-intro"><div><span>EVENT TYPE</span><b>{demo.feed[0]?.eventType ?? '—'}</b></div><div><span>TICK</span><b>{String(demo.metric.tick).padStart(4, '0')}</b></div><div><span>TARGET</span><b>{demo.feed[0]?.target ?? '—'}</b></div><div><span>MODE</span><b>{demo.source === 'live' ? 'LIVE API' : demo.source === 'local' ? 'LOCAL DEMO' : 'CHECKING'}</b></div></div>
          <div className="technical-feed" role="region" aria-label="Simulation event log">
            {demo.feed.length ? demo.feed.map((entry) => <div className="technical-row" key={entry.id}><span className={`technical-category category-${entry.category.toLowerCase()}`}>{entry.category}</span><span className="technical-tick">{String(entry.tick).padStart(4, '0')}</span><span className="technical-type">{entry.eventType}</span><span className="technical-target">{entry.target}</span><span className="technical-description">{entry.description}<small>{entry.change}</small></span></div>) : <p className="technical-empty">Start the sequence to inspect event type, tick, target and measured change.</p>}
          </div>
        </div>}
      </div>
    </section>
  );
}
