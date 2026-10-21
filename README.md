# BoardScope 0.3 — local engineering preview

A runnable first version of the embedded Linux test workbench. The browser dashboard talks to a local Python service. The service runs a simulator or SSH commands on a configured board and saves results on the lab PC. No Docker, board-side package, cloud account or frontend build is required.


## Current test connections (0.3)

| Run connection | Inventory | Software reboot | Reviewed custom scripts |
| --- | --- | --- | --- |
| SSH | Yes | Yes, root/passwordless sudo/password sudo | Yes |
| UART | Yes | Yes, with boot UUID verification and console re-login | Yes, with bounded script transfer |
| SSH → UART fallback | Yes | One reset through the selected connection; read-only recovery may use UART | Choose connection before execution; never replay an uncertain script |

**Setup:** in Connect / settings, configure both profiles for the same physical board. Set **Built-in reboot privileges → Sudo needs a password** for a non-root account that needs a password. Choose either the selected transport's login password or a separate sudo password. Key-based SSH login usually needs a separate sudo password. Root is detected by `id -u` and does not use sudo. All three passwords remain memory-only and are cleared on restart or Forget passwords.

**Run:** choose SSH, UART, or **SSH → UART fallback**, select inventory/reboot/custom, and authorise the requested action. Fallback requires explicitly confirming both profiles target the same board. It tries SSH first; if a connection/readiness read fails it switches to UART and stays there for the remainder of that run. Start a new run to try SSH again. Unknown/changed SSH host keys stop the run; fallback does not bypass host trust. There is no automatic IP discovery or rewrite of SSH host addresses in this release.

SSH failures and UART fallback are recorded in events/cycles and shown in the dashboard. Inventory passing via UART is not proof that networking works. Reboot success requires a changed Linux boot UUID plus the configured inventory assertions. Reset intent is recorded before execution and a dispatched reset is never resent through the other connection.

**Custom scripts:** select a registered, reviewed script and authorise it. UART uploads it in short POSIX printf chunks to an exclusively created mode-0600 file under `/tmp`, runs it once with individually quoted arguments, then removes the file after the script returns. The image must support `sh`, `printf`, `rm`, writable `/tmp`, and a normal serial Linux console. Sudo reboot support also requires `stty` and `sudo` for non-root accounts. UART stdout/stderr are combined; exit 0 passes, other exit codes fail. The configured UART timeout covers script transfer plus execution; choose a longer timeout for large scripts or slow baud rates. Script invocation must fit a 3500-byte terminal command line; oversized argument sets are rejected before script execution.

Custom scripts run as the login account. The built-in sudo settings do **not** feed passwords into arbitrary script prompts; use scripts that run noninteractively with their required permissions. A timeout/disconnect after dispatch has an uncertain result: the run stops even with Continue on failure, does not replay the script, and skips further commands that might interfere with it. Target processes or temporary files may remain; inspect and clean them up before another run. Timeout is not a guarantee of target-side process termination.

UART observes startup passively, does not send bootloader commands, and re-enters the Linux credentials only at recognised login/password prompts. Send Enter is used only for an explicitly confirmed idle Linux console, never during reboot observation. Serial evidence is bounded and collected while UART is reading login, boot or command output; it is not a continuous independent background stream in fallback mode. The UI's check status is a last-check snapshot, not a persistent liveness guarantee.

Physical hard reset/power cycling, live console streaming and manufacturing fixtures remain outside this release. Validate on your real board starting with one inventory cycle, one small harmless custom script, and one authorised reboot before a long run.

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
5. For reboot testing, the account must already have permission for non-interactive `sudo -n /sbin/reboot`. This release does not modify sudoers. It supports direct /sbin/reboot for root and built-in sudo modes, but not a custom reset command. Confirm authorisation in the run form.
6. Optionally enter a serial device path on the host and baud rate. The host must already have permissions, and another application must not own the serial port. Serial capture is read-only. SSH remains required to control the board.

The runner records reset intent, issues one command, and checks for a changed boot UUID. SSH disconnect does not itself prove a reboot. Rejected or uncertain reset delivery is recorded and observed until the deadline; the runner never blindly sends another reset command. A boot deadline can be exceeded by the current bounded SSH connection/command attempt.

## Custom tests

Register a reviewed POSIX shell script in Test library. Scripts are immutable records with a SHA-256 hash; register a new copy when changing one. Select the script in a custom run on a physical board using SSH, UART or authorised fallback. Arguments are a JSON array of strings, shell-quoted individually. The dashboard requires explicit authorisation before starting.

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

UART-only boards can be registered, verified and used for Linux inventory tests. The current 0.3 transport capabilities and limitations are listed above; earlier connection milestones are described below for context. SSH test execution and optional read-only serial capture remain as before. Password login does not grant reboot privileges; SSH reboot still requires noninteractive `sudo -n /sbin/reboot` permission.

## Start Linux inventory through UART (0.2.1)

1. Save and verify the UART connection, including the appropriate Linux console login and optional Send Enter setting.
2. Click **Start test** on the board card. UART boards are included in the run dialog.
3. Select **Test connection → UART** and **Linux inventory**. A board registered primarily for SSH can also select UART when its serial port is configured; saving a UART verification alone does not change the test transport.
4. Set cycles, interval and failure policy, then start. BoardScope logs into the console once and retains that serial session across the run. It reads Linux readiness/boot identity, the expected interface, optional sound-card count and available kernel evidence. No SSH connection is attempted for a UART run.
5. The run history, detail view and JSON plan identify UART as the execution transport. Results remain subject to explicit expected inventory rules; interface presence does not prove network connectivity.

The 0.3 update enables UART reboot/custom-script tests and authorised SSH → UART fallback; see Current test connections above. One session owns reads/writes during a UART run; the SSH run's separate serial capture thread is not started. This milestone does not provide a live serial stream or continuous raw serial transcript. Close other terminal applications before testing. Stop is observed between bounded inventory commands and releases the serial session. Keep Send Enter enabled only when you know the board is at a Linux login/shell.

## Saved connection settings (0.3.1)

Each physical board card displays separate SSH and UART profiles: saved hostname/port/user/authentication or serial port/baud/console login, session-password availability, and the last verification result. Password values are never shown. The default connection is explicitly labelled as the default for new tests; an active run's connection policy and UART fallback are shown separately.

Use **Edit SSH** or **Edit UART** to open that profile's tab. Board/default settings and reboot privileges have their own tabs. Switching tabs does not save changes. **Save settings** submits the complete prefilled configuration, preserving the other profile and its session credentials. Checks use saved settings and are disabled after you edit fields; save and reopen before checking. Changing SSH connection fields or entering a new SSH password invalidates only SSH verification; the corresponding rule applies to UART. Unchanged profiles retain their last-check results.

The Start test dialog shows a read-only **Saved settings this test will use** summary for the selected transport; fallback shows both profiles. These values are snapshotted by the backend when the run is created. Board configuration persists; passwords remain only in the current process and must be entered again after a server restart.

## SSH-first dashboard redesign

The dashboard begins with Connect your board → Run a test → Review the result. Add SSH board opens a short SSH form; password login is the default for new boards, with port, OS and key login under SSH options. Saving a new simple SSH board does not contact hardware. Check SSH on its card is the separate read-only verification action. New simple boards leave interface/sound expectations unset until configured under full board settings.

Board cards show the primary connection, address, credential/last-check state and Check/Edit/Start actions. Full saved profiles, UART and reboot configuration remain under Saved settings & other connections. The alternative full setup is explicitly available from the simple form; switching to it preserves the simple-form inputs in the unsaved draft. Existing configurations and test execution behavior are retained.

Run options are collapsed by default; custom script fields and execution/reboot authorisations appear only for the selected test. The technical activity log is secondary to cycle results. Expanded saved-profile sections survive dashboard polling. The navigation labels are Dashboard, Boards, Tests and Results. This is the local application dashboard, not a public hosted website.


### Results, saved scripts and board removal

Results show the failure stage, exception type, failed expectations and suggested next checks. Guidance is deterministic and does not assert a root cause. Connection/baseline failures appear even if no cycle completed. Historical results receive guidance from existing evidence but explicitly mark the stage as unrecorded. Custom-script results separate stdout, stderr and exit code (UART combines console output). SSH command previews include command, return status and output, excluding stdin; previews retain the last 20 commands with 16 KiB per stream and show truncation. Kernel collection remains the last 180 dmesg lines; UART logs cover the capture period only, not a complete boot archive. JSON exports include the new evidence.

Tests → View / edit loads the saved source, name and timeout. Saving requires review, increments the version and updates its hash. Already queued, active and completed runs retain their original script snapshots. Standard polling and reports still omit source; explicit local script viewing returns it.

Boards → Remove board requires confirmation and rejects removal during active runs. Removal hides the board and forgets its passwords, while retaining the archived board record and past results in SQLite. It is not an erasure of test history.

Boards also displays the actual database path on the PC running the server. Default: `~/.local/share/boardscope/boardscope.sqlite3`, overridden by `BOARDSCOPE_DATA`. IP/hostname, username, key path, UART settings, scripts and results are stored there. SSH/UART/sudo password values live only in server memory and disappear on restart; the dashboard shows availability, never the stored value. Keys remain in their original files.


### Engineer dashboard UI

The light, responsive dashboard includes Overview, Boards, Tests, Results, Assistant and Settings. Overview derives summaries, active tests, failure evidence and recent results from the existing APIs. Boards Reachable means last successful physical-board checks, not continuous monitoring. Passed/Failed Today use finished physical runs in the browser's local calendar day. Simulations remain explicitly labelled. Running tests show the latest recorded event, elapsed wall time and the relevant reported deadline; inventory timeouts are marked unreported.

Check tries saved SSH settings first and configured UART after a connection/readiness failure, using the existing verify endpoints. Host-key/trust failures require review and do not trigger fallback. If SSH is absent, only configured UART is checked. Readiness and test status are separate; green UART fallback does not imply SSH is healthy. Saved check times and SSH errors remain available in More → Saved connection details. New test forms prefer the existing auto transport when both profiles are configured, and still require the existing same-board/fallback authorization; operators can select SSH or UART directly. No backend policy or API contract changes are included.

Assistant is collapsed by default and opens with selected board/run/script-version context. All generation actions are disabled; this UI does not set up a model, generate responses or execute drafts. Existing deterministic evidence comparison remains available when no backend model is configured. Search, filters, selected boards, detail expansion and DOM focus survive polling. Responsive card rows and a full-screen mobile Assistant drawer include focus controls and reduced-motion styling.


### Reference-matched interface refinement

The dashboard now follows the supplied visual reference more closely: a 238px desktop sidebar, larger Overview heading, 94px summary cards, compact board rows with line icons, text-based status indicators, the reference table column order, and a compact running-test/attention/results stack. Secondary board actions live under the labelled three-dot menu; unreachable boards expose Diagnose directly. Connection-check errors remain in board status/details; Needs attention lists test failures. The Assistant retains the reference context card, help cards, compose area and safety footer, but configuration and generation stay disabled. It is still collapsed by default as requested.

The refinement changes frontend markup and styling only. No metrics from the reference image are copied into production. Browser layout checks use synthetic fixtures clearly labelled in their screenshots; physical board behavior remains unchanged.


### Unified execution backend

SSH, UART and the simulator now implement one abstract executor selected by a side-effect-free factory. The dashboard and existing API fields remain compatible. Reviewed custom runs add an execution record containing completion/dispatch certainty, optional exit status, partial output, error classification and evidence completeness. Uncertain actions stop the run and are not replayed. Existing pre-dispatch SSH-first/UART fallback and explicit same-board authorization remain in place.

Serial capture now belongs to the executor, shares the UART port lease, and cannot create a second independent reader. UART custom scripts use volatile shell-memory transfer rather than temporary target script files; no target agent or helper installation is required. This is agentless execution, not zero CPU/memory usage. Scripts must remain noninteractive, within 64000 UTF-8 bytes, and handle their own background children.

Credentials remain outside SQLite. Runs receive a memory-only snapshot that is released after cleanup. Optional board API fields ssh_private_key and ssh_key_passphrase accept a transient private key/passphrase (excluded from responses and persistence); no dashboard key-upload UI is added. Supplying a session private key prevents implicit key-file/agent lookup for that connection. Existing user-owned key paths/SSH-agent authentication still work; those external stores are not made volatile by BoardScope. Restart clears application session secrets, and Forget passwords also clears session key material. No guarantee of Python heap zeroization, remote child-process termination or hard worker termination is made. Supervised worker processes remain the next step for strict isolation from stuck DNS/native I/O.
