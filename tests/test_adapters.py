import subprocess
import uuid
import pytest
from boardscope.adapters import SSHBoard


def test_linux_capability_script_on_host(monkeypatch):
    # Run the exact POSIX inspection script on Linux; this catches shell/glob
    # compatibility errors without issuing a reboot or connecting to hardware.
    board=SSHBoard({})
    def command(cmd,timeout=15,stdin_text=None):
        p=subprocess.run(['sh','-s'],input=stdin_text,text=True,capture_output=True,timeout=timeout)
        return p.returncode,p.stdout,p.stderr
    monkeypatch.setattr(board,'command',command)
    snapshot=board.inspect()
    uuid.UUID(snapshot['boot_id'])
    assert snapshot['machine'] and 'lo' in snapshot['interfaces']
    assert snapshot['sound_cards']>=0 and not snapshot['simulated']


def test_script_argument_shell_escaping(monkeypatch):
    board=SSHBoard({})
    def command(cmd,timeout=15,stdin_text=None):
        p=subprocess.run(cmd,input=stdin_text,text=True,capture_output=True,shell=True,timeout=timeout)
        return p.returncode,p.stdout,p.stderr
    monkeypatch.setattr(board,'command',command)
    dangerous="x; printf INJECTED; $(printf injected) 'quoted'"
    code,out,err=board.script('printf "%s" "$1"\n',[dangerous],5)
    assert code==0 and out==dangerous


def test_unknown_ssh_host_key_rejected_and_connection_closed(monkeypatch):
    import paramiko
    class Client:
        closed=False
        def load_system_host_keys(self):pass
        def set_missing_host_key_policy(self,policy):
            assert isinstance(policy,paramiko.RejectPolicy)
        def connect(self,*a,**k):raise paramiko.SSHException('Unknown host')
        def close(self):self.closed=True
    c=Client()
    monkeypatch.setattr(paramiko,'SSHClient',lambda:c)
    board=SSHBoard({'host':'test','port':22,'username':'engineer'})
    with pytest.raises(paramiko.SSHException):board.client()
    assert c.closed
