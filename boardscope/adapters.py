import re
import shlex
import time
import uuid
from pathlib import Path


class Simulator:
    simulated = True

    def __init__(self, board):
        self.board = board
        self.boot_id = str(uuid.uuid4())
        self.cycle = 0

    def inspect(self):
        return {"boot_id": self.boot_id, "os": self.board['environment'], "kernel": "simulated-riscv64", "machine": "riscv64", "interfaces": ["end0"], "sound_cards": 3, "commands": ["sh", "ip"], "simulated": True}

    def reset(self):
        self.cycle += 1
        time.sleep(.15)
        self.boot_id = str(uuid.uuid4())

    def ready(self):
        data = self.inspect()
        if self.cycle == self.board.get('failure_cycle', 3):
            scenario = self.board.get('scenario', 'missing_device')
            if scenario == 'boot_timeout':
                raise TimeoutError('Simulated boot readiness timeout')
            if scenario == 'missing_device':
                data['sound_cards'] = 2
        return data

    def evidence(self):
        if self.cycle == self.board.get('failure_cycle', 3) and self.board.get('scenario') == 'missing_device':
            return 'SIMULATED kernel log\n[4.12] audio-demo: probe failed (-110)\nThis is synthetic evidence, not a real board log.'
        return 'SIMULATED kernel log\n[3.4] platform devices initialised\nSynthetic evidence; no physical board contacted.'


class SSHBoard:
    simulated = False

    def __init__(self, board):
        self.board = board

    def client(self):
        import paramiko
        c = paramiko.SSHClient()
        c.load_system_host_keys()
        c.set_missing_host_key_policy(paramiko.RejectPolicy())
        try:
            c.connect(self.board['host'], port=self.board['port'], username=self.board['username'], key_filename=self.board.get('key_path') or None, timeout=8, auth_timeout=8, banner_timeout=8, allow_agent=True, look_for_keys=True)
            return c
        except Exception:
            c.close()
            raise

    def command(self, command, timeout=15, stdin_text=None):
        c = self.client()
        try:
            si, so, se = c.exec_command(command, timeout=timeout)
            if stdin_text is not None:
                si.write(stdin_text)
                si.flush()
                si.channel.shutdown_write()
            channel = so.channel
            out, err = bytearray(), bytearray()
            deadline = time.monotonic() + timeout
            while True:
                if channel.recv_ready():
                    out.extend(channel.recv(8192))
                if channel.recv_stderr_ready():
                    err.extend(channel.recv_stderr(8192))
                if len(out) + len(err) > 262144:
                    raise RuntimeError('Command output exceeded 256 KiB; SSH channel closed')
                if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError('SSH command timed out')
                time.sleep(.02)
            return channel.recv_exit_status(), out.decode(errors='replace'), err.decode(errors='replace')
        finally:
            c.close()

    def inspect(self):
        code, out, err = self.command("sh -s", stdin_text="""set -eu
printf 'BOOT='; cat /proc/sys/kernel/random/boot_id
printf 'KERNEL='; uname -r
printf 'MACHINE='; uname -m
printf 'OS='; if [ -r /etc/os-release ]; then . /etc/os-release; printf '%s\\n' "${PRETTY_NAME:-unknown}"; else printf 'unknown\\n'; fi
printf 'INTERFACES='; for p in /sys/class/net/*; do [ -e "$p" ] && printf '%s ' "${p##*/}"; done; printf '\\n'
printf 'SOUND='; n=0; for p in /sys/class/sound/card[0-9]*; do [ -e "$p" ] && n=$((n+1)); done; printf '%s\\n' "$n"
printf 'COMMANDS='; for c in sh ip dmesg reboot; do command -v "$c" >/dev/null 2>&1 && printf '%s ' "$c"; done; printf '\\n'
""")
        if code:
            raise RuntimeError('Capability check failed: ' + err[:500])
        fields = dict(line.split('=', 1) for line in out.splitlines() if '=' in line)
        boot = fields.get('BOOT', '')
        if not re.fullmatch(r'[0-9a-fA-F-]{36}', boot):
            raise RuntimeError('A valid Linux boot ID is required')
        return {'boot_id': boot, 'kernel': fields.get('KERNEL'), 'machine': fields.get('MACHINE'), 'os': fields.get('OS'), 'interfaces': fields.get('INTERFACES', '').split(), 'sound_cards': int(fields.get('SOUND', '0')), 'commands': fields.get('COMMANDS', '').split(), 'simulated': False}

    def reset(self):
        # Execution intent is journalled by the runner before this one command.
        code, out, err = self.command('sudo -n /sbin/reboot', timeout=10)
        if code:
            raise RuntimeError('Reboot command rejected: ' + err[:500])

    def ready(self):
        return self.inspect()

    def evidence(self):
        try:
            code, out, err = self.command('dmesg | tail -n 180')
            return out if code == 0 and out else 'Kernel evidence unavailable: ' + err
        except Exception as e:
            return 'Kernel evidence unavailable: ' + str(e)

    def script(self, source, args, timeout):
        return self.command('/bin/sh -s -- ' + ' '.join(shlex.quote(a) for a in args), timeout, source)


def adapter(board):
    return Simulator(board) if board['mode'] == 'simulator' else SSHBoard(board)
