import io
import re
import shlex
import time
import uuid
from pathlib import Path
from .credentials import get_secret, sudo_secret, redact
from .transport import ActionUncertain, ActionRejected, ActionNotDispatched, HostTrustError, AuthenticationError, ProtocolError
from .executor import BoardExecutor, ExecutorCapabilities
from .linux_shell import LinuxShell


class Simulator(BoardExecutor):
    transport_name = 'simulator'
    capabilities = ExecutorCapabilities(custom_scripts=False)
    simulated = True

    def __init__(self, board):
        super().__init__(board)
        self.boot_id = str(uuid.uuid4())
        self.cycle = 0

    def inspect(self):
        self.lifecycle='ready'
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

    def command(self,command,timeout=15,stdin_text=None):
        raise RuntimeError('Simulator does not execute shell commands')

    def script(self,source,args,timeout):
        raise RuntimeError('Simulator does not execute user scripts')


class SSHBoard(LinuxShell, BoardExecutor):
    transport_name = 'ssh'
    capabilities = ExecutorCapabilities(serial_capture=True)
    simulated = False

    def __init__(self, board):
        super().__init__(board)
        self._capture=None

    def _connect_timeout(self):
        return self.remaining(2 if self.observation_deadline is not None else 8)

    def open(self):
        super().open()
        if self.board.get('serial_port'):
            from .serial_resource import SerialCapture
            self._capture=SerialCapture(self.board,self.messages)
            self._capture.open()

    def close(self):
        try:
            if self._capture:self._capture.close();self._capture=None
        finally:super().close()

    def take_serial_log(self):
        return self._capture.take() if self._capture else ''

    def client(self):
        import paramiko
        c = paramiko.SSHClient()
        try:c.load_system_host_keys()
        except Exception:
            c.close()
            raise HostTrustError('Cannot read SSH host trust data. Check known_hosts permissions and format.') from None
        c.set_missing_host_key_policy(paramiko.RejectPolicy())
        try:
            password_mode=self.board.get('auth_method','key')=='password'
            password=get_secret(self.board.get('id'), 'ssh_password') if password_mode else None
            if password_mode and not password:
                raise AuthenticationError('SSH password is missing for this session. Open Connect and enter it again.')
            private_key=get_secret(self.board.get('id'),'ssh_private_key') if not password_mode else None
            pkey=None
            if private_key:
                for key_type in (paramiko.Ed25519Key,paramiko.ECDSAKey,paramiko.RSAKey):
                    try:
                        pkey=key_type.from_private_key(io.StringIO(private_key),password=get_secret(self.board.get('id'),'ssh_key_passphrase'))
                        break
                    except (paramiko.SSHException,ValueError):continue
                if pkey is None:raise AuthenticationError('Session private key could not be unlocked or parsed')
            with self.interrupt_guard(c.close):
                c.connect(self.board['host'], port=self.board['port'], username=self.board['username'], pkey=pkey, key_filename=None if password_mode or pkey is not None else self.board.get('key_path') or None, password=password, timeout=self._connect_timeout(), auth_timeout=self._connect_timeout(), banner_timeout=self._connect_timeout(), allow_agent=not password_mode and pkey is None, look_for_keys=not password_mode and pkey is None)
            return c
        except Exception as exc:
            c.close()
            if isinstance(exc, paramiko.AuthenticationException):
                raise AuthenticationError('SSH authentication failed. Check the username and selected password/key.') from None
            if isinstance(exc, paramiko.BadHostKeyException):
                raise HostTrustError('SSH host key changed. Verify the board fingerprint before updating known_hosts.') from None
            if isinstance(exc,paramiko.SSHException) and 'known_hosts' in str(exc):
                raise HostTrustError('SSH host key is not trusted. Verify the fingerprint and add the board to known_hosts.') from None
            raise

    def command(self, command, timeout=15, stdin_text=None):
        previous=self._command_deadline
        self._command_deadline=time.monotonic()+timeout
        c=None;out,err=bytearray(),bytearray();record={'command':command,'exit_code':None}
        self._dispatch='not_sent'
        try:
            self.remaining(timeout)
            c=self.client()
            self.remaining(timeout)
            # The request can reach the server even if channel acknowledgement is lost.
            self._dispatch='possibly_sent'
            with self.interrupt_guard(c.close):
                si,so,se=c.exec_command(command,timeout=self.remaining(timeout))
            channel=so.channel
            channel.settimeout(min(.2,self.remaining(timeout)))
            if stdin_text is not None:
                payload=stdin_text.encode();offset=0
                while offset<len(payload):
                    self.remaining(timeout)
                    if channel.recv_ready():out.extend(channel.recv(8192))
                    if channel.recv_stderr_ready():err.extend(channel.recv_stderr(8192))
                    if len(out)+len(err)>262144:raise RuntimeError('Command output exceeded 256 KiB; evidence incomplete')
                    try:n=channel.send(payload[offset:offset+4096])
                    except TimeoutError:continue
                    if n<=0:raise ConnectionError('SSH channel closed while sending command input')
                    offset+=n
                channel.shutdown_write()
            self._dispatch='accepted'
            while True:
                self.remaining(timeout)
                if channel.recv_ready():out.extend(channel.recv(8192))
                if channel.recv_stderr_ready():err.extend(channel.recv_stderr(8192))
                self._last_output=(out.decode(errors='replace'),err.decode(errors='replace'))
                if len(out)+len(err)>262144:raise RuntimeError('Command output exceeded 256 KiB; evidence incomplete')
                if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
                    code=channel.recv_exit_status()
                    if code<0:raise ProtocolError('SSH channel closed without a remote exit status')
                    record['exit_code']=code
                    return code,out.decode(errors='replace'),err.decode(errors='replace')
                if channel.closed:raise ConnectionError('SSH channel closed before command completion')
                time.sleep(.02)
        except Exception as exc:
            record['error']=str(exc)
            raise
        finally:
            self._last_output=(out.decode(errors='replace'),err.decode(errors='replace'))
            record['truncated']=len(out)>16384 or len(err)>16384
            record.update(stdout=self._last_output[0][:16384],stderr=self._last_output[1][:16384])
            self.command_log=(self.command_log+[redact(record)])[-20:]
            self._command_deadline=previous
            if c:c.close()

    def reset(self):
        try:return self._reset()
        except (ActionUncertain,ActionRejected,ActionNotDispatched,HostTrustError):raise
        except Exception as exc:
            raise ActionNotDispatched('Reboot was not dispatched: '+str(exc)) from None

    def _reset(self):
        code,out,err=self.command('id -u')
        if code:raise ActionRejected('Cannot determine reboot privileges')
        if out.strip()=='0':cmd='/sbin/reboot';password=None
        elif self.board.get('sudo_mode','noninteractive')=='password':
            cmd="sudo -S -p '' /sbin/reboot";password=sudo_secret(self.board,'ssh')+'\n'
        else:cmd='sudo -n /sbin/reboot';password=None
        # Never retry an uncertain reset delivery.
        try:code,out,err=self.command(cmd,timeout=10,stdin_text=password)
        except HostTrustError:raise
        except Exception as exc:
            if self._dispatch=='not_sent':raise ActionNotDispatched('Reboot was not dispatched: '+str(exc)) from None
            raise ActionUncertain('SSH reboot delivery is uncertain: '+str(exc)) from None
        if code:raise ActionRejected('Reboot command rejected: '+err[:500])

    def ready(self):
        return self.inspect()

    def script(self, source, args, timeout):
        try:return self.command('/bin/sh -s -- '+' '.join(shlex.quote(a) for a in args),timeout,source)
        except Exception as exc:
            if self._dispatch=='not_sent':raise
            raise ActionUncertain('SSH script result is uncertain: '+str(exc)+'. Inspect the board; the script was not replayed.') from None


def adapter(board):
    from .factory import create_executor
    return create_executor(board)
