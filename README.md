# BoardScope 0.2 — local engineering preview

A runnable first version of the embedded Linux test workbench. The browser dashboard talks to a local Python service. The service runs a simulator or SSH commands on a configured board and saves results on the lab PC. No Docker, board-side package, cloud account or frontend build is required.

## Start

Python 3.11+ on a Linux lab PC is the initial target. This build was verified with Python 3.12. Windows/macOS host and actual RISC-V board support have not been physically validated.

```sh
cd boardscope
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m boardscope
```

Open **http://127.0.0.1:8000** in a browser. Choose another local port using `--port 8080`. On Windows, venv executables are under `.venv\Scripts` instead of `.venv/bin`.

The downloadable source excludes the development environment and test data. Installation needs access to Python package repositories. The application itself needs no internet connection unless using SSH to a board over a network.

## First demo

1. Select **Start test**, choose the Ubuntu simulator, select Reboot endurance and start five cycles. It should pass.
2. Start the same test using the Yocto simulator with “Pause for investigation”. The synthetic board loses one sound device on cycle 3.
3. Review checks and kernel evidence. Select **Compare evidence** to compare against cycle 2. This is a deterministic summary, clearly labelled as AI not configured.
4. Resume to finish, or stop. A later passing cycle does not erase the earlier failure.
5. Export the run as JSON. Simulated runs and evidence are explicitly marked.

## Connect your physical Ubuntu / Yocto board

BoardScope requires a Linux boot ID at `/proc/sys/kernel/random/boot_id`, `/sys` mounted, `sh`, `uname`, and an SSH server with password or key/agent authentication. RISC-V is not an installation dependency: commands execute remotely, and reported architecture comes from `uname -m`. Actual compatibility depends on your board image and SSH configuration.

1. From the same lab PC, establish SSH to your board and verify the host fingerprint through your normal trusted process. BoardScope uses system known_hosts and rejects unknown or changed host keys. It does not silently accept fingerprints.
2. Register the name, OS label, SSH hostname/IP, username and port. Choose Password and enter the board password, or choose SSH key / agent and supply a private key path on the PC or use your SSH agent/default key. Private key contents are not stored in the database. Encrypted keys require an already loaded SSH agent.
3. Set the expected interface to your board's name, such as `eth0` or `end0`; leave it blank to skip this assertion. Optional expected sound-card count must match your hardware. An interface inventory check is not a connectivity test.
4. Verify the connection, then run Linux inventory first.
5. For reboot testing, the account must already have permission for non-interactive `sudo -n /sbin/reboot`. This first version does not modify sudoers and does not support root-only reboot commands or a custom reset command. Confirm authorisation in the run form.
6. Optionally enter a serial device path on the host and baud rate. The host must already have permissions, and another application must not own the serial port. Serial capture is read-only. SSH remains required to control the board.

The runner records reset intent, issues one command, and checks for a changed boot UUID. SSH disconnect does not itself prove a reboot. Rejected or uncertain reset delivery is recorded and observed until the deadline; the runner never blindly sends another reset command. A boot deadline can be exceeded by the current bounded SSH connection/command attempt.

## Custom tests

Register a reviewed POSIX shell script in Test library. Scripts are immutable records with a SHA-256 hash; register a new copy when changing one. Select the script in a custom run on a physical SSH board. Arguments are a JSON array of strings, shell-quoted individually. The dashboard requires explicit authorisation before starting.

Exit code 0 passes; a nonzero code fails; timeout/transport failures are errors. Commands run as the registered SSH account, with its permissions. There is no board-side sandbox. At timeout, BoardScope closes the SSH connection; target processes or children may survive, so scripts must manage cleanup and cancellation. Stop waits for an in-flight custom command's bounded timeout and cannot undo changes. No arbitrary custom code executes inside the simulator.

## Local AI (optional integration)

If you already operate an Ollama server on `127.0.0.1:11434` with a suitable local model installed, set its model name before starting:

```sh
BOARDSCOPE_MODEL=your-installed-model .venv/bin/python -m boardscope
```

“Ask local AI” sends the failed cycle and last passing baseline only to that local endpoint. AI returns observations, hypotheses, suggested next checks and limitations; it does not determine pass/fail, edit scripts, run commands or reset hardware. Without the setting, the product returns a deterministic comparison. Integration parsing/error handling is tested with mocked responses; inference quality and a real model invocation have not been validated in this environment.

## Data and execution

Default data directory: `~/.local/share/boardscope`. Set `BOARDSCOPE_DATA` before launch to select another directory. Data includes board metadata, immutable run configuration snapshots, cycles, logs, events and optional AI investigations. SQLite WAL provides transactional writes and one active run reservation per board. Logs may contain proprietary information; exports remain under your control. No automatic cloud upload exists.

Run the application as your normal user. The CLI binds only to loopback, rejects non-local Host headers and cross-origin requests, and requires a per-process browser session token for API calls. This is a single-user local preview, not LAN hosting, enterprise authentication or a production security guarantee. Only run one server process per data directory. Do not use multiple Uvicorn workers.

On restart, unfinished runs are marked interrupted rather than resumed. Inspect physical board state before creating another run. Pause acts between cycles. Stop cannot reverse a reboot already sent. Five worker threads allow modest concurrent runs, each on a different registered board; scheduling fairness, fleet throughput and fixture safety are future work. Avoid registering the same physical device twice: reservations use the registered board ID, not verified physical identity.

Logs are bounded: SSH output 256 KiB per command, serial capture 2 MiB per run, stored cycle evidence 256 KiB per log field. Run detail displays the most recent 200 events; SQLite retains all events. JSON exports include cycle evidence and displayed events, not all historical events or custom script source.

## Developer verification

```sh
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Optional DOM integration verification requires Node 18+ and a **fresh test data directory**, because it creates demo runs, a script and a simulator board. Run the service with `BOARDSCOPE_DATA` pointing to a new disposable directory in one terminal, then `npm install` and `npm run test:ui` in another. This exercises UI logic against the service using jsdom; it does not verify real browser rendering. `requirements-lock.txt` records the full Python environment used for verification, including development packages.

See `ARCHITECTURE.md` for components and the next implementation milestones. This first dashboard uses bundled vanilla JavaScript/CSS to keep installation simple; it is not yet the planned React app. The backend and host worker currently share one process; the separately installable agent and PostgreSQL deployment are later milestones.

## Shared development

See `CONTRIBUTING.md` for the GitHub workflow and next SSH-password/UART milestones. `AGENTS.md` provides contributor guidance. `.github/workflows/tests.yml` runs backend tests on pushes and pull requests; it has not yet run on GitHub. Code lives in GitHub while the tool and hardware testing remain local.

## Connection page (0.2)

Open **Boards → Connect / settings** on an existing physical board, or register a new board. You can now edit its IP and connection settings without registering another board.

For SSH, select **Password** or **SSH key / agent**. Enter the board username and the matching password/key details, save, and then Verify SSH. Password mode does not try unrelated agent/default keys. Passwords remain in server memory only, disappear after restart, and are never returned by API responses or persisted in board/run snapshots. Blank password fields keep the current session value; use **Forget passwords** to remove both session passwords. The UI clears password inputs when a dialog closes. There is no Remember credentials option yet.

For UART, connect a USB UART adapter matching the board's voltage and leave adapter VCC disconnected when the board is independently powered. Configure the serial device path (for example `/dev/ttyUSB0` or a stable `/dev/serial/by-id/...` path), baud rate, and Linux console username/password if required. Available serial devices are listed in the dialog; manual paths are supported. Close other terminal applications and ensure your host user has access to the device. Save, reopen Connect, and choose **Check saved UART**.

The UART verifier listens for a plain Linux `login:` / `Password:` prompt or an automatic shell ending in `$` or `#`, authenticates if necessary, and executes the fixed read-only Linux identity script. A detected bootloader prompt is rejected without sending credentials. Sending Enter to wake an idle console is disabled by default; explicitly enable it only when the board is already at a Linux login or shell. Unrecognised prompts, coloured/custom shells, two-factor logins and bootloader consoles may require additional board-specific support. Verification closes the port afterward. Linux hosts are the initial UART target.

SSH and UART each show their last verification result, timestamp and error. These are point-in-time checks, not continuous connectivity indicators. Matching boot UUIDs indicate the two checks reached the same running kernel; a mismatch can mean a different board or a reboot between checks and requires investigation. Capability snapshots do not provide permanent hardware identity.

UART-only boards can be registered and verified. **UART reboot/test execution, live console streaming and automatic SSH fallback are not part of this milestone.** SSH test execution and optional read-only serial capture remain as before. Password login does not grant reboot privileges; SSH reboot still requires noninteractive `sudo -n /sbin/reboot` permission.
