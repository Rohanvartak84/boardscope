"""Bounded UART login and read-only Linux identity verification.

No run execution or automatic reset through UART in this milestone.
"""
import re
import shlex
import threading
import time
import uuid

from .adapters import SSHBoard
from .credentials import get_secret

_GUARD = threading.Lock()
_PORT_LOCKS = {}
_BOOTLOADER = re.compile(r'(?im)(hit any key|press any key|U-Boot>|^\s*=>\s*$|^\s*GRUB[^\n]*>|^\s*Shell>\s*$)')
_LOGIN = re.compile(r'(?im)(?:^|\n)[^\n]*login:\s*$')
_PASSWORD = re.compile(r'(?im)(?:^|\n)password:\s*$')
_SHELL = re.compile(r'(?:^|\n)[^\r\n]{0,160}[#$]\s*$')


class UARTBoard(SSHBoard):
    simulated = False

    def client(self):
        raise RuntimeError('UART does not use an SSH client')

    def command(self, command, timeout=15, stdin_text=None):
        import serial
        port=self.board.get('serial_port')
        if not port:raise RuntimeError('Select a serial port first')
        with _GUARD:lock=_PORT_LOCKS.setdefault(port,threading.Lock())
        if not lock.acquire(blocking=False):raise RuntimeError('Serial port busy in BoardScope')
        handle=None
        try:
            try:
                handle=serial.Serial(port,self.board.get('baud',115200),timeout=.1,write_timeout=2,exclusive=True)
            except (OSError,serial.SerialException):
                raise RuntimeError('Cannot open serial port. Check the device path, host permissions and other terminal applications.') from None
            self._login(handle,timeout)
            script=stdin_text if stdin_text is not None else command
            marker='BS_'+uuid.uuid4().hex
            # Single-line command even for a multiline script, using POSIX printf
            # to deliver a quoted script to a child shell.
            script=script.replace('\\','\\\\').replace('\n','\\n').replace('\r','\\r')
            line="printf '%s\\n' "+shlex.quote(marker+'_BEGIN')+"; printf '%b' "+shlex.quote(script)+" | sh; bs_rc=$?; printf '\\n%s:%s\\n' "+shlex.quote(marker+'_END')+' "$bs_rc"\n'
            handle.write(line.encode());handle.flush()
            text='';deadline=time.monotonic()+timeout
            start=re.compile(r'(?:^|\n)'+marker+r'_BEGIN\r?\n')
            end=re.compile(r'(?:^|\n)'+marker+r'_END:(\d+)\r?\n')
            while time.monotonic()<deadline:
                text+=handle.read(4096).decode(errors='replace')
                if len(text)>262144:raise RuntimeError('UART output exceeded 256 KiB')
                first=start.search(text);last=end.search(text)
                if first and last and last.start()>=first.end():
                    return int(last.group(1)),text[first.end():last.start()].replace('\r',''),''
            raise TimeoutError('Linux shell command did not finish before the UART deadline')
        finally:
            if handle:handle.close()
            lock.release()

    def _login(self, handle, timeout):
        text='';deadline=time.monotonic()+timeout;sent_user=False;sent_password=False;woke=False;opened=time.monotonic()
        while time.monotonic()<deadline:
            text+=handle.read(4096).decode(errors='replace');text=text[-16384:]
            if _BOOTLOADER.search(text):
                raise RuntimeError('Bootloader prompt detected. Wait for Linux; BoardScope did not send login credentials.')
            if re.search(r'(?i)(login incorrect|authentication failure)',text):
                raise RuntimeError('UART login rejected. Check the Linux username/password.')
            if _SHELL.search(text):return
            if _LOGIN.search(text) and not sent_user:
                username=self.board.get('uart_username','')
                if not username:raise RuntimeError('Linux login prompt detected. Enter a UART username in the connection settings.')
                handle.write((username+'\n').encode());handle.flush();text='';sent_user=True
            elif _PASSWORD.search(text) and not sent_password:
                password=get_secret(self.board.get('id'),'uart_password')
                if not password:raise RuntimeError('UART password is missing for this session. Open Connect and enter it again.')
                handle.write((password+'\n').encode());handle.flush();text='';sent_password=True
            elif not text.strip() and not woke and time.monotonic()-opened>1 and self.board.get('uart_wake',False):
                handle.write(b'\n');handle.flush();woke=True
        raise TimeoutError('No Linux shell detected on UART. Check baud rate, console configuration and login settings. If Linux is already idle, enable the explicit Send Enter option.')

    def inspect(self):
        result=super().inspect()
        result['transport']='uart'
        return result

    def reset(self):
        raise RuntimeError('UART reset execution is not implemented in this connection milestone')

    def script(self,*args,**kwargs):
        raise RuntimeError('Custom script execution through UART is not implemented')
