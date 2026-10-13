"""Evidence-based guidance; suggestions do not assert a root cause."""
from .credentials import redact


def diagnostic(stage, kind, message, checks=None):
    text=message.lower()
    steps=['Review the raw evidence below and compare the last passing cycle.']
    if 'auth' in text or 'password' in text:
        steps=['Check the saved username and authentication method under Boards → Edit connection.', 'Re-enter the session password after restarting BoardScope; verify login from the lab PC.']
    elif 'host key' in text or 'known_hosts' in text:
        steps=['Verify the board fingerprint independently before changing the lab PC known_hosts entry.', 'Check that the saved address still belongs to the intended board.']
    elif 'sudo' in text or 'privilege' in text or 'reboot command rejected' in text:
        steps=['Check Boards → Reboot settings: root/passwordless sudo or password source.', 'Verify reboot permission for this user; do not repeat a reset with uncertain delivery.']
    elif 'serial' in text or 'uart' in text or 'linux shell' in text:
        steps=['Check the UART device path, permissions, cable, baud rate and console login on the lab PC.', 'Check that another terminal is not using the serial port; review captured serial output.']
    elif 'boot' in text or 'deadline' in text or 'timed out' in text:
        steps=['Review UART boot output to see whether boot stalled or Linux started without networking.', 'Check the saved board address and SSH service after boot; compare the boot deadline to normal startup time.']
    elif 'connect' in text or 'refused' in text or 'unreachable' in text:
        steps=['From the lab PC, check the saved IP/hostname and port, board power and network link.', 'Check that sshd is running on the board and use a DHCP reservation to keep its address stable.']
    failed=[c for c in (checks or []) if c['outcome']=='fail']
    if failed:
        if stage=='Execute custom script':
            steps=['Review script stdout/stderr and the nonzero exit code below.', 'Open Tests → View / edit and check the script, arguments and device paths against the board image.']
        else:
            steps=['Compare each expected value with the observed inventory below.', 'Check saved board expectations; if correct, review device enumeration, driver probe messages and kernel configuration.']
    if kind=='ActionUncertain':steps.insert(0,'Inspect the physical board before another action. The previous action may have executed; it was not replayed.')
    return redact({'stage':stage,'error_type':kind,'message':message,'failed_checks':failed,'next_checks':steps,'limitation':'Suggested checks, not a confirmed root cause.'})
