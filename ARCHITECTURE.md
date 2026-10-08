# BoardScope implementation architecture

## Current boundary

Browser dashboard → loopback FastAPI API → transactional SQLite + local thread worker → simulator or Paramiko SSH adapter → Linux board. Optional pyserial reader captures boot logs from a USB UART attached to the lab PC. Optional local Ollama endpoint analyses captured evidence. The AI has no execution tools.

The API serves the bundled dashboard from the same origin. Clients poll state and selected run details every 1.5 seconds. There are no external UI dependencies, CDN requests or Docker privilege mappings. Python runs natively on the machine with network and serial access.

## Modules

| Module | Responsibility |
| --- | --- |
| `boardscope/__main__.py` | Loopback-only launch and port selection |
| `boardscope/app.py` | API validation, lifecycle, persistence, reservations, runner, controls, evidence comparison and optional AI integration |
| `boardscope/adapters.py` | Fixed Linux capability inspection, one-shot software reboot, evidence capture, reviewed script execution and simulator |
| `boardscope/static/` | Dashboard, boards, tests, history, run controls and evidence UI |
| `tests/test_workflows.py` | Workflow, reservation, recovery, local access, authorisation and model output checks |

## Database schema

| Table | Columns / constraints | Purpose |
| --- | --- | --- |
| boards | id PK, data JSON text | Board configuration and latest capability snapshot |
| scripts | id PK, data JSON text | Immutable script source, SHA-256, timeout and creation time |
| runs | id PK, board_id FK, state, data JSON text | Immutable board/plan/script snapshots plus execution summary |
| cycles | id PK, run_id FK, number, data JSON text; unique(run_id, number) | Checks, timestamps, boot snapshot, bounded kernel/serial logs and simulation flag |
| events | seq autoincrement PK, run_id FK, data JSON text | Recorded reset intent, controls, warnings and execution events |

A partial unique index on runs(board_id) covers queued, running, pausing, paused and stopping. Workers merge updates inside SQLite transactions to preserve operator state. Final outcome aggregation also happens transactionally. Records use UTC timestamps. This is an intentionally small preview schema, not the future normalised multi-tenant schema.

## Run states and outcomes

- Queued → running → completed.
- Running/queued → pausing → paused → running.
- Active → stopping → cancelled.
- Process restart: every previously active run → interrupted; no reset replay.
- Outcomes are separate from states: pass, fail, error, cancelled or inconclusive. A cancelled run preserves a recorded fail/error outcome when one exists.
- On unsuccessful cycle, plan policy is pause, abort or continue. Abort completes with the recorded unsuccessful outcome.

A run stores the plan and board snapshot at creation, so later capability verification does not change historical expectations. Custom scripts are copied into the run's local internal snapshot; API summaries and reports expose identity/hash rather than source.

## API surface

All API requests require the session token injected into the local HTML page.

| Method / path | Action |
| --- | --- |
| GET /api/state | Dashboard state and script metadata |
| POST /api/boards | Register simulator or SSH board |
| POST /api/boards/{id}/verify | Read Linux capability snapshot |
| POST /api/scripts | Register reviewed immutable script |
| POST /api/runs | Reserve a board and create/run a snapshot plan |
| GET /api/runs/{id} | Run summary, cycles and latest 200 events |
| POST /api/runs/{id}/control | Pause / resume / stop |
| GET /api/runs/{id}/report | Download JSON evidence report |
| POST /api/runs/{id}/investigate | Deterministic comparison or optional local-model investigation |

## Next milestones

1. Validate inventory and a short reboot test on the actual RISC-V board with Ubuntu, then the Yocto image. Capture the board model, kernel/build identifiers, network interface, known host fingerprint and required privileges. Add acceptance tests using those real results.
2. Extract runner/persistence/adapters from `app.py` and introduce explicit capabilities and board identity to prevent duplicate physical registrations. Add edit/archive workflows and complete event exports.
3. Add hardware reset/power adapters for a chosen relay/controller with explicit fixture mapping, single ownership, action acknowledgement, electrical constraints and recovery checks. Hard-button resets are not possible through SSH alone.
4. Introduce the installable native host agent with authenticated outbound transport, durable leases, heartbeats, connection recovery and agent-specific serial/SSH mappings. Dashboard cannot directly reach USB devices from the browser.
5. Add PostgreSQL migrations, normalised schema, blob evidence retention and a queue for multiple labs. Validate duplicate delivery, lease expiration, uncertain physical actions and failure recovery before increasing fleet scale.
6. Move the UI to React/TypeScript, add accessibility verification, robust live updates, plan versioning and lab permissions. Provide an actual installer and signed updates.
7. Evaluate local AI on labelled real failures; require evidence references, measure misleading hypotheses, and keep execution independent of model output.

Flashing, manufacturing screening, Android/ADB, performance qualification and certification testing are outside the current version. No claims of universal Ubuntu/Yocto or arbitrary proprietary-board support are made.
