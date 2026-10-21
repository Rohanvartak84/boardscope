"""Transport-neutral execution contract; no handles or credentials in results."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from contextlib import contextmanager
import threading
import math
import time
from typing import Callable

from .credentials import redact
from .transport import ActionUncertain, ActionRejected, ActionNotDispatched, HostTrustError, AuthenticationError, ResourceBusy, ResourceError, ProtocolError


@dataclass(frozen=True)
class ExecutorCapabilities:
    separate_stderr: bool = True
    custom_scripts: bool = True
    serial_capture: bool = False
    cancellation: str = 'bounded_observation'


@dataclass(frozen=True)
class ExecutionRequest:
    source: str = field(repr=False)
    args: tuple[str, ...] = field(default_factory=tuple, repr=False)
    timeout_s: float = 15

    def __post_init__(self):
        if '\x00' in self.source or any('\x00' in arg for arg in self.args):
            raise ValueError('POSIX shell input cannot contain NUL bytes')
        if len(self.source.encode())>64000:raise ValueError('Script exceeds 64000 UTF-8 bytes')
        if not math.isfinite(self.timeout_s) or self.timeout_s <= 0:
            raise ValueError('Execution timeout must be finite and positive')


@dataclass(frozen=True)
class ExecutionResult:
    transport: str
    completion: str
    dispatch: str
    exit_code: int | None = None
    stdout: str = ''
    stderr: str | None = None
    combined: bool = False
    duration_ms: int = 0
    error_type: str | None = None
    error: str | None = None
    error_class: str | None = None
    remote_may_be_running: bool = False
    evidence_complete: bool = True

    def public(self):
        return redact(asdict(self))

    def raise_for_error(self):
        if self.error is None:
            return
        errors={'HostTrustError':HostTrustError,'ActionRejected':ActionRejected,
                'AuthenticationError':AuthenticationError,'ResourceBusy':ResourceBusy,
                'ResourceError':ResourceError,'ProtocolError':ProtocolError,'TimeoutError':TimeoutError}
        cls=ActionUncertain if self.completion=='uncertain' else InterruptedError if self.completion=='cancelled' else errors.get(self.error_type,RuntimeError)
        raise cls(self.error)


def classify_error(exc):
    if isinstance(exc, HostTrustError):return 'identity'
    if isinstance(exc, AuthenticationError):return 'authentication'
    if isinstance(exc, ResourceError):return 'resource'
    if isinstance(exc, ActionUncertain):return 'uncertain_execution'
    if isinstance(exc, ActionRejected):return 'action_rejected'
    if isinstance(exc,ActionNotDispatched):return 'not_dispatched'
    if isinstance(exc, InterruptedError):return 'cancelled'
    if isinstance(exc, TimeoutError):return 'deadline'
    if isinstance(exc, ProtocolError):return 'protocol'
    if isinstance(exc, (ConnectionError, OSError)):return 'transport'
    return 'execution'


class BoardExecutor(ABC):
    """One lifecycle for the runner; transport details stay in implementations.

    command/script remain tuple-returning compatibility primitives for internal
    shell operations. Reviewed workloads use execute for a normalized record.
    """
    simulated = False
    transport_name = 'unknown'
    observation_deadline = None
    capabilities = ExecutorCapabilities()

    def __init__(self, board):
        self.board = board
        self.cancelled: Callable[[], bool] = lambda: False
        self.observation_deadline = None
        self._operation_deadline = None
        self._command_deadline = None
        self.command_log = []
        self.messages = []
        self.lifecycle = 'closed'
        self._dispatch = 'not_sent'
        self._last_output = ('', '')
        self._action_uncertain=False

    @property
    def active_transport(self):
        return self.transport_name

    def configure(self, cancelled):
        self.cancelled = cancelled

    def remaining(self, timeout):
        self.check_cancelled()
        deadlines=[x for x in (self.observation_deadline,self._operation_deadline,self._command_deadline) if x is not None]
        if deadlines:timeout=min(timeout,min(deadlines)-time.monotonic())
        if timeout <= 0:raise TimeoutError('Execution/readiness deadline reached')
        return timeout

    def check_cancelled(self):
        if self.cancelled():raise InterruptedError('Operator stopped observation; target termination is not confirmed')

    @contextmanager
    def interrupt_guard(self,close):
        """Close sockets/channels if a library waits for an acknowledgement.

        Cooperative containment, not an OS-level hard-kill guarantee.
        """
        stop=threading.Event();problem=[]
        def watch():
            while not stop.wait(.05):
                try:self.remaining(1)
                except Exception as exc:
                    problem.append(exc)
                    try:close()
                    except Exception:pass
                    return
        watcher=threading.Thread(target=watch,daemon=True);watcher.start()
        try:yield
        finally:
            stop.set();watcher.join(timeout=.2)
            if problem:raise problem[0]

    def open(self):
        self.check_cancelled()
        self.lifecycle = 'opening'

    def close(self):
        self.lifecycle = 'closed'

    @abstractmethod
    def inspect(self):...

    def ready(self):
        return self.inspect()

    @abstractmethod
    def command(self, command, timeout=15, stdin_text=None):...

    @abstractmethod
    def reset(self):...

    @abstractmethod
    def script(self, source, args, timeout):...

    @abstractmethod
    def evidence(self):...

    def execute(self, request: ExecutionRequest):
        if self._action_uncertain:
            return ExecutionResult(self.active_transport,'uncertain','possibly_sent',error_type='ActionUncertain',error='Previous action is unresolved; no command was replayed',error_class='uncertain_execution',remote_may_be_running=True,evidence_complete=False)
        tick=time.monotonic()
        self._operation_deadline=tick+request.timeout_s
        self._dispatch='not_sent';self._last_output=('','')
        self.lifecycle='executing'
        completed=False
        try:
            self.check_cancelled()
            code,out,err=self.script(request.source,list(request.args),self.remaining(request.timeout_s))
            if code < 0:raise ProtocolError('No reliable remote exit status was received')
            completed=True
            return ExecutionResult(self.active_transport,'completed','accepted',code,
                redact(out),None if not self.capabilities.separate_stderr else redact(err),
                not self.capabilities.separate_stderr,round((time.monotonic()-tick)*1000))
        except Exception as exc:
            uncertain=isinstance(exc,ActionUncertain) or self._dispatch!='not_sent'
            if uncertain:
                self._action_uncertain=True
                if self._dispatch=='not_sent':self._dispatch='possibly_sent'
            completion='uncertain' if uncertain else 'cancelled' if isinstance(exc,InterruptedError) else 'error'
            out,err=self._last_output
            return ExecutionResult(self.active_transport,completion,self._dispatch,
                stdout=redact(out),stderr=None if not self.capabilities.separate_stderr else redact(err),
                combined=not self.capabilities.separate_stderr,duration_ms=round((time.monotonic()-tick)*1000),
                error_type=type(exc).__name__,error=redact(str(exc)),error_class=classify_error(exc),
                remote_may_be_running=uncertain,evidence_complete=False)
        finally:
            self._operation_deadline=None
            self.lifecycle='uncertain' if self._action_uncertain else 'ready' if completed else 'disconnected'

    def begin_cycle(self):
        self.command_log=[]
        self.take_serial_log()

    def take_serial_log(self):return ''

    def drain_events(self):
        notes=self.messages;self.messages=[];return notes

    def execution_log(self):return redact(list(self.command_log))
