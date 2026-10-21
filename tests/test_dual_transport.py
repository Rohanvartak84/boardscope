from tests.executor_stub import StubExecutor
import os
import re
import select
import subprocess
import threading
import time
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
import boardscope.app as app
import boardscope.fallback as fallback
from boardscope.adapters import SSHBoard
from boardscope.credentials import set_credentials, clear_credentials
from boardscope.transport import ActionUncertain, ActionRejected, HostTrustError
from boardscope.uart import UARTBoard


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(app,'DATA',tmp_path);monkeypatch.setattr(app,'DB',tmp_path/'lab.sqlite3')
    with TestClient(app.app,base_url='http://127.0.0.1',headers={'X-BoardScope-Token':app.TOKEN}) as c:yield c


@contextmanager
def console(uid='1000',sudo_ok=True,echo=False):
    import pty
    master,slave=pty.openpty();path=os.ttyname(slave);stop=threading.Event();wire=[];errors=[]
    shell=subprocess.Popen(['sh'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    state={'boot':1,'stage':'username','resets':0,'passwords':0}
    def worker():
        try:
            time.sleep(.15);os.write(master,b'desk login: ')
            pending=b''
            while not stop.is_set():
                ready,_,_=select.select([master],[],[],.1)
                if not ready:continue
                pending+=os.read(master,8192)
                while b'\n' in pending:
                    line,pending=pending.split(b'\n',1);wire.append(line)
                    stage=state['stage']
                    if stage=='username':
                        assert line==b'engineer';os.write(master,b'Password: ');state['stage']='password'
                    elif stage=='password':
                        assert line==b'fake-login-secret';os.write(master,b'engineer@desk:~$ ');state['stage']='shell'
                    elif stage=='sudo':
                        assert line==b'fake-sudo-secret';state['passwords']+=1
                        # Deliberately echo in the emulator to verify log redaction.
                        os.write(master,line+b'\r\n')
                        if not sudo_ok:
                            os.write(master,('\r\n'+state['rc']+':1\r\nengineer@desk:~$ ').encode());state['stage']='shell';continue
                        state['resets']+=1;state['boot']+=1;state['stage']='username'
                        os.write(master,b'\r\nU-Boot 2026\r\nHit any key to stop autoboot\r\nLinux booting\r\ndesk login: ')
                    elif b'/sbin/reboot' in line:
                        assert state['stage']=='shell'
                        rc=re.search(r'BS_[a-f0-9]+_RESET_RC',line.decode()).group(0)
                        state['rc']=rc
                        if uid=='0':
                            state['resets']+=1;state['boot']+=1;state['stage']='username';os.write(master,b'Linux booting\r\ndesk login: ')
                        else:
                            prompt=re.search(r'BS_[a-f0-9]+_SUDO',line.decode()).group(0)
                            os.write(master,('\r\n'+prompt).encode());state['stage']='sudo'
                    else:
                        if echo:os.write(master,line+b'\r\n')
                        command=line.decode().replace("'id -u'", "'printf "+uid+"'")
                        shell.stdin.write((command+'\n').encode());shell.stdin.flush()
                        out=b'';deadline=time.monotonic()+4
                        while time.monotonic()<deadline:
                            if select.select([shell.stdout],[],[],.1)[0]:out+=os.read(shell.stdout.fileno(),8192)
                            if re.search(rb'BS_[a-f0-9]+_END:[0-9]+\n',out):break
                        else:raise TimeoutError('Emulated shell command did not complete')
                        out=re.sub(rb'(BOOT=)[0-9a-fA-F-]{36}',lambda m:m.group(1)+(f'00000000-0000-0000-0000-{state["boot"]:012d}').encode(),out)
                        os.write(master,out.replace(b'\n',b'\r\n')+b'engineer@desk:~$ ')
        except Exception as exc:errors.append(exc)
    thread=threading.Thread(target=worker,daemon=True);thread.start()
    try:yield path,state,wire,errors
    finally:
        stop.set();thread.join(3);shell.terminate();shell.wait(timeout=3)
        shell.stdin.close();shell.stdout.close();os.close(master);os.close(slave)


def board(path):
    return {'id':'console-test','mode':'uart','serial_port':path,'baud':115200,'uart_username':'engineer','sudo_mode':'password','sudo_password_source':'separate'}


@pytest.mark.skipif(os.name!='posix',reason='Serial emulation needs POSIX')
@pytest.mark.parametrize('uid',['0','1000'])
def test_uart_reboot_relogin_new_boot_and_sudo_redaction(uid):
    with console(uid=uid) as (path,state,wire,errors):
        set_credentials('console-test',uart_password='fake-login-secret',sudo_password='fake-sudo-secret')
        a=UARTBoard(board(path))
        try:
            a.open();before=a.inspect()['boot_id'];a.reset();after=a.ready()['boot_id']
            assert before!=after and state['resets']==1 and not errors
            assert state['passwords']==(1 if uid=='1000' else 0)
            assert all(b'fake-sudo-secret' not in line for line in wire if b'/sbin/reboot' in line)
            log=a.take_serial_log();assert 'fake-sudo-secret' not in log and 'fake-login-secret' not in log
            assert 'Linux booting' in log
        finally:a.close();clear_credentials()


@pytest.mark.skipif(os.name!='posix',reason='Serial emulation needs POSIX')
def test_uart_large_custom_script_preserves_args_exit_code_and_cleanup():
    with console() as (path,state,wire,errors):
        set_credentials('console-test',uart_password='fake-login-secret')
        a=UARTBoard(board(path))
        source='# '+('comment '*650)+'\nprintf "%s\\n" "$1"\nprintf "stderr-marker\\n" >&2\nexit 7\n'
        arg="literal; $(printf INJECTION) 'quote'"
        try:
            code,out,err=a.script(source,[arg],20)
            assert code==7 and arg in out and 'stderr-marker' in out and not errors
            assert all(len(line)<3500 for line in wire)
            assert state['resets']==0
        finally:a.close();clear_credentials()


@pytest.mark.skipif(os.name!='posix',reason='Serial emulation needs POSIX')
def test_uart_rejected_sudo_does_not_reboot():
    with console(sudo_ok=False) as (path,state,wire,errors):
        set_credentials('console-test',uart_password='fake-login-secret',sudo_password='fake-sudo-secret')
        a=UARTBoard(board(path))
        try:
            a.open()
            with pytest.raises(ActionRejected):a.reset()
            assert state['resets']==0 and state['passwords']==1 and not errors
        finally:a.close();clear_credentials()


def test_ssh_reset_password_sent_via_stdin_only(monkeypatch):
    a=SSHBoard({'id':'sudo-test','sudo_mode':'password','sudo_password_source':'separate'});calls=[]
    set_credentials('sudo-test',sudo_password='fake-sudo-secret')
    def command(cmd,timeout=15,stdin_text=None):
        calls.append((cmd,stdin_text));return (0,'1000\n','') if cmd=='id -u' else (0,'','')
    monkeypatch.setattr(a,'command',command)
    try:
        a.reset();assert calls[-1][1]=='fake-sudo-secret\n'
        assert 'fake-sudo-secret' not in calls[-1][0]
    finally:clear_credentials()


def test_fallback_records_failure_and_never_replays_script(monkeypatch):
    calls=[]
    class SSH:
        def __init__(self,b):pass
        def inspect(self):calls.append('ssh-inspect');raise ConnectionError('network down')
    class UART:
        _reboot_pending=False
        def __init__(self,b):pass
        def open(self):calls.append('uart-open')
        def inspect(self):return {'boot_id':'boot-a','transport':'uart'}
        def script(self,*a):calls.append('uart-script');raise ActionUncertain('missing result')
    monkeypatch.setattr(fallback,'SSHBoard',SSH);monkeypatch.setattr(fallback,'UARTBoard',UART)
    a=fallback.FallbackBoard({})
    with pytest.raises(ActionUncertain):a.script('true',[],5)
    assert calls==['ssh-inspect','uart-open','uart-script']
    assert any('network down' in e['message'] for e in a.drain_events())


def test_host_trust_failure_does_not_fallback(monkeypatch):
    class SSH:
        def __init__(self,b):pass
        def inspect(self):raise HostTrustError('changed fingerprint')
    class UART:
        def __init__(self,b):pass
        def open(self):raise AssertionError('must not bypass host trust')
    monkeypatch.setattr(fallback,'SSHBoard',SSH);monkeypatch.setattr(fallback,'UARTBoard',UART)
    with pytest.raises(HostTrustError):fallback.FallbackBoard({}).inspect()


def wait(client,rid):
    end=time.monotonic()+5
    while time.monotonic()<end:
        r=client.get('/api/runs/'+rid).json()
        if r['state'] not in app.ACTIVE:return r
        time.sleep(.02)
    raise AssertionError('run did not finish')


@pytest.mark.parametrize('mode',['uart','auto'])
def test_custom_runs_on_uart_and_auto_with_uncertain_result_stopping_run(client,monkeypatch,mode):
    calls=[]
    class Adapter(StubExecutor):
        simulated=False;active='uart'
        def open(self):pass
        def inspect(self):return {'boot_id':'boot','interfaces':['end0'],'sound_cards':3}
        def script(self,*args):calls.append('script');raise ActionUncertain('execution lost; do not replay')
        def take_serial_log(self):return 'partial console output'
        def close(self):calls.append('close')
    monkeypatch.setattr(app,'adapter',lambda b:Adapter())
    b=client.post('/api/boards',json={'name':'Physical','mode':'uart','host':'192.0.2.1','username':'engineer','serial_port':'/dev/ttyTEST'}).json()
    script=client.post('/api/scripts',json={'name':'test','source':'true','confirmed':True}).json()
    r=client.post('/api/runs',json={'board_id':b['id'],'test':'custom','transport':mode,'allow_fallback':True,'script_id':script['id'],'allow_script':True,'cycles':5,'failure_policy':'continue','interval_s':0})
    assert r.status_code==201,r.text
    done=wait(client,r.json()['id'])
    assert done['outcome']=='error' and done['completed_cycles']==1
    assert calls.count('script')==1 and calls[-1]=='close'
    assert done['cycles'][0]['transport']=='uart'
    assert 'do not replay' in done['cycles'][0]['kernel_log']


def test_auto_requires_pairing_authorisation_and_sudo_password_stays_local(client):
    b=client.post('/api/boards',json={'name':'Paired','mode':'ssh','host':'192.0.2.1','username':'engineer','serial_port':'/dev/ttyTEST','sudo_password':'fake-private-sudo'}).json()
    assert 'fake-private-sudo' not in str(b)
    assert 'fake-private-sudo' not in client.get('/api/state').text
    assert client.post('/api/runs',json={'board_id':b['id'],'transport':'auto'}).status_code==422
    assert client.post('/api/runs',json={'board_id':b['id'],'transport':'uart','test':'reboot'}).status_code==422


def test_reboot_observation_falls_back_without_second_reset(monkeypatch):
    calls=[]
    class SSH:
        def __init__(self,b):self.down=False
        def inspect(self):
            if self.down:raise ConnectionError('IP changed')
            return {'boot_id':'boot-before'}
        def reset(self):calls.append('ssh-reset');self.down=True;raise ActionUncertain('delivery lost')
    class UART:
        _reboot_pending=False
        def __init__(self,b):pass
        def open(self):calls.append('uart-open')
        def ready(self):return {'boot_id':'boot-after','transport':'uart'}
        def reset(self):raise AssertionError('must not reset a second time')
    monkeypatch.setattr(fallback,'SSHBoard',SSH);monkeypatch.setattr(fallback,'UARTBoard',UART)
    a=fallback.FallbackBoard({});assert a.inspect()['boot_id']=='boot-before'
    with pytest.raises(ActionUncertain):a.reset()
    assert a.ready()['boot_id']=='boot-after'
    assert calls==['ssh-reset','uart-open']


def test_uart_reboot_runner_records_each_changed_boot(client,monkeypatch):
    class UART(StubExecutor):
        transport_name='uart'
        simulated=False
        def __init__(self):super().__init__();self.boot=1;self.resets=0;self.closed=False
        def open(self):pass
        def inspect(self):return {'boot_id':str(self.boot),'interfaces':['end0'],'sound_cards':3}
        def ready(self):return self.inspect()
        def reset(self):self.boot+=1;self.resets+=1
        def evidence(self):return 'kernel boot evidence'
        def close(self):self.closed=True
    a=UART();monkeypatch.setattr(app,'adapter',lambda b:a)
    b=client.post('/api/boards',json={'name':'UART','mode':'uart','serial_port':'/dev/ttyTEST'}).json()
    response=client.post('/api/runs',json={'board_id':b['id'],'test':'reboot','allow_reboot':True,'cycles':2,'interval_s':0,'timeout_s':5})
    assert response.status_code==201
    r=wait(client,response.json()['id'])
    assert r['outcome']=='pass' and a.resets==2 and a.closed
    assert all(c['checks'][0]['name']=='New boot verified' and c['checks'][0]['outcome']=='pass' for c in r['cycles'])


@pytest.mark.skipif(os.name!='posix',reason='Serial emulation needs POSIX')
def test_uart_script_timeout_blocks_further_commands_without_replay():
    with console() as (path,state,wire,errors):
        set_credentials('console-test',uart_password='fake-login-secret')
        a=UARTBoard(board(path))
        try:
            with pytest.raises(ActionUncertain):a.script('sleep 2\necho late\n',[],.5)
            count=len(wire)
            with pytest.raises(ActionUncertain):a.inspect()
            assert len(wire)==count and a._blocked
        finally:a.close();clear_credentials()


def test_successful_fallback_keeps_connection_failure_visible(client,monkeypatch):
    class Adapter(StubExecutor):
        simulated=False;active='uart'
        def __init__(self):super().__init__();self.notes=[{'kind':'connection_fallback','level':'warning','message':'SSH unreachable; switching to UART'}]
        def inspect(self):return {'boot_id':'boot','interfaces':['end0'],'sound_cards':3}
        def ready(self):return self.inspect()
        def evidence(self):return 'kernel evidence'
        def take_serial_log(self):return ''
        def drain_events(self):notes=self.notes;self.notes=[];return notes
        def close(self):pass
    monkeypatch.setattr(app,'adapter',lambda b:Adapter())
    b=client.post('/api/boards',json={'name':'Paired','mode':'ssh','host':'192.0.2.1','username':'engineer','serial_port':'/dev/ttyTEST'}).json()
    response=client.post('/api/runs',json={'board_id':b['id'],'transport':'auto','allow_fallback':True,'cycles':1,'interval_s':0})
    r=wait(client,response.json()['id'])
    assert r['outcome']=='pass' and r['fallback_attempted'] and r['fallback_used']
    assert r['cycles'][0]['connection_notes'][0]['message']=='SSH unreachable; switching to UART'
    assert any(e['level']=='warning' and 'SSH unreachable' in e['message'] for e in r['events'])


@pytest.mark.skipif(os.name!='posix',reason='Serial emulation needs POSIX')
def test_uart_common_execution_record_filters_echo_and_uses_no_target_files():
    from boardscope.executor import ExecutionRequest
    with console(echo=True) as (path,state,wire,errors):
        set_credentials('console-test',uart_password='fake-login-secret')
        a=UARTBoard(board(path))
        source='printf "real-output\\n"; printf "error-output\\n" >&2; exit 9\n'
        try:
            result=a.execute(ExecutionRequest(source,timeout_s=4))
            assert result.completion=='completed' and result.exit_code==9
            assert result.combined and result.stderr is None
            assert result.stdout.strip()=='real-output\nerror-output'
            assert all(b'/tmp/boardscope-' not in line for line in wire)
            assert not errors
        finally:a.close();clear_credentials()
