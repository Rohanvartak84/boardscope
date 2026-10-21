"""Small contract-compliant executor for API workflow mocks, never hardware."""
from boardscope.executor import BoardExecutor, ExecutorCapabilities


class StubExecutor(BoardExecutor):
    transport_name='ssh'

    def __init__(self,board=None):
        existing=list(getattr(type(self),'command_log',[]))
        super().__init__(board or {})
        self.command_log=existing

    @property
    def capabilities(self):return ExecutorCapabilities(separate_stderr=self.active_transport!='uart')

    @property
    def active_transport(self):return getattr(self,'active',self.transport_name)

    def inspect(self):raise AssertionError('Unexpected inspection')
    def command(self,*args,**kwargs):raise AssertionError('Unexpected shell command')
    def script(self,*args):raise AssertionError('Unexpected script')
    def reset(self):raise AssertionError('Unexpected reset')
    def evidence(self):return ''
