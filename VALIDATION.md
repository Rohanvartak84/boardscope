# Validation — BoardScope 0.1

Verified in this environment on 2026-10-08, using Python 3.12.

- Backend: **12 pytest checks passed**. Covers simulator reboot UUID changes and evidence, failure pause/resume, active-board reservation, cancellation/release, restart interruption, local access controls, explicit physical action authorisation, atomic state updates, real Linux capability script execution on the host, argument shell escaping, SSH host-key rejection and cleanup, reviewed custom-script invocation through a mock SSH adapter, and mocked local inference output validation/persistence.
- Dashboard: **live-service DOM integration checks passed**. Covers passing reboot, simulated failure/pause, evidence comparison, resume, custom-script registration, board registration and HTML escaping.
- JavaScript syntax check passed.
- One upstream test-client deprecation warning was emitted; tests use the installed httpx compatibility path.

Not verified: physical RISC-V hardware, UART capture on hardware, Ubuntu/Yocto image compatibility on that board, actual SSH reboot permissions, actual local model inference, fleet throughput or browser visual layout/accessibility. A Chromium download failed in this environment; DOM checks were used instead. This is an engineering preview, not a production release.
