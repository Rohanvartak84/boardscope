import io
import threading
import time
from types import SimpleNamespace

import paramiko
import pytest

from boardscope.adapters import SSHBoard, Simulator, adapter
from boardscope.credentials import set_credentials, get_secret, clear_credentials, credential_scope, redact
from boardscope.executor import BoardExecutor, ExecutionRequest
from boardscope.factory import create_executor
from boardscope.serial_resource import acquire_port
from boardscope.transport import AuthenticationError, ResourceBusy, ActionUncertain
from boardscope.uart import UARTBoard


def test_factory_contract_no_connection_side_effects(monkeypatch):
    def forbidden(*a,**k):raise AssertionError('Factory must not contact hardware')
    monkeypatch.setattr(paramiko.SSHClient,'connect',forbidden)
    import serial
    monkeypatch.setattr(serial,'Serial',forbidden)
    for mode in ('ssh','uart','auto','simulator'):
        a=create_executor({'mode':mode,'environment':'Ubuntu'})
        assert isinstance(a,BoardExecutor) and a.lifecycle=='closed'
    assert not issubclass(UARTBoard,SSHBoard)
    with pytest.raises(ValueError):adapter({'mode':'typo'})
    with pytest.raises(TypeError):BoardExecutor({})


class Channel:
    def __init__(self,stdout=b'',stderr=b'',code=0,silent=False):
        self.stdout=stdout;self.stderr=stderr;self.code=code;self.silent=silent;self.closed=False;self.sent=[]
    def settimeout(self,t):assert 0<t<=.2
    def send(self,data):self.sent.append(data);return len(data)
    def shutdown_write(self):pass
    def recv_ready(self):return bool(self.stdout)
    def recv_stderr_ready(self):return bool(self.stderr)
    def recv(self,n):data=self.stdout[:n];self.stdout=self.stdout[n:];return data
    def recv_stderr(self,n):data=self.stderr[:n];self.stderr=self.stderr[n:];return data
    def exit_status_ready(self):return not self.silent
    def recv_exit_status(self):
        assert not self.stdout and not self.stderr,'Drain both streams before waiting for status'
        return self.code


class Client:
    def __init__(self,channel):self.channel=channel;self.closed=threading.Event();self.calls=0
    def exec_command(self,command,timeout):
        self.calls+=1;return None,SimpleNamespace(channel=self.channel),None
    def close(self):self.channel.closed=True;self.closed.set()


def ssh(monkeypatch,channel):
    a=SSHBoard({'id':'mock-ssh'});client=Client(channel)
    monkeypatch.setattr(a,'client',lambda:client)
    return a,client


def test_ssh_normalizes_nonzero_exit_without_transport_failure(monkeypatch):
    a,c=ssh(monkeypatch,Channel(b'output',b'device missing',7))
    result=a.execute(ExecutionRequest('false',('literal; arg',),1))
    assert result.completion=='completed' and result.exit_code==7 and result.error is None
    assert result.stdout=='output' and result.stderr=='device missing' and not result.combined
    assert c.closed.is_set() and c.calls==1
    assert b''.join(c.channel.sent)==b'false'
    assert 'source' not in result.public()


def test_ssh_silent_command_has_absolute_deadline_and_no_replay(monkeypatch):
    a,c=ssh(monkeypatch,Channel(b'partial output',silent=True))
    start=time.monotonic();result=a.execute(ExecutionRequest('sleep forever',timeout_s=.08))
    assert time.monotonic()-start<1 and c.closed.is_set()
    assert result.completion=='uncertain' and result.remote_may_be_running
    assert result.stdout=='partial output' and result.exit_code is None
    assert not result.evidence_complete and a.lifecycle=='uncertain'
    again=a.execute(ExecutionRequest('must not run'))
    assert again.completion=='uncertain' and c.calls==1


def test_ssh_missing_status_is_not_a_failed_assertion(monkeypatch):
    a,c=ssh(monkeypatch,Channel(b'partial',code=-1))
    result=a.execute(ExecutionRequest('true',timeout_s=1))
    assert result.exit_code is None and result.completion=='uncertain'
    assert result.stdout=='partial' and c.closed.is_set()


def test_ssh_predispatch_auth_failure_is_not_uncertain(monkeypatch):
    a=SSHBoard({})
    def missing():raise AuthenticationError('Password missing for this session')
    monkeypatch.setattr(a,'client',missing)
    result=a.execute(ExecutionRequest('true'))
    assert result.dispatch=='not_sent' and result.completion=='error'
    assert not result.remote_may_be_running and result.error_class=='authentication'


def test_ssh_cancel_after_dispatch_preserves_uncertainty(monkeypatch):
    a,c=ssh(monkeypatch,Channel(b'partial',silent=True))
    a.configure(lambda:bool(c.channel.sent) and not c.channel.stdout)
    result=a.execute(ExecutionRequest('echo partial; sleep forever'))
    assert result.completion=='uncertain' and result.stdout=='partial' and c.closed.is_set()


def test_ssh_unacknowledged_request_is_interrupted_by_guard(monkeypatch):
    a,c=ssh(monkeypatch,Channel(silent=True))
    def stuck(command,timeout):
        assert c.closed.wait(.8),'Guard must close a request waiting for an acknowledgement'
        raise ConnectionError('request acknowledgement lost')
    monkeypatch.setattr(c,'exec_command',stuck)
    result=a.execute(ExecutionRequest('true',timeout_s=.08))
    assert result.completion=='uncertain' and c.closed.is_set()


def test_serial_aliases_share_one_owner(tmp_path):
    real=tmp_path/'tty';real.touch();alias=tmp_path/'alias';alias.symlink_to(real)
    lease=acquire_port(str(real))
    try:
        with pytest.raises(ResourceBusy):acquire_port(str(alias))
    finally:lease.release()
    acquire_port(str(alias)).release()


def test_optional_capture_contention_does_not_break_ssh_or_claim_fallback(tmp_path):
    path=str(tmp_path/'tty');owner=acquire_port(path)
    a=SSHBoard({'serial_port':path})
    try:
        a.open();notes=a.drain_events()
        assert notes and all(n['kind']=='evidence' for n in notes)
        with pytest.raises(ResourceBusy):acquire_port(path)
    finally:a.close();owner.release()


def test_credential_scope_is_volatile_and_isolated():
    clear_credentials();set_credentials('a',ssh_password='old-secret')
    try:
        with credential_scope('a'):
            set_credentials('a',ssh_password='new-secret')
            assert get_secret('a','ssh_password')=='old-secret'
            assert redact('old-secret new-secret')=='[REDACTED] [REDACTED]'
        assert get_secret('a','ssh_password')=='new-secret'
    finally:clear_credentials()
    assert get_secret('a','ssh_password') is None


def test_ssh_private_key_is_parsed_from_memory_without_disk_or_agent(monkeypatch):
    key=paramiko.RSAKey.generate(1024);buffer=io.StringIO();key.write_private_key(buffer,password='fixture-passphrase')
    secret=buffer.getvalue();calls={}
    class AuthClient:
        def load_system_host_keys(self):pass
        def set_missing_host_key_policy(self,p):pass
        def connect(self,*a,**kw):calls.update(kw)
        def close(self):pass
    monkeypatch.setattr(paramiko,'SSHClient',AuthClient)
    set_credentials('key-test',ssh_private_key=secret,ssh_key_passphrase='fixture-passphrase')
    try:
        a=SSHBoard({'id':'key-test','host':'fixture','port':22,'username':'engineer','auth_method':'key'})
        a.client().close()
        assert calls['pkey'].get_name()=='ssh-rsa' and calls['key_filename'] is None
        assert not calls['look_for_keys'] and not calls['allow_agent']
    finally:clear_credentials()


def test_fallback_execution_uses_shared_record_and_clears_child_deadlines(monkeypatch):
    import boardscope.fallback as module
    from tests.executor_stub import StubExecutor
    calls=[]
    class SSH(StubExecutor):
        def inspect(self):raise ConnectionError('fixture network down')
    class UART(StubExecutor):
        transport_name='uart';_reboot_pending=False
        def inspect(self):return {'boot_id':'fixture-boot'}
        def script(self,*args):calls.append('script');return 3,'console output',''
    monkeypatch.setattr(module,'SSHBoard',SSH);monkeypatch.setattr(module,'UARTBoard',UART)
    a=module.FallbackBoard({})
    result=a.execute(ExecutionRequest('false',timeout_s=1))
    assert result.transport=='uart' and result.combined and result.stderr is None
    assert result.exit_code==3 and result.completion=='completed' and calls==['script']
    assert a.ssh._operation_deadline is None and a.uart._operation_deadline is None
    assert a.drain_events()[0]['kind']=='connection_fallback'
    a.close()


def test_reboot_preflight_failure_does_not_claim_reset_delivery(monkeypatch):
    from boardscope.transport import ActionNotDispatched
    a=SSHBoard({})
    def denied(*args,**kwargs):raise AuthenticationError('missing login')
    monkeypatch.setattr(a,'command',denied)
    with pytest.raises(ActionNotDispatched,match='not dispatched'):a.reset()


def test_uart_invalid_completion_frame_is_uncertain_not_an_assertion_failure(monkeypatch):
    import re
    a=UARTBoard({});wire=[]
    class Handle:
        def write(self,data):wire.append(data);return len(data)
        def close(self):pass
    a._handle=Handle()
    def read():
        marker=re.search(rb'BS_[a-f0-9]+',wire[-1]).group().decode()
        return marker+'_BEGIN\npartial\n'+marker+'_END:999\n'
    monkeypatch.setattr(a,'_read',read)
    with pytest.raises(ActionUncertain):a._execute('false',1,action=True)
    assert a._blocked


def test_reboot_host_trust_failure_keeps_identity_boundary(monkeypatch):
    from boardscope.transport import HostTrustError
    a=SSHBoard({})
    def untrusted(*args,**kwargs):raise HostTrustError('changed fingerprint')
    monkeypatch.setattr(a,'command',untrusted)
    with pytest.raises(HostTrustError):a.reset()
