"""Single-owner UART shell, bounded script transfer and reboot observation."""
import codecs
import re
import shlex
import threading
import time
import uuid

from .adapters import SSHBoard
from .credentials import get_secret, sudo_secret, redact
from .transport import ActionUncertain, ActionRejected

_GUARD=threading.Lock()
_PORT_LOCKS={}
_BOOTLOADER=re.compile(r'(?im)(hit any key|press any key|U-Boot>|^\s*=>\s*$|^\s*GRUB[^\n]*>|^\s*Shell>\s*$)')
_LOGIN=re.compile(r'(?im)(?:^|\n)[^\n]*login:\s*$')
_PASSWORD=re.compile(r'(?im)(?:^|\n)password:\s*$')
_SHELL=re.compile(r'(?:^|\n)[^\r\n]{0,160}[#$]\s*$')
_ANSI=re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')


class UARTBoard(SSHBoard):
    simulated=False

    def __init__(self,board):
        super().__init__(board)
        self._handle=None;self._lock=None
        self._blocked=False;self._reboot_pending=False;self._reboot_text='';self._boot_shell_ready=False
        self._before_boot=None;self._log='';self.messages=[]
        self.observation_deadline=None
        self.cancelled=lambda:False
        self._decoder=codecs.getincrementaldecoder('utf-8')(errors='replace')

    def _budget(self,timeout):
        if self.observation_deadline is not None:
            timeout=min(timeout,self.observation_deadline-time.monotonic())
        if timeout<=0:raise TimeoutError('Boot observation deadline reached')
        return timeout

    def _record(self,text):
        room=262144-len(self._log)
        if room>0:self._log+=text[:room]

    def _read(self,capture=False):
        if self.cancelled():raise InterruptedError('Operator stopped serial observation')
        text=self._decoder.decode(self._handle.read(4096))
        if capture:self._record(text)
        return text

    def open(self,timeout=15):
        import serial
        if self._blocked:raise ActionUncertain('UART command state is uncertain. Inspect the board manually before creating a new run.')
        if self._handle is not None:return
        port=self.board.get('serial_port')
        if not port:raise RuntimeError('Select a serial port first')
        with _GUARD:lock=_PORT_LOCKS.setdefault(port,threading.Lock())
        if not lock.acquire(blocking=False):raise RuntimeError('Serial port busy in BoardScope')
        self._lock=lock
        try:
            try:self._handle=serial.Serial(port,self.board.get('baud',115200),timeout=.1,write_timeout=2,exclusive=True)
            except (OSError,serial.SerialException):
                raise RuntimeError('Cannot open serial port. Check the device path, host permissions and other terminal applications.') from None
            self._decoder=codecs.getincrementaldecoder('utf-8')(errors='replace')
            self._login(self._handle,self._budget(timeout),allow_boot=self._reboot_pending)
            self._boot_shell_ready=self._reboot_pending
        except Exception:self.close();raise

    def close(self):
        try:
            if self._handle is not None:self._handle.close()
        finally:
            self._handle=None
            if self._lock is not None:self._lock.release();self._lock=None

    def _execute(self,script,timeout=15,action=False):
        if self._blocked:raise ActionUncertain('UART action result is uncertain; subsequent commands are blocked')
        temporary=self._handle is None
        if temporary:self.open(timeout)
        marker='BS_'+uuid.uuid4().hex
        encoded=script.replace('\\','\\\\').replace('\n','\\n').replace('\r','\\r')
        line="printf '%s\\n' "+shlex.quote(marker+'_BEGIN')+"; printf '%b' "+shlex.quote(encoded)+" | sh; bs_rc=$?; printf '\\n%s:%s\\n' "+shlex.quote(marker+'_END')+' "$bs_rc"\n'
        if len(line.encode())>3500:
            if temporary:self.close()
            raise RuntimeError('UART command line too long; use registered custom scripts for larger code')
        sent=False;text='';start=None
        try:
            if self.cancelled():raise InterruptedError('Stopped before serial command')
            sent=True;self._handle.write(line.encode());self._handle.flush()
            text='';deadline=time.monotonic()+self._budget(timeout)
            start=re.compile(r'(?:^|\n)'+marker+r'_BEGIN\r?\n')
            end=re.compile(r'(?:^|\n)'+marker+r'_END:(\d+)\r?\n')
            while time.monotonic()<deadline:
                text+=self._read()
                if len(text)>262144:raise RuntimeError('UART output exceeded 256 KiB')
                first=start.search(text);last=end.search(text)
                if first and last and last.start()>=first.end():
                    out=text[first.end():last.start()].replace('\r','')
                    self._record(out+'\n')
                    return int(last.group(1)),out,''
            raise TimeoutError('UART command deadline reached')
        except Exception as exc:
            first=start.search(text) if start is not None else None
            if first:self._record(text[first.end():])
            self.close()
            if action and sent:
                self._blocked=True
                raise ActionUncertain('UART script result is uncertain: '+str(exc)+'. It was not replayed; inspect target processes and temporary files.') from None
            raise
        finally:
            if temporary:self.close()

    def command(self,command,timeout=15,stdin_text=None):
        return self._execute(stdin_text if stdin_text is not None else command,timeout)

    def _login(self,handle,timeout,allow_boot=False,initial=''):
        text=initial;deadline=time.monotonic()+timeout;sent_user=False;sent_password=False;woke=False;opened=time.monotonic();prefetched=bool(initial)
        while time.monotonic()<deadline:
            # _login is also tested with a minimal serial object.
            if prefetched:prefetched=False
            elif handle is self._handle:text+=self._read(capture=True)
            else:text+=handle.read(4096).decode(errors='replace')
            text=_ANSI.sub('',text[-16384:])
            bootloader=bool(_BOOTLOADER.search(text))
            if bootloader and not allow_boot:
                raise RuntimeError('Bootloader prompt detected. Wait for Linux; BoardScope did not send login credentials.')
            if re.search(r'(?i)(login incorrect|authentication failure)',text):raise RuntimeError('UART login rejected. Check the Linux username/password.')
            if _SHELL.search(text) and not re.search(r'(?im)^\s*(=>|U-Boot>|Shell>)',text.splitlines()[-1] if text.splitlines() else ''):return
            if _LOGIN.search(text) and not sent_user:
                username=self.board.get('uart_username','')
                if not username:raise RuntimeError('Linux login prompt detected. Enter a UART username in the connection settings.')
                handle.write((username+'\n').encode());handle.flush();text='';sent_user=True
            elif _PASSWORD.search(text) and sent_user and not sent_password:
                password=get_secret(self.board.get('id'),'uart_password')
                if not password:raise RuntimeError('UART password is missing for this session. Open Connect and enter it again.')
                handle.write((password+'\n').encode());handle.flush();text='';sent_password=True
            elif not allow_boot and not text.strip() and not woke and time.monotonic()-opened>1 and self.board.get('uart_wake',False):
                handle.write(b'\n');handle.flush();woke=True
        raise TimeoutError('No Linux shell detected on UART. Check baud rate, console configuration and login settings. If Linux is already idle, enable the explicit Send Enter option.')

    def inspect(self):
        result=super().inspect();result['transport']='uart';return result

    def ready(self):
        if self._reboot_pending:
            if self._handle is None:self.open(self._budget(6))
            elif not self._boot_shell_ready:
                initial=self._reboot_text;self._reboot_text=''
                self._login(self._handle,self._budget(6),allow_boot=True,initial=initial)
            self._boot_shell_ready=False
            result=self.inspect()
            if result['boot_id']!=self._before_boot:self._reboot_pending=False
            return result
        return self.inspect()

    def reset(self):
        self.open()
        self._before_boot=self.inspect()['boot_id']
        code,out,err=self.command('id -u')
        if code:raise ActionRejected('Cannot determine reboot privileges')
        root=out.strip()=='0';password=None
        prompt='BS_'+uuid.uuid4().hex+'_SUDO'
        if root:cmd='/sbin/reboot'
        elif self.board.get('sudo_mode','noninteractive')=='password':
            password=sudo_secret(self.board,'uart')
            cmd='sudo -S -p '+shlex.quote(prompt)+' /sbin/reboot'
        else:cmd='sudo -n /sbin/reboot'
        marker='BS_'+uuid.uuid4().hex+'_RESET_RC'
        # Password is written only in response to this unique sudo prompt and
        # never embedded in shell command text. Abort if echo cannot be disabled.
        line='if stty -echo; then printf "\\n"; '+cmd+'; bs_rc=$?; stty echo; else bs_rc=125; fi; printf "\\n%s:%s\\n" '+shlex.quote(marker)+' "$bs_rc"\n'
        self._handle.reset_input_buffer()
        if self.cancelled():raise InterruptedError('Stopped before reboot dispatch')
        self._reboot_pending=True;self._reboot_text='';self._boot_shell_ready=False
        try:
            self._handle.write(line.encode());self._handle.flush()
            deadline=time.monotonic()+self._budget(3);text='';sent_password=False;interrupted_sudo=False
            while time.monotonic()<deadline:
                text+=self._read(capture=True);self._reboot_text=text[-16384:]
                rejected=re.search(r'(?:^|\n)'+marker+r':(\d+)\r?\n',text)
                if rejected:
                    if int(rejected.group(1)):
                        self._reboot_pending=False
                        raise ActionRejected('UART reboot rejected. Check sudo credentials and permission.')
                    return
                if password and not sent_password and re.search(r'(?:^|\n)'+prompt+r'\s*$',text):
                    self._handle.write((password+'\n').encode());self._handle.flush();sent_password=True;text=''
                if 'Sorry, try again' in text and not interrupted_sudo:
                    self._handle.write(b'\x03');self._handle.flush();interrupted_sudo=True
            if interrupted_sudo:
                self._blocked=True
                raise ActionUncertain('Sudo rejected the password and console cleanup is unconfirmed; inspect the console manually')
            if password and not sent_password:
                raise ActionUncertain('No expected sudo prompt observed. Reboot was not retried.')
            # Reset may disconnect before a return code; readiness/boot ID is
            # the success criterion. Do not send any wake keys during startup.
        except ActionRejected:raise
        except Exception as exc:
            raise ActionUncertain('UART reboot delivery is uncertain: '+str(exc)+'. Observing only; reset will not be replayed.') from None

    def script(self,source,args,timeout):
        self.open()
        deadline=time.monotonic()+timeout
        path='/tmp/boardscope-'+uuid.uuid4().hex+'.sh'
        def execute(code,action=False):
            remaining=deadline-time.monotonic()
            if remaining<=0:raise TimeoutError('UART script transfer/execution deadline reached')
            rc,out,err=self._execute(code,remaining,action=action)
            if rc and not action:raise RuntimeError('UART script transfer failed: '+out[:500])
            return rc,out,err
        execute('umask 077; (set -C; : > '+shlex.quote(path)+')')
        try:
            data=source.encode('utf-8')
            for offset in range(0,len(data),256):
                encoded=''.join('\\0%03o'%b for b in data[offset:offset+256])
                execute("printf '%b' "+shlex.quote(encoded)+' >> '+shlex.quote(path))
            run='sh '+shlex.quote(path)+' '+' '.join(shlex.quote(a) for a in args)
            return execute(run+'; bs_script_rc=$?; rm -f '+shlex.quote(path)+'; exit "$bs_script_rc"',action=True)
        except ActionUncertain:raise
        except Exception:
            # Only clean up when no arbitrary script was dispatched.
            if not self._blocked:
                try:self._execute('rm -f '+shlex.quote(path),2)
                except Exception:pass
            raise

    def evidence(self):
        if self._blocked:return 'UART action result uncertain. Evidence commands skipped to avoid interfering with target processes.'
        if self._reboot_pending:return 'Linux readiness not confirmed; inspect the saved UART boot log.'
        return super().evidence()

    def take_serial_log(self):
        result=redact(self._log);self._log='';return result

    def drain_events(self):result=self.messages;self.messages=[];return result
