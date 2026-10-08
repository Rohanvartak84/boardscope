import json
import os
import select
import subprocess
import threading
import time

import paramiko
import pytest
from fastapi.testclient import TestClient
import boardscope.app as module
from boardscope.adapters import SSHBoard
from boardscope.credentials import set_credentials, get_secret, clear_credentials
from boardscope.uart import UARTBoard


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(module,'DATA',tmp_path)
    monkeypatch.setattr(module,'DB',tmp_path/'lab.sqlite3')
    with TestClient(module.app,base_url='http://127.0.0.1',headers={'X-BoardScope-Token':module.TOKEN}) as c:
        yield c


def test_password_is_session_only_and_errors_are_redacted(client,monkeypatch):
    secret='testing-session-secret'
    payload={'name':'Physical','mode':'ssh','host':'192.0.2.1','username':'engineer','auth_method':'password','ssh_password':secret}
    r=client.post('/api/boards',json=payload)
    assert r.status_code==201 and secret not in r.text
    bid=r.json()['id']
    assert get_secret(bid,'ssh_password')==secret
    assert secret not in client.get('/api/state').text
    assert secret not in module.DB.read_bytes().decode(errors='ignore')
    class Fails:
        def inspect(self):raise RuntimeError('login failed '+secret)
    monkeypatch.setattr(module,'adapter',lambda board:Fails())
    response=client.post('/api/boards/'+bid+'/verify',json={})
    assert response.status_code==400 and secret not in response.text
    assert secret not in client.get('/api/state').text
    assert secret not in module.DB.read_bytes().decode(errors='ignore')
    clear_credentials()
    assert not client.get('/api/state').json()['boards'][0]['credential_status']['ssh_password']


def test_credentials_validation_does_not_echo_secret(client):
    secret='Z'*1025
    r=client.post('/api/boards',json={'name':'Test','ssh_password':secret})
    assert r.status_code==422 and secret not in r.text
    assert 'input' not in r.text


def test_ssh_password_uses_explicit_auth_without_keys(monkeypatch):
    calls={}
    class Client:
        def load_system_host_keys(self):pass
        def set_missing_host_key_policy(self,p):assert isinstance(p,paramiko.RejectPolicy)
        def connect(self,*a,**kwargs):calls.update(kwargs)
        def close(self):pass
    monkeypatch.setattr(paramiko,'SSHClient',Client)
    set_credentials('ssh-test',ssh_password='session-only-password')
    a=SSHBoard({'id':'ssh-test','host':'example','port':22,'username':'engineer','auth_method':'password','key_path':'ignored'})
    a.client()
    assert calls['password']=='session-only-password'
    assert not calls['allow_agent'] and not calls['look_for_keys'] and calls['key_filename'] is None
    clear_credentials()
    with pytest.raises(RuntimeError,match='missing for this session'):a.client()


def test_edit_connection_keeps_blank_session_password_and_verifies_both(client,monkeypatch):
    payload={'name':'Test','mode':'ssh','host':'192.0.2.1','username':'engineer','auth_method':'password','ssh_password':'session-secret','serial_port':'/dev/ttyTEST'}
    b=client.post('/api/boards',json=payload).json();bid=b['id']
    payload.pop('ssh_password');payload['host']='192.0.2.2'
    assert client.post('/api/boards/'+bid+'/connection',json=payload).status_code==200
    assert get_secret(bid,'ssh_password')=='session-secret'
    modes=[]
    class OK:
        def inspect(self):return {'boot_id':'00000000-0000-0000-0000-000000000001','machine':'riscv64','os':'Yocto'}
    monkeypatch.setattr(module,'adapter',lambda b:(modes.append(b['mode']) or OK()))
    ssh=client.post('/api/boards/'+bid+'/verify',json={'transport':'ssh'})
    uart=client.post('/api/boards/'+bid+'/verify',json={'transport':'uart'})
    assert ssh.status_code==uart.status_code==200
    assert modes==['ssh','uart'] and uart.json()['same_boot_as_other_connection'] is True
    states=client.get('/api/state').json()['boards'][0]['connection_checks']
    assert states['ssh']['status']==states['uart']['status']=='verified'


def test_uart_tests_are_explicitly_blocked(client):
    b=client.post('/api/boards',json={'name':'Serial','mode':'uart','serial_port':'/dev/ttyTEST'}).json()
    assert client.post('/api/runs',json={'board_id':b['id']}).status_code==422


@pytest.mark.skipif(os.name!='posix',reason='Pseudo-terminal tests require POSIX')
@pytest.mark.parametrize('login',[False,True])
def test_uart_identity_via_real_serial_pseudoterminal(login):
    import pty
    master,slave=pty.openpty();path=os.ttyname(slave);done=threading.Event();received=[];errors=[]
    def emulator():
        try:
            time.sleep(.15)
            os.write(master,b'desk-board login: ' if login else b'root@desk-board:~# ')
            pending=b'';stage=0 if login else 2
            while not done.is_set():
                ready,_,_=select.select([master],[],[],.1)
                if not ready:continue
                pending+=os.read(master,8192)
                while b'\n' in pending:
                    line,pending=pending.split(b'\n',1);received.append(line)
                    if stage==0:
                        assert line==b'engineer';os.write(master,b'Password: ');stage=1
                    elif stage==1:
                        assert line==b'fake-password';os.write(master,b'engineer@desk-board:~$ ');stage=2
                    else:
                        # Execute only the fixed read-only identity command against
                        # the test host, emulating a Linux console over a PTY.
                        p=subprocess.run(['sh','-c',line.decode()],capture_output=True,timeout=3)
                        os.write(master,p.stdout.replace(b'\n',b'\r\n')+b'engineer@desk-board:~$ ')
        except Exception as e:errors.append(e)
    thread=threading.Thread(target=emulator,daemon=True);thread.start()
    try:
        set_credentials('pty-board',uart_password='fake-password')
        a=UARTBoard({'id':'pty-board','serial_port':path,'baud':115200,'uart_username':'engineer'})
        snapshot=a.inspect()
        assert snapshot['machine'] and snapshot['transport']=='uart'
        assert 'lo' in snapshot['interfaces']
        assert 'fake-password' not in json.dumps(snapshot)
        assert not errors
    finally:
        done.set();thread.join(1);os.close(master);os.close(slave);clear_credentials()


def test_uart_bootloader_receives_no_credentials():
    class Console:
        writes=[]
        def read(self,n):return b'U-Boot> '
        def write(self,data):self.writes.append(data)
        def flush(self):pass
    c=Console()
    a=UARTBoard({'id':'test','uart_username':'engineer','uart_wake':True})
    with pytest.raises(RuntimeError,match='Bootloader'):a._login(c,1)
    assert c.writes==[]
