# ChaosNet Landing Page Design

## Goal

Create a polished, interactive landing page for ChaosNet, an interactive cloud VPC and auto-failover simulator. The page must work for three audiences at once: technical evaluators, learners/reviewers, and visitors who simply want to see an engaging webpage.

The landing page should make ChaosNet understandable in seconds, then use a guided live simulation to prove the concept. It should feel like a designed observability product rather than a README rendered in a browser or a generic SaaS template.

## Product story

The page's central story is **failure, made visible**:

1. Two availability zones serve traffic normally.
2. Availability Zone A fails.
3. Health checks detect the failure after a realistic lag.
4. Traffic reroutes to Availability Zone B.
5. The database replica is promoted to primary.
6. The system recovers and reports the result.

The demo should use the existing ChaosNet semantics and terminology, but introduce technical language progressively. A visitor first sees plain-language event captions; an optional details view exposes ticks, event types, targets, and metrics.

## Audience and success criteria

- A non-technical visitor can explain what ChaosNet does after viewing the hero.
- A technical evaluator sees evidence of deterministic simulation, multi-AZ topology, failover, and measured recovery.
- A visual visitor can interact with the page without needing to understand the API or CLI.
- The main path reaches a working demo quickly, with replay and pause controls.
- The page is responsive, keyboard accessible, readable in reduced-motion mode, and visually coherent on mobile.

## Visual direction

### Character

Calm observability control room: dark graphite surfaces, sea-glass healthy states, amber detection states, and coral failure states. The memorable element is the topology canvas and its animated traffic paths. Surrounding copy and sections remain quiet and editorial so the visualization has hierarchy.

### Palette

- `#10151C` — midnight graphite background
- `#18232B` — topology and control surface
- `#E8EEF2` — primary text
- `#65D6C2` — healthy and recovered state
- `#FFB454` — degraded and detection state
- `#F06C5D` — failure and injected chaos
- `#91A4B2` — secondary text and inactive structure

### Typography

- Space Grotesk for headings, navigation, buttons, and key interface values.
- IBM Plex Sans for body copy, descriptions, and explanatory content.
- A restrained monospace face only for technical event details and tick readouts.

Use sentence case, left-aligned copy, and short line lengths. Avoid all-caps eyebrow labels and generic metric-card repetition.

## Page structure

### 1. Header

Brand mark and wordmark on the left. Navigation links: How it works, Architecture, Evidence. Primary action: Run the demo. On mobile, collapse navigation into a compact menu or keep only the primary action visible.

### 2. Hero and live demo

Two-column layout on desktop, stacked on mobile.

Left column:

- Headline: `Make failure measurable.`
- Supporting copy: explain that ChaosNet is a deterministic cloud network simulator that shows what happens when infrastructure stops behaving.
- Primary action: `Run the failure demo`
- Secondary action: `Explore the simulator`
- Small proof line: `Multi-AZ topology · seeded runs · measured recovery`

Right column:

- Live simulation panel with a topology diagram: Internet Gateway, Zone A, Zone B, application paths, and database roles.
- Status line showing the current phase in plain language.
- Controls: Run demo, pause, replay, and show technical details.
- A compact live metrics strip for tick, availability, requests, and current incident.
- Event feed that updates as the scenario progresses.

The demo should have a short, deliberate sequence rather than continuous decorative motion. The initial state is healthy. Run starts the scripted scenario. At the failure phase, Zone A visibly dims and turns coral; traffic paths move through Zone B; the replica changes to primary; the result state presents the measured summary. Replay returns to the initial state.

### 3. What ChaosNet proves

A horizontal or two-column explanatory section with four proof statements:

- Failures have detection lag.
- Routes adapt to live topology state.
- Replicas can become primary without split-brain.
- Recovery is measured, not assumed.

Each statement should pair a plain-language sentence with a concise technical detail revealed on interaction or hover/focus. Do not use identical cards with decorative icons; vary the layout through a central explanation and supporting evidence lines.

### 4. Engineering evidence

Present evidence as a clean, readable table/list rather than a wall of badges:

- deterministic seeded runs
- role-aware shortest-path routing
- multi-Availability Zone topology
- seven chaos primitives
- REST and WebSocket control surface
- 44 automated tests across eight phases

Technical visitors should be able to expand a “How it works” disclosure to see the tick order: chaos, health, failover, traffic, metrics.

### 5. Choose your depth

Three clear next steps:

- Watch the guided demo — for a quick understanding.
- Explore the architecture — for system design details.
- Run your own scenario — for hands-on interaction.

These should link to real product routes or clearly marked future destinations. Do not imply an unavailable feature is complete.

### 6. Closing CTA

`Break the network. Understand the recovery.`

Button: `Open ChaosNet`.

## Interaction and motion

- One coordinated demo sequence is the primary motion moment.
- Traffic paths animate only while the demo is running.
- Status changes use color plus text; never rely on color alone.
- Hover and focus states explain technical details, not merely decorate controls.
- Pause immediately stops animation; replay resets all visual and metric state.
- Respect `prefers-reduced-motion` by switching to instant state changes and keeping all information visible.
- Keyboard focus must be clearly visible. Every interactive control needs an accessible name.

## Implementation boundaries

- First delivery is the landing page and its self-contained guided demo.
- Reuse the existing simulator terminology and scenario behavior where practical.
- If the API is available locally, the page may consume it; otherwise the landing-page demo must have a deterministic front-end presentation so the page remains compelling when opened alone.
- Do not add a design system, state-management library, chart library, or animation library unless an existing project dependency requires it. CSS and small local JavaScript are sufficient for the landing-page interaction.
- Do not fabricate production claims, customer logos, or operational data. Demo metrics must be clearly labeled as simulation output.

## Responsive behavior

- Desktop: two-column hero with a large simulation panel.
- Tablet: reduced-width two-column layout or stacked controls.
- Mobile: copy first, then simulation panel; controls become full-width or wrap; topology remains legible through simplified labels and horizontal scrolling inside the panel only if necessary.
- Maintain a 16px minimum page gutter and avoid horizontal page scrolling.

## Testing and verification

- Run the existing Python test suite before and after product changes.
- Start the relevant web server and inspect the page in a browser at desktop and mobile widths.
- Verify the demo path: initial state, run, failure, reroute, promotion, recovery, pause, replay, and technical-details toggle.
- Verify keyboard navigation, visible focus, reduced-motion behavior, and basic color contrast.
- Confirm unavailable routes or features are not represented as working destinations.
