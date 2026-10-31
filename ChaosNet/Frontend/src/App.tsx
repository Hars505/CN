import { useEffect } from 'react';
import LandingPage from './landing/LandingPage';
import SimulatorApp from './Simulator';

export default function App() {
  const route = window.location.pathname.replace(/\/+$/, '') || '/';
  const isSimulator = route === '/simulator';

  useEffect(() => {
    const description = isSimulator
      ? 'Operate the ChaosNet multi-availability-zone cloud resilience simulator and inject controlled infrastructure failures.'
      : 'Watch cloud failure unfold across two availability zones, follow the failover, and measure recovery with a guided ChaosNet simulation.';
    document.title = isSimulator ? 'ChaosNet — Full simulator' : 'ChaosNet — Failure, made visible';
    document.body.classList.toggle('landing-route', !isSimulator);
    const descriptionTag = document.querySelector<HTMLMetaElement>('meta[name="description"]');
    if (descriptionTag) descriptionTag.content = description;
    let robotsTag = document.querySelector<HTMLMetaElement>('meta[name="robots"]');
    if (isSimulator) {
      if (!robotsTag) {
        robotsTag = document.createElement('meta');
        robotsTag.name = 'robots';
        document.head.appendChild(robotsTag);
      }
      robotsTag.content = 'noindex,follow';
    } else if (robotsTag?.content === 'noindex,follow') {
      robotsTag.remove();
    }
  }, [isSimulator]);

  return isSimulator ? <SimulatorApp /> : <LandingPage />;
}
