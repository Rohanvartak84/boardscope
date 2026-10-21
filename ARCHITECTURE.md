# BoardScope implementation architecture

## Current boundary

Browser dashboard → loopback FastAPI API → transactional SQLite + local thread worker → shared BoardExecutor contract → simulator, Paramiko SSH, pyserial UART or authorized fallback coordinator. Optional passive serial capture belongs to the SSH executor and shares serial ownership with UART command sessions. Optional local Ollama endpoint analyses captured evidence. The AI has no execution tools.

The API serves the bundled dashboard from the same origin. Clients poll state and selected run details every 1.5 seconds. There are no external UI dependencies, CDN requests or Docker privilege mappings. Python runs natively on the machine with network and serial access.

## Modules

| Module | Responsibility |
| --- | --- |
| `boardscope/__main__.py` | Loopback-only launch and port selection |
| `boardscope/app.py` | API validation, lifecycle, persistence, reservations, runner, controls, evidence comparison and optional AI integration |
| `boardscope/executor.py` | Abstract executor, capabilities, validated requests, normalized results, deadlines/cancellation and error classification |
| `boardscope/factory.py` | Side-effect-free construction for SSH, UART, simulator and automatic fallback |
| `boardscope/linux_shell.py` | Shared POSIX shell-based Linux inventory and evidence collection |
| `boardscope/adapters.py` | SSH executor and simulator |
| `boardscope/uart.py` | Single-owner serial shell, framing, memory-only script transfer and reboot observation |
| `boardscope/fallback.py` | Pre-dispatch connection selection and observation after reboot; no uncertain-action replay |
| `boardscope/serial_resource.py` | Canonical-path serial leases and optional passive evidence capture |
| `boardscope/credentials.py` | Volatile process credential broker and run-scoped snapshots |
| `boardscope/static/` | Dashboard, boards, tests, history, run controls and evidence UI |
| `tests/test_workflows.py` | Workflow, reservation, recovery, local access, authorisation and model output checks |

## Database schema

| Table | Columns / constraints | Purpose |
| --- | --- | --- |
| boards | id PK, data JSON text | Board configuration and latest capability snapshot |
| scripts | id PK, data JSON text | Versioned script source, SHA-256, timeout and creation time; runs keep snapshots |
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

## Connection milestone (0.2)

`credentials.py` owns a locked per-process secret map, session presence metadata and evidence/error redaction. Password fields are Pydantic SecretStr inputs excluded from serialised board records. The validation-error handler omits original input values. Lifespan clears credentials on startup/shutdown.

`uart.py` adds bounded Linux login and identity verification through pyserial. A per-port lock and Linux exclusive serial opening protect concurrent UART verification. A nonce-delimited command response separates shell echo from script output. Its identity script is the same fixed Linux inspection used by SSH, executed through a quoted POSIX printf pipeline. UART test runs are explicitly blocked pending a dedicated run/session implementation.

New API behavior: POST `/api/boards/{id}/connection` edits settings while idle; POST `/api/boards/{id}/forget-passwords` clears memory-only secrets while idle; GET `/api/serial-ports` lists local devices; POST `/api/boards/{id}/verify` accepts an optional transport of ssh, uart or simulator and saves separate last-check states. Password values are not present in responses or persisted metadata. Known host verification still applies to password-based SSH.

Continuous UART streaming, serial command/log ownership during test runs, hardware identity, trusted SSH reconnection after IP changes, and credential-manager storage remain next milestones.

## UART inventory milestone (0.2.1)

RunInput adds an optional explicit transport (ssh/uart/simulator), defaulting to the board's primary mode for compatibility. Run creation validates physical/simulator boundaries, serial/SSH configuration, and UART's inventory-only capability. The immutable run plan records the resolved transport; the board snapshot's mode selects that adapter without changing the saved board configuration.

UARTBoard now exposes open/close session methods. Verification still opens and closes a temporary session, while the worker retains a logged-in serial session across inventory cycles and closes it on success, error, cancellation or shutdown. UART command I/O has a single reader; the independent serial capture thread is used only by SSH runs. Reboot/custom UART execution and automatic transport fallback remain blocked.

## Dual transport execution (0.3)

`transport.py` distinguishes host trust failures, explicit action rejection and uncertain delivery/results. `fallback.py` selects SSH first with read-only inspection and switches to a single retained UART session when connection/readiness fails. Fallback is sticky for that run and never redispatches a script/reset. Explicit pairing authorisation is required because profiles are engineer-configured; boot UUIDs are not permanent hardware identity. Configuring the wrong UART port is a setup error that cannot be resolved by IP discovery.

`uart.py` adds passive reboot observation, nonce-specific sudo prompts and credential re-login. Custom source is transferred in bounded quoted octal printf chunks into an exclusively created private temporary file. Arbitrary script timeouts mark execution uncertain, block subsequent serial commands and terminate the run without a retry. UART stdout/stderr are merged by the console. Backend run records include actual cycle transport, connection warnings and fallback attempted/used flags. The dashboard exposes SSH/UART/auto, action authorisations and memory-only sudo settings.

Readiness probes use the configured deadline, but transport operations are bounded attempts rather than hard real-time guarantees. Reboot dispatch has its own bounded credential/response phase. Serial evidence is collected when UART owns the stream; there is no independent background UART reader in fallback mode. SSH-only runs retain optional serial capture; auto/UART runs never start a competing reader.


## Unified executor milestone (current)

The common contract is implemented by SSHBoard, UARTBoard, Simulator and FallbackBoard. UART no longer subclasses SSH; both reuse LinuxShell. The runner configures cancellation, opens one executor, inspects readiness, performs plans, consumes normalized execution/serial/command evidence and closes the executor in a finally boundary. It contains no serial-opening or transport-specific session branches. Existing command/script tuple primitives are retained inside implementations for compatibility; reviewed workloads use ExecutionRequest and ExecutionResult.

The factory validates transport names and only constructs objects. Fallback selection remains separate. Host trust, cancellation and uncertain-action errors are not converted into fallback opportunities. Following a dispatched script with a missing result, the run stops irrespective of continue policy, and that executor refuses a further workload. Reboots distinguish preflight/not-dispatched failure, explicit rejection and uncertain delivery. Intent is recorded before reviewed workload/reboot dispatch. Recovery observes boot identity and never issues a second reset.

Execution records distinguish completion, dispatch certainty, optional exit status, combined versus separate streams, partial output, error class/type, duration, evidence completeness and whether remote execution may continue. They are additive cycle evidence, not a database migration or changed pass/fail rule. A completed nonzero reviewed script still follows its exit-code assertion contract; no remote status is an execution uncertainty rather than a failed assertion.

SSH uses finite connect/auth/banner/channel waits, an absolute workload/command deadline, cancellation checks, fair stdout/stderr consumption and bounded input/output. A deadline/cancellation watcher closes the client during blocking library acknowledgement waits. Output is consumed before retrieving status; missing exit status is not accepted as an ordinary failure code. Explicit cleanup closes channels/clients. These are cooperative thread-based protections, not hard process isolation: stalled OS DNS resolution or an uninterruptible native driver operation can still require process supervision, which remains a future milestone. Local cancellation/connection closure does not prove target process termination.

UART preserves a persistent shell under a shared canonical-port lease and POSIX exclusive-open request. Command frames use unpredictable transaction IDs, line boundaries and validated POSIX exit status. Echo is outside the command response envelope; malformed/missing action completion blocks further action. Scripts are transferred in bounded octal chunks into a shell variable, with a sentinel preserving trailing newlines, then piped to a native child shell. No BoardScope helper, daemon or temporary script file is installed. Source is bounded to 64000 UTF-8 bytes and cannot contain NUL. Completed scripts unset the variable; unresolved sessions may retain volatile target shell data until inspected or closed. Arbitrary scripts can themselves modify the board, spawn children or affect shell history; no universal remote cleanup guarantee is claimed.

Credential fields are excluded from persisted board/run configuration. A worker owns a volatile scoped snapshot through cleanup; changing the broker's session values does not silently change an in-flight run's credentials. Explicit API inputs ssh_private_key and ssh_key_passphrase support in-memory SSH private-key parsing without temporary files or implicit disk/agent lookup for that session key. Existing explicit file-path/agent authentication remains compatible and is not claimed to be an exclusively volatile external key store. The dashboard has no new private-key input in this milestone. Known-host public trust data can remain on disk. Authentication traffic is excluded from UART login evidence; other evidence is redacted against known scoped/session secrets. Python memory zeroization and protection against OS swap/core dumps are not guaranteed.

Existing board reservations remain backed by SQLite's active-run uniqueness constraint. Shared serial leases also prevent SSH passive capture and UART commands from opening the same canonical port independently. Optional passive-capture failure produces evidence warnings, not a failed SSH test or a false fallback flag. OS exclusivity is platform/driver dependent and cannot guarantee cooperation from every external terminal. Pairing authorization and permanent board identity remain distinct: a boot UUID changes across reboot and is not a permanent asset identifier.
