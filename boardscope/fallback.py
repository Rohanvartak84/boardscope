"""Choose a transport before actions. Never replay a dispatched action."""
from .adapters import SSHBoard
from .uart import UARTBoard
from .credentials import redact
from .executor import BoardExecutor
from .transport import ActionUncertain, ActionRejected, ActionNotDispatched, HostTrustError


class FallbackBoard(BoardExecutor):
    transport_name='auto'
    simulated=False

    def __init__(self,board):
        super().__init__(board)
        self.ssh=SSHBoard(dict(board,mode='ssh'))
        self.uart=UARTBoard(dict(board,mode='uart'))
        self.active=None
        self.messages=[]
        self.observation_deadline=None
        self._last_boot=None

    @property
    def capabilities(self):
        return (self.uart if self.active=='uart' else self.ssh).capabilities

    @property
    def active_transport(self):return self.active or 'auto'

    def configure(self,cancelled):
        super().configure(cancelled)
        self.ssh.cancelled=cancelled;self.uart.cancelled=cancelled

    def begin_cycle(self):
        self.ssh.command_log=[];self.uart.command_log=[]
        self.take_serial_log()

    def execution_log(self):return self.ssh.execution_log()+self.uart.execution_log()

    def command(self,command,timeout=15,stdin_text=None):
        if self.active is None:self.inspect()
        target=self.uart if self.active=='uart' else self.ssh
        return target.command(command,timeout,stdin_text)

    def _choose(self):
        self.remaining(15)
        self.ssh._operation_deadline=self._operation_deadline
        self.uart._operation_deadline=self._operation_deadline
        # Once a run falls back, retain UART rather than repeatedly delaying it
        # with the same unreachable SSH address. A new run tries SSH again.
        if self.active=='uart':return self.uart
        self.ssh.observation_deadline=self.observation_deadline
        try:
            result=self.ssh.inspect()
            self.active='ssh';self._last_boot=result['boot_id']
            return self.ssh,result
        except (HostTrustError,InterruptedError,ActionUncertain):
            raise
        except Exception as exc:
            self.messages.append({'kind':'connection_fallback','level':'warning','message':'SSH connection/readiness failed: '+redact(str(exc))+'; switching to UART. This connection failure is retained.'})
            self.uart.observation_deadline=self.observation_deadline
            self.uart.open()
            self.active='uart'
            return self.uart

    def inspect(self):
        chosen=self._choose()
        if isinstance(chosen,tuple):
            self.lifecycle='ready'
            return dict(chosen[1],transport='ssh')
        chosen.observation_deadline=self.observation_deadline
        result=chosen.ready() if chosen._reboot_pending else chosen.inspect()
        self._last_boot=result['boot_id']
        self.lifecycle='ready'
        return dict(result,transport='uart')

    def ready(self):
        if self.active=='uart':
            self.uart.observation_deadline=self.observation_deadline
            return self.uart.ready()
        return self.inspect()

    def reset(self):
        target=self.uart if self.active=='uart' else self.ssh
        if self.active is None:raise RuntimeError('Inspect the board before rebooting')
        # No second reset through the other adapter, regardless of delivery.
        if self.active=='ssh':
            self.uart._before_boot=self._last_boot;self.uart._reboot_pending=True
        try:target.reset()
        except (ActionRejected,ActionNotDispatched):
            self.uart._reboot_pending=False
            raise

    def execute(self,request):
        try:return super().execute(request)
        finally:
            self.ssh._operation_deadline=None
            self.uart._operation_deadline=None

    def script(self,source,args,timeout):
        self.inspect()  # choose/check before issuing the reviewed script
        self.ssh._operation_deadline=self._operation_deadline
        self.uart._operation_deadline=self._operation_deadline
        target=self.uart if self.active=='uart' else self.ssh
        try:
            result=target.script(source,args,timeout)
            self._dispatch='accepted'
            return result
        except ActionUncertain:
            self._dispatch=getattr(target,'_dispatch','possibly_sent')
            raise
        except Exception as exc:
            self._dispatch=getattr(target,'_dispatch','possibly_sent')
            if self._dispatch=='not_sent':raise
            raise ActionUncertain('Custom script execution may be incomplete: '+redact(str(exc))+'. It was not replayed through the other transport.') from None
        finally:
            self._last_output=getattr(target,'_last_output',('',''))

    def evidence(self):
        target=self.uart if self.active=='uart' else self.ssh
        return target.evidence()

    def drain_events(self):
        result=self.messages;self.messages=[];return result

    def take_serial_log(self):return self.uart.take_serial_log()
    def close(self):
        try:self.ssh.close()
        finally:self.uart.close();super().close()
