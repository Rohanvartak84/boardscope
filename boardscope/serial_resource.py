"""Shared serial ownership for command sessions and passive SSH evidence capture."""
import os
import threading
from .credentials import redact
from .transport import ResourceBusy

_GUARD=threading.Lock()
_PORT_LOCKS={}


def acquire_port(path):
    key=os.path.realpath(path)
    with _GUARD:lock=_PORT_LOCKS.setdefault(key,threading.Lock())
    if not lock.acquire(blocking=False):raise ResourceBusy('Serial port busy in BoardScope; close the owning session first')
    return lock


class SerialCapture:
    """Optional, passive, bounded capture. Never sends login or wake bytes."""
    def __init__(self,board,messages):
        self.board=board;self.messages=messages;self.handle=None;self.lease=None
        self.stop=threading.Event();self.thread=None;self.data='';self.guard=threading.Lock()

    def open(self):
        import serial
        try:
            self.lease=acquire_port(self.board['serial_port'])
            self.handle=serial.Serial(self.board['serial_port'],self.board.get('baud',115200),
                timeout=.1,write_timeout=1,exclusive=True if os.name=='posix' else None)
        except Exception as exc:
            self.close()
            self.messages.append({'kind':'evidence','level':'warning','message':'Optional serial capture unavailable: '+redact(str(exc))})
            return
        self.thread=threading.Thread(target=self._read,daemon=True);self.thread.start()

    def _read(self):
        total=0
        try:
            while not self.stop.is_set():
                raw=self.handle.read(4096)
                if not raw:continue
                total+=len(raw)
                text=redact(raw.decode(errors='replace'))
                with self.guard:self.data+=text
                if total>=2*1024*1024:
                    self.messages.append({'kind':'evidence','level':'warning','message':'Serial capture limit reached (2 MiB); evidence incomplete'})
                    return
        except Exception as exc:
            if not self.stop.is_set():self.messages.append({'kind':'evidence','level':'warning','message':'Serial capture interrupted: '+redact(str(exc))})

    def take(self):
        with self.guard:result=self.data;self.data='';return result

    def close(self):
        self.stop.set()
        if self.thread:self.thread.join(timeout=.5)
        try:
            if self.handle:self.handle.close()
        finally:
            self.handle=None
            if self.lease:self.lease.release();self.lease=None
