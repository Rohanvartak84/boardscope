# BoardScope contributor instructions

BoardScope is a local embedded Linux testing workbench for Ubuntu and Yocto-built images, initially targeting validation on the owner's RISC-V board.

## Work boundaries

- Run the application on the lab PC; board commands run through an explicit adapter.
- Keep the dashboard, evidence and credentials local. The current dashboard binds to loopback.
- Never commit SSH keys, passwords, .env files, local databases, proprietary logs or customer source code.
- Never contact or reboot physical hardware while developing or testing unless explicitly authorised for that specific task. Use simulators and mocked adapters.
- Record physical reset intent before execution. Do not automatically replay uncertain physical actions after connection loss or process restart.
- Deterministic checks decide outcomes. AI generates reviewable observations and hypotheses; never grant it unrestricted command execution.
- Keep simulation explicit in UI, results and reports.

## Repository

- boardscope/app.py: FastAPI, SQLite, local worker and API.
- boardscope/adapters.py: simulator and SSH adapter.
- boardscope/static/: bundled dashboard, no production Node dependency.
- tests/: Python workflow/adapter checks and optional DOM integration harness.
- ARCHITECTURE.md and README.md: current capabilities and setup limitations.

## Validation

Use Python 3.11+ and install requirements-dev.txt in a virtual environment. Run `python -m pytest -q`. Changes to JS must pass `node --check boardscope/static/app.js`. For UI interactions use the documented jsdom harness against a fresh disposable service data directory. Clearly distinguish DOM verification from browser layout testing and mocks from physical hardware results.

## Collaboration

Work on a feature branch, keep changes scoped and open a pull request describing the behavior and validation. Do not replace unrelated user changes. Do not claim SSH password login or UART shell execution exists until it is implemented and tested. Track limitations in README.md when changing behavior.
