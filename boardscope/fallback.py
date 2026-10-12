"""Choose a transport before actions. Never replay a dispatched action."""
from .adapters import SSHBoard
from .uart import UARTBoard
from .credentials import redact
from .transport import ActionUncertain, ActionRejected, HostTrustError


class FallbackBoard:
    simulated=False

    def __init__(self,board):
        self.board=board
        self.ssh=SSHBoard(dict(board,mode='ssh'))
        self.uart=UARTBoard(dict(board,mode='uart'))
        self.active=None
        self.messages=[]
        self.observation_deadline=None
        self._last_boot=None

    def _choose(self):
        # Once a run falls back, retain UART rather than repeatedly delaying it
        # with the same unreachable SSH address. A new run tries SSH again.
        if self.active=='uart':return self.uart
        self.ssh.observation_deadline=self.observation_deadline
        try:
            result=self.ssh.inspect()
            self.active='ssh';self._last_boot=result['boot_id']
            return self.ssh,result
        except HostTrustError:
            raise
        except Exception as exc:
            self.messages.append({'level':'warning','message':'SSH connection/readiness failed: '+redact(str(exc))+'; switching to UART. This connection failure is retained.'})
            self.uart.observation_deadline=self.observation_deadline
            self.uart.open()
            self.active='uart'
            return self.uart

    def inspect(self):
        chosen=self._choose()
        if isinstance(chosen,tuple):return dict(chosen[1],transport='ssh')
        chosen.observation_deadline=self.observation_deadline
        result=chosen.ready() if chosen._reboot_pending else chosen.inspect()
        self._last_boot=result['boot_id']
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
        except ActionRejected:
            self.uart._reboot_pending=False
            raise

    def script(self,source,args,timeout):
        self.inspect()  # choose/check before issuing the reviewed script
        target=self.uart if self.active=='uart' else self.ssh
        try:return target.script(source,args,timeout)
        except ActionUncertain:raise
        except Exception as exc:
            raise ActionUncertain('Custom script execution may be incomplete: '+redact(str(exc))+'. It was not replayed through the other transport.') from None

    def evidence(self):
        target=self.uart if self.active=='uart' else self.ssh
        return target.evidence()

    def drain_events(self):
        result=self.messages;self.messages=[];return result

    def take_serial_log(self):return self.uart.take_serial_log()
    def close(self):self.uart.close()
