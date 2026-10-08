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
