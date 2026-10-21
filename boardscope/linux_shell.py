"""Read-only Linux shell operations shared by SSH and UART."""
import re


class LinuxShell:
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
        self.lifecycle='ready'
        return {'boot_id': boot, 'kernel': fields.get('KERNEL'), 'machine': fields.get('MACHINE'), 'os': fields.get('OS'), 'interfaces': fields.get('INTERFACES', '').split(), 'sound_cards': int(fields.get('SOUND', '0')), 'commands': fields.get('COMMANDS', '').split(), 'simulated': False}

    def evidence(self):
        try:
            code, out, err = self.command('dmesg | tail -n 180')
            return out if code == 0 and out else 'Kernel evidence unavailable: ' + err
        except Exception as e:
            return 'Kernel evidence unavailable: ' + str(e)

