# Validation — BoardScope 0.1

Verified in this environment on 2026-10-08, using Python 3.12.

- Backend: **12 pytest checks passed**. Covers simulator reboot UUID changes and evidence, failure pause/resume, active-board reservation, cancellation/release, restart interruption, local access controls, explicit physical action authorisation, atomic state updates, real Linux capability script execution on the host, argument shell escaping, SSH host-key rejection and cleanup, reviewed custom-script invocation through a mock SSH adapter, and mocked local inference output validation/persistence.
- Dashboard: **live-service DOM integration checks passed**. Covers passing reboot, simulated failure/pause, evidence comparison, resume, custom-script registration, board registration and HTML escaping.
- JavaScript syntax check passed.
- One upstream test-client deprecation warning was emitted; tests use the installed httpx compatibility path.

Not verified: physical RISC-V hardware, UART capture on hardware, Ubuntu/Yocto image compatibility on that board, actual SSH reboot permissions, actual local model inference, fleet throughput or browser visual layout/accessibility. A Chromium download failed in this environment; DOM checks were used instead. This is an engineering preview, not a production release.

## Connection milestone 0.2

20 Python checks pass locally, including the existing workflows plus session-only password handling, validation/error redaction, explicit SSH password authentication, editable connections, independent SSH/UART verification, UART run blocking, bootloader refusal and real pyserial I/O through Linux pseudo-terminals emulating automatic shell and username/password login. The fixed identity script reads the test host; no physical board is contacted.

The DOM harness now also exercises SSH password board registration, connection editing, saved-transport buttons and forgetting session passwords. It uses a live local service with disposable data and never opens a network connection to the fake board.

Physical UART/SSH acceptance on the user's RISC-V board and browser visual rendering remain unverified.

## UART inventory milestone 0.2.1

25 backend checks pass locally. Additional coverage checks inventory dispatch from UART and SSH-primary boards, recorded UART transport, one open/close per run, no SSH or separate serial-reader access, missing-port validation, unsupported UART test rejection, and repeated inventory commands over a retained real pyserial pseudo-terminal session with automatic-shell and password-login emulation.

The live-service DOM harness verifies the UART board's Start test action, default/selected UART transport, disabled reboot/custom options, UART run labels and an explicit missing-device failure using a deliberately nonexistent serial path. Physical hardware and browser visual rendering are not verified here.

## Dual transport milestone 0.3

39 backend checks pass locally. Coverage includes real pyserial pseudo-terminal console emulation for username/password login, root and password-sudo reboot, changed boot identity after re-login, credential echo redaction, rejected sudo, chunked scripts larger than a terminal line, shell-quoted arguments, combined console output, nonzero exit codes and uncertain timeout blocking. Fake adapters verify reboot recovery after SSH/IP loss without a second reset, custom execution stopping after an uncertain result, host-trust failure blocking fallback, action/pairing authorisation, and actual cycle transport metadata.

The live-service DOM harness verifies sudo settings/editing, fallback selection and pairing confirmation, enabled UART test choices and existing workflows. No physical hardware was rebooted; no actual SSH server, real board sudo configuration, hardware UART reconnect behavior or browser layout has been validated here. Physical acceptance is required before unattended testing.

## Settings clarity (0.3.1)

43 backend checks pass locally, including three profile edit/credential cases that preserve the unchanged profile's configuration and verification result while invalidating the edited profile. UI DOM coverage checks saved SSH/UART summaries, separate tabs, correct prefilled values, unsaved-state check disabling, profile preservation and selected-test connection summaries. Browser visual layout and physical hardware remain unverified.

## SSH-first dashboard redesign

Live-service DOM checks cover the three-step home, compact cards, SSH-only quick setup/editing and blank secret fields, advanced profile access, preserved old workflows, collapsed run options, and test-dependent custom/reboot controls. JavaScript syntax passes. No backend execution changes are introduced. Browser visual rendering and physical board behavior remain unverified.


### Result guidance and management

Added mocked workflow coverage for baseline error location, custom-script stdout/stderr and exit codes, script-edit snapshot preservation, board removal/history/password clearing and active-run removal rejection. Live-service DOM checks cover script viewing/editing, failure guidance, storage disclosure and confirmed board removal. JavaScript syntax and Python workflow tests are required. Physical hardware and visual browser layout remain unverified.


### Frontend redesign checks

Frontend-only fixtures in `tests/ui-dashboard.cjs` verify six-item navigation, four data-derived summaries, recorded error/stage rendering, stable row/input identity and focus during refresh, SSH-first/UART-success checking, no-UART and host-trust failure paths, disabled Assistant generation/context, authorized auto-transport selection, mobile menu/drawer behavior and disconnected recovery. Run with the same jsdom NODE_PATH as `tests/dashboard.cjs`. The live-service DOM harness retains simulator reboot/failure/resume, script editing, saved board settings, removal and escaping coverage. Backend code is unchanged; the 49-test regression suite passes. Chromium download was unavailable in this environment, so visual browser layout validation and physical-board verification remain outstanding.


### Reference layout verification

The reference refinement was rendered and visually reviewed in Chromium at 1774px with the Assistant open, and with a full-screen mobile Assistant at 390px. `tests/ui-layout.cjs` exercises the actual bundled frontend with intercepted synthetic API fixtures, checks no page-level horizontal overflow at 1774, 1280, 820 and 390px, verifies the collapsed default/disabled Assistant actions, and captures review images. It issues no requests to hardware. Screenshots are marked UI fixture/synthetic data and are not evidence of a lab session. This supersedes the earlier lack of browser layout verification for the redesigned interface.

The optional layout harness requires Playwright in a development verification directory (not a production dependency); set `NODE_PATH` to its node_modules. Set `BOARDSCOPE_BROWSER_EXECUTABLE` for a local Chromium executable and optionally `BOARDSCOPE_SCREENSHOT_DIR` for review output, then run `node tests/ui-layout.cjs` from the repository root. Interaction regression checks remain `tests/ui-dashboard.cjs` and the live-service `tests/dashboard.cjs` harness.


### Unified executor verification

Contract/factory tests construct every supported executor without touching hardware and reject unknown transports. Mock SSH channels verify simultaneous stdout/stderr draining, real/nonzero versus absent exit status, partial evidence on silent command deadlines and cancellation, acknowledgement interruption, explicit close, no automatic replay and pre-dispatch authentication/reboot classification. Serial tests exercise shared ownership through aliases, optional capture contention, echo filtering, invalid completion status and persistent-shell memory-only script transfer over PTYs. Credential tests cover scoped snapshot isolation, redaction, transient encrypted private-key parsing and absence of key material from API state/SQLite. Existing workflow tests use contract-compliant mocks, including additive execution evidence and sticky UART fallback. Physical hardware remains unverified; thread deadlines do not establish an OS-level hard-kill guarantee.
