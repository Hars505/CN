# ChaosNet Landing Page and Guided Failure Demo

## Approved direction

Redesign `/` as the public-facing “Failure, made visible” landing page. Preserve the current full control-room dashboard at `/simulator`. The hero itself contains an interactive topology and the primary guided failure/recovery story. Use the real ChaosNet FastAPI/WebSocket service when it is reachable from the browser; otherwise run an explicitly labeled deterministic local demo, never presenting local sample metrics as backend measurements.

## Implementation approach

Keep the existing dashboard UI and backend integration intact by moving the current root dashboard component to `src/Simulator.tsx`. Replace `src/App.tsx` with a small pathname switch for `/` and `/simulator`. Implement the landing route in focused modules: `src/landing/LandingPage.tsx` for public page composition and calls to action, `src/landing/GuidedFailureDemo.tsx` for the timed scenario, technical details and API/deterministic modes, and `src/landing/TopologyScene.tsx` for the responsive interactive SVG topology. Style the new public experience in `src/landing/landing.css`; retain `src/styles.css` for global baseline and the existing simulator.

The guided script progresses through healthy baseline, an Availability Zone A failure, detection, rerouting, replica promotion, recovery and measured proof. On an API-backed run it resets/starts the simulation, posts the documented AZ failure and recovery chaos requests, watches REST topology/metrics and WebSocket `INITIAL_STATE`/`TICK_UPDATE`/event messages, and advances captions only when evidence is observed or explicitly says it is awaiting confirmation. On offline runs it applies a repeatable local topology/metric sequence and clearly labels it “Deterministic local demo.” The UI supports pause, replay, a technical details disclosure showing event type/tick/target/metric changes, and a direct link to `/simulator`.

Update `public/manus-routes.json` to declare `/` and `/simulator`. Keep the current pinned React/Vite/TypeScript toolchain and Lucide dependency; use typography links for Space Grotesk, IBM Plex Sans and restrained DM Mono without adding a new framework. Enrich the existing `index.html` with a useful content-bearing landing-page fallback, page title, description and social metadata. Do not invent a canonical/public origin. Use no server/database additions. Preserve existing `app.config.ts` logo metadata.

## Project structure

- `src/App.tsx`: route dispatcher for the landing page and `/simulator`.
- `src/Simulator.tsx`: preserved existing full cloud operations dashboard.
- `src/landing/LandingPage.tsx`: editorial homepage, explanatory sections, CTA and footer.
- `src/landing/GuidedFailureDemo.tsx`: real API/WebSocket sequence and explicit deterministic local fallback.
- `src/landing/TopologyScene.tsx`: two-zone interactive SVG with stage-driven status and traffic paths.
- `src/landing/landing.css`: landing-only colors, typography, layout and responsive behavior.
- `src/api.ts` and `src/types.ts`: existing REST helpers, normalized topology and metric types reused by both routes.
- `public/manus-routes.json`: the public landing route and retained simulator route.
- `index.html`: page metadata and content-bearing landing fallback for the root URL.

## Design system

- **Design Movement:** editorial observability product design—calm, engineered, and narrative-led rather than a generic SaaS hero or an analytics dashboard.
- **Core Principles:** (1) explain failure/recovery in plain language before exposing implementation detail; (2) make the topology itself the visual proof; (3) distinguish measured backend state from deterministic local mode; (4) give technical users optional depth without making all content terminal-like.
- **Color Philosophy:** midnight graphite `#10151C` and topology surfaces `#18232B` reduce glare and frame the system as a steady operations instrument. Cool mint `#65D6C2` means healthy or recovered, warm amber `#FFB454` means detected/degraded, and coral `#F06C5D` means injected failure. Primary text is `#E8EEF2`; borders remain quiet and translucent.
- **Layout Paradigm:** a left-aligned editorial narrative is paired with a large, live topology canvas. The hero begins as a split stage, then the story moves down the page through proof, engineering evidence, depth choices and a closing CTA; it avoids a centered card grid.
- **Signature Elements:** a two-AZ topology with moving request signals; one horizontal failure-to-recovery timeline that progresses with the demo; compact proof metrics that use the same state/color language as the topology.
- **Interaction Philosophy:** one strong “Run the failure demo” action starts the guided story. Pause/replay are always near the topology. “Show technical details” progressively reveals event names, tick, target and metric changes; “Open full simulator” leads to the retained operational dashboard.
- **Animation:** request particles move only on healthy paths; failure changes are short and restrained (coral pulse, then muted path), detection uses amber, recovery uses a single mint sweep. Honor `prefers-reduced-motion` by disabling looping particles/transitions and preserve every status in static labels.
- **Typography System:** Space Grotesk for large headlines and editorial section headings; IBM Plex Sans for body copy, controls and metric labels; DM Mono only in the optional event log and compact technical details. Keep body copy readable and avoid monospace-heavy presentation.
- **Brand Essence:** a deterministic cloud resilience simulator for engineers and technical evaluators who need to see how failures propagate and recover; **clear, rigorous, composed**.
- **Brand Voice:** plain, direct, evidence-oriented; primary lines: “Make failure measurable.” and “Break the network. Understand the recovery.”
- **Wordmark & Logo:** retain the custom ChaosNet network-node mark and pair it with a carefully tracked Space Grotesk wordmark, not default text styling.
- **Signature Brand Color:** `#65D6C2`—the mint recovery signal that uniquely links proof metrics, healthy paths and restored service.

## Claims and boundaries

Use only behavior implemented in the site or confirmed by the live API. Do not repeat the attachment’s “44 automated tests across eight…” or role-aware shortest-path claims unless the repository or backend confirms them. Backend state may be unavailable in a hosted Preview because browser loopback addresses refer to the viewer; local-demo mode must remain explicit and visibly distinct.
