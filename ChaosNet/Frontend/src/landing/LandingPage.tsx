import { ArrowDown, ArrowRight, ArrowUpRight, Activity, Cable, Database, Layers3, Network, Radar, ShieldCheck, Waypoints, Zap } from 'lucide-react';
import GuidedFailureDemo from './GuidedFailureDemo';
import { useGuidedDemo } from './useGuidedDemo';
import './landing.css';

const proofPoints = [
  { number: '01', icon: <Radar size={17} />, title: 'Detection is not instantaneous.', body: 'A failure begins before the system knows it. Watch health checks close that gap.' },
  { number: '02', icon: <Waypoints size={17} />, title: 'Routing follows topology.', body: 'See requests leave a failed zone and continue through the infrastructure that remains.' },
  { number: '03', icon: <Database size={17} />, title: 'Verify a single primary.', body: 'Follow replica promotion and check that recovery does not create split-brain.' },
  { number: '04', icon: <Activity size={17} />, title: 'Recovery leaves evidence.', body: 'Availability, latency and request loss show what the incident cost and how the system recovered.' },
];

const engineeringEvidence = [
  { icon: <Layers3 size={17} />, title: 'Multi-AZ topology', detail: 'Two zones · public and private network layers' },
  { icon: <Cable size={17} />, title: 'REST + WebSocket', detail: 'Controls, state updates and event stream' },
  { icon: <ShieldCheck size={17} />, title: 'Controlled failures', detail: 'Zone, node, network and database scenarios' },
  { icon: <Activity size={17} />, title: 'Measured outcomes', detail: 'Availability · detection · latency · recovery' },
];

export default function LandingPage() {
  const demo = useGuidedDemo();

  return (
    <div className="landing-page">
      <header className="landing-header">
        <a className="landing-brand" href="/" aria-label="ChaosNet home"><span className="landing-brand-mark"><Network size={17} /><i /></span><span>CHAOS<span>NET</span></span></a>
        <nav className="landing-nav" aria-label="Main navigation"><a href="#how-it-works">How it works</a><a href="#evidence">Engineering evidence</a><a href="/simulator">Architecture</a></nav>
        <button className="header-demo-cta" type="button" onClick={() => void demo.runDemo()}>Run demo <ArrowRight size={14} /></button>
      </header>

      <main>
        <section className="landing-hero">
          <div className="hero-copy">
            <p className="landing-eyebrow"><span className="eyebrow-rule" /> FAILURE, MADE VISIBLE</p>
            <h1>Make failure<br /><em>measurable.</em></h1>
            <p className="hero-description">A deterministic cloud network simulator that shows what happens when infrastructure stops behaving — and how recovery takes shape.</p>
            <div className="hero-actions"><button className="primary-cta" type="button" onClick={() => void demo.runDemo()}><Zap size={15} fill="currentColor" />Run the failure demo<ArrowRight size={16} /></button><a className="secondary-cta" href="/simulator">Explore the simulator <ArrowUpRight size={14} /></a></div>
            <div className="hero-footnote"><span className="hero-footnote-dot" />One controlled failure. Two availability zones. A measurable recovery.</div>
            <a className="scroll-cue" href="#how-it-works"><span>SCROLL TO EXPLORE</span><ArrowDown size={13} /></a>
          </div>
          <GuidedFailureDemo demo={demo} />
        </section>

        <section className="story-band" id="how-it-works" aria-label="Failure and recovery story">
          <div className="story-band-heading"><p className="landing-eyebrow">THE RESILIENCE LOOP</p><h2>Failure is the input.<br /><span>Recovery is the behavior.</span></h2></div>
          <div className="story-band-steps"><div><span>01</span><b>Inject</b><p>Take a zone offline.</p></div><i /><div><span>02</span><b>Observe</b><p>Follow checks and reroutes.</p></div><i /><div><span>03</span><b>Recover</b><p>Verify the system state.</p></div></div>
        </section>

        <section className="proof-section">
          <div className="section-heading"><p className="landing-eyebrow"><span className="eyebrow-rule" /> WHAT CHAOSNET PROVES</p><h2>See the system<br /><em>under pressure.</em></h2><p className="section-lede">Resilience is more than a green check. It is a sequence: detect, adapt, promote and recover.</p></div>
          <div className="proof-list">{proofPoints.map((point) => <article className="proof-point" key={point.number}><span className="proof-number">{point.number}</span><span className="proof-icon">{point.icon}</span><div><h3>{point.title}</h3><p>{point.body}</p></div><ArrowUpRight className="proof-arrow" size={16} /></article>)}</div>
        </section>

        <section className="evidence-section" id="evidence">
          <div className="evidence-heading"><div><p className="landing-eyebrow">ENGINEERING EVIDENCE</p><h2>Built to be<br /><em>inspected.</em></h2></div><p>The guided story stays readable. Every state change can still be traced through the topology, event stream and simulator controls.</p></div>
          <div className="evidence-rail">{engineeringEvidence.map((item, index) => <article className="evidence-item" key={item.title}><span className="evidence-index">0{index + 1}</span><span className="evidence-icon">{item.icon}</span><h3>{item.title}</h3><p>{item.detail}</p></article>)}</div>
        </section>

        <section className="depth-section" id="choose-depth">
          <div className="depth-heading"><p className="landing-eyebrow">CHOOSE YOUR DEPTH</p><h2>Start with the story.<br /><em>Stay for the system.</em></h2></div>
          <div className="depth-links"><a href="#run-demo"><span className="depth-count">01 / WATCH</span><strong>Follow the failure demo</strong><span>See one incident unfold, step by step.</span><ArrowRight size={16} /></a><a href="/simulator"><span className="depth-count">02 / EXPLORE</span><strong>Inspect the architecture</strong><span>Open the full VPC control room.</span><ArrowRight size={16} /></a><a href="/simulator"><span className="depth-count">03 / RUN</span><strong>Try your own scenario</strong><span>Choose a fault and measure recovery.</span><ArrowRight size={16} /></a></div>
        </section>

        <section className="final-cta">
          <div><p className="landing-eyebrow"><span className="eyebrow-rule" /> RESILIENCE, DEMONSTRATED</p><h2>Break the network.<br /><em>Understand the recovery.</em></h2></div>
          <div className="final-actions"><button className="primary-cta" type="button" onClick={() => void demo.runDemo()}><Zap size={15} fill="currentColor" />Run the failure demo<ArrowRight size={16} /></button><a href="/simulator">Open the full simulator <ArrowUpRight size={14} /></a></div>
        </section>
      </main>

      <footer className="landing-footer"><a className="landing-brand" href="/" aria-label="ChaosNet home"><span className="landing-brand-mark"><Network size={15} /><i /></span><span>CHAOS<span>NET</span></span></a><span className="footer-note">Cloud failure, made observable.</span><div><a href="#how-it-works">How it works</a><a href="/simulator">Simulator</a><span>VPC · 10.0.0.0/16</span></div></footer>
    </div>
  );
}
