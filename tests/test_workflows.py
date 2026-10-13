import json
import time
import pytest
from fastapi.testclient import TestClient
import boardscope.app as module


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'DATA', tmp_path)
    monkeypatch.setattr(module, 'DB', tmp_path / 'lab.sqlite3')
    monkeypatch.delenv('BOARDSCOPE_MODEL', raising=False)
    with TestClient(module.app, base_url='http://127.0.0.1', headers={'X-BoardScope-Token':module.TOKEN}) as c:
        yield c
        for r in c.get('/api/state').json()['runs']:
            if r['state'] in module.ACTIVE:
                c.post(f"/api/runs/{r['id']}/control",json={'action':'stop'})
                wait(c,r['id'],lambda x:x['state'] not in module.ACTIVE)


def wait(c,rid,predicate,timeout=6):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        r=c.get('/api/runs/'+rid).json()
        if predicate(r):return r
        time.sleep(.03)
    raise AssertionError('Run did not reach expected state: '+json.dumps(r))


def start(c,env='Ubuntu',**kwargs):
    b=next(b for b in c.get('/api/state').json()['boards'] if b['environment']==env)
    response=c.post('/api/runs',json={'board_id':b['id'],'test':'reboot','cycles':4,'interval_s':0,'failure_policy':'continue',**kwargs})
    assert response.status_code==201,response.text
    return response.json()


def test_reboot_pass_and_evidence_export(client):
    r=start(client)
    done=wait(client,r['id'],lambda r:r['state']=='completed')
    assert done['outcome']=='pass'
    assert len(done['cycles'])==4
    ids=[c['snapshot']['boot_id'] for c in done['cycles']]
    assert len(set(ids))==4
    assert all(c['simulated'] for c in done['cycles'])
    report=client.get('/api/runs/'+r['id']+'/report')
    assert report.json()['cycles']==done['cycles']
    assert 'attachment' in report.headers['content-disposition']


def test_failure_pause_reservation_resume_and_summary(client):
    r=start(client,'Yocto',failure_policy='pause')
    paused=wait(client,r['id'],lambda r:r['state']=='paused')
    assert paused['completed_cycles']==3
    failed=paused['cycles'][-1]
    assert failed['outcome']=='fail'
    assert 'synthetic' in failed['kernel_log'].lower()
    assert client.post('/api/runs',json={'board_id':r['board_id']}).status_code==409
    assert client.post('/api/boards/'+r['board_id']+'/verify',json={}).status_code==409
    summary=client.post('/api/runs/'+r['id']+'/investigate',json={}).json()
    assert summary['mode']=='deterministic_summary' and summary['baseline']==2
    assert 'expected 3, observed 2' in str(summary['observations'])
    assert client.post('/api/runs/'+r['id']+'/control',json={'action':'resume'}).status_code==200
    done=wait(client,r['id'],lambda r:r['state']=='completed')
    assert done['outcome']=='fail' and done['completed_cycles']==4


def test_stop_releases_board_without_replaying_cycle(client):
    r=start(client,cycles=100,interval_s=.2)
    wait(client,r['id'],lambda r:r['completed_cycles']>=1)
    assert client.post('/api/runs/'+r['id']+'/control',json={'action':'stop'}).status_code==200
    done=wait(client,r['id'],lambda r:r['state']=='cancelled')
    assert done['outcome']=='cancelled' and done['completed_cycles']<100
    assert client.post('/api/boards/'+r['board_id']+'/verify',json={}).status_code==200


def test_process_restart_interrupts_without_reset_replay(client):
    b=client.get('/api/state').json()['boards'][0]
    rid='stale-run'
    data={'id':rid,'state':'running','plan':{'test':'reboot'},'board_id':b['id']}
    with module.connection() as c:c.execute('INSERT INTO runs VALUES(?,?,?,?)',(rid,b['id'],'running',json.dumps(data)))
    module.init_db()
    r=module.item('runs',rid)
    assert r['state']=='interrupted' and r['outcome']=='error'
    assert 'not retried' in r['message']


def test_local_access_and_explicit_physical_authorisation(client):
    assert client.get('/api/state',headers={'X-BoardScope-Token':''}).status_code==401
    assert client.get('/api/state',headers={'Origin':'https://other.example'}).status_code==403
    assert client.get('/api/state',headers={'Host':'other.example'}).status_code==403
    b=client.post('/api/boards',json={'name':'Physical','mode':'ssh','host':'192.0.2.1','username':'engineer'}).json()
    assert client.post('/api/runs',json={'board_id':b['id'],'test':'reboot'}).status_code==422
    assert client.post('/api/scripts',json={'name':'test','source':'true'}).status_code==422
    s=client.post('/api/scripts',json={'name':'test','source':'true','confirmed':True}).json()
    assert 'source' not in s and len(s['sha256'])==64
    assert client.post('/api/runs',json={'board_id':b['id'],'test':'custom','script_id':s['id']}).status_code==422
    demo=client.get('/api/state').json()['boards'][1]
    assert client.post('/api/runs',json={'board_id':demo['id'],'test':'custom','script_id':s['id'],'allow_script':True}).status_code==422


def test_atomic_patch_preserves_operator_control(client):
    b=client.get('/api/state').json()['boards'][0]
    r={'id':'control-race','board_id':b['id'],'state':'stopping','completed_cycles':0}
    with module.connection() as c:c.execute('INSERT INTO runs VALUES(?,?,?,?)',(r['id'],b['id'],r['state'],json.dumps(r)))
    module.patch_run(r['id'],{'state':'running'},states=('queued',))
    module.patch_run(r['id'],{'completed_cycles':1})
    actual=module.item('runs',r['id'])
    assert actual['state']=='stopping' and actual['completed_cycles']==1
    module.patch_run(r['id'],{'state':'cancelled'})


def test_local_ai_invalid_response_does_not_change_outcome(client,monkeypatch):
    r=start(client,'Yocto',failure_policy='abort')
    wait(client,r['id'],lambda r:r['state']=='completed')
    monkeypatch.setenv('BOARDSCOPE_MODEL','local-test')
    class BadResponse:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,n):return b'{"response":"{\\"observations\\":\\"not an array\\"}"}'
    monkeypatch.setattr(module,'urlopen',lambda *a,**k:BadResponse())
    response=client.post('/api/runs/'+r['id']+'/investigate',json={})
    assert response.status_code==502
    assert client.get('/api/runs/'+r['id']).json()['outcome']=='fail'


def test_authorised_custom_script_executes_snapshot_and_hides_source(client,monkeypatch):
    calls=[]
    class FakeSSH:
        simulated=False
        def inspect(self):return {'boot_id':'00000000-0000-0000-0000-000000000001'}
        def script(self,source,args,timeout):
            calls.append((source,args,timeout))
            return 2,'device unavailable',''
        def evidence(self):return 'captured test evidence'
    monkeypatch.setattr(module,'adapter',lambda board:FakeSSH())
    b=client.post('/api/boards',json={'name':'Mock SSH','mode':'ssh','host':'192.0.2.1','username':'engineer'}).json()
    script=client.post('/api/scripts',json={'name':'Device check','source':'test -e "$1"','confirmed':True,'timeout_s':7}).json()
    response=client.post('/api/runs',json={'board_id':b['id'],'test':'custom','script_id':script['id'],'allow_script':True,'args':['/dev/test device'],'cycles':2,'failure_policy':'abort'})
    assert response.status_code==201
    r=wait(client,response.json()['id'],lambda r:r['state']=='completed')
    assert r['outcome']=='fail' and r['completed_cycles']==1
    assert calls==[('test -e "$1"',['/dev/test device'],7)]
    assert r['script_snapshot']['sha256']==script['sha256']
    assert all('source' not in str(x.get('script_snapshot',{})) for x in client.get('/api/state').json()['runs'])


def test_local_ai_uses_local_endpoint_and_saves_reviewable_result(client,monkeypatch):
    r=start(client,'Yocto',failure_policy='abort')
    wait(client,r['id'],lambda r:r['state']=='completed')
    monkeypatch.setenv('BOARDSCOPE_MODEL','local-test')
    result={'observations':['Cycle 3 lost one sound card.'],'hypotheses':['Synthetic probe timeout.'],'next_checks':['Review the probe log.'],'limitations':['Synthetic evidence only.']}
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,n):return json.dumps({'response':json.dumps(result)}).encode()
    def infer(req,timeout):
        assert req.full_url=='http://127.0.0.1:11434/api/generate'
        body=json.loads(req.data)
        assert body['model']=='local-test' and '"simulated": true' in body['prompt']
        return Response()
    monkeypatch.setattr(module,'urlopen',infer)
    response=client.post('/api/runs/'+r['id']+'/investigate',json={})
    assert response.status_code==200
    actual=client.get('/api/runs/'+r['id']).json()
    assert actual['outcome']=='fail' and actual['investigation']['mode']=='local_ai'


def test_script_edit_preserves_run_snapshot(client,monkeypatch):
    class Fake:
        simulated=False
        def inspect(self):return {'boot_id':'mock'}
        def script(self,*args):return 0,'ok',''
        def evidence(self):return 'mock'
    monkeypatch.setattr(module,'adapter',lambda b:Fake())
    board=client.post('/api/boards',json={'name':'mock','mode':'ssh','host':'192.0.2.1','username':'user'}).json()
    script=client.post('/api/scripts',json={'name':'original','source':'echo original','confirmed':True}).json()
    assert client.get('/api/scripts/'+script['id']).json()['source']=='echo original'
    run=client.post('/api/runs',json={'board_id':board['id'],'test':'custom','script_id':script['id'],'allow_script':True,'cycles':1}).json()
    wait(client,run['id'],lambda r:r['state']=='completed')
    assert client.post('/api/scripts/'+script['id']+'/edit',json={'name':'edited','source':'echo edited'}).status_code==422
    updated=client.post('/api/scripts/'+script['id']+'/edit',json={'name':'edited','source':'echo edited','confirmed':True}).json()
    assert updated['version']==2 and updated['sha256']!=script['sha256']
    assert client.get('/api/runs/'+run['id']).json()['script_snapshot']['sha256']==script['sha256']
    assert module.item('runs',run['id'])['script_snapshot']['source']=='echo original'


def test_remove_board_preserves_history_and_forgets_password(client):
    r=start(client,cycles=1)
    wait(client,r['id'],lambda r:r['state']=='completed')
    module.set_credentials(r['board_id'],ssh_password='test-secret')
    assert client.post('/api/boards/'+r['board_id']+'/delete',json={}).status_code==200
    assert r['board_id'] not in [b['id'] for b in client.get('/api/state').json()['boards']]
    assert client.get('/api/runs/'+r['id']).status_code==200
    assert not module.credential_status(r['board_id'])['ssh_password']
    assert client.post('/api/runs',json={'board_id':r['board_id']}).status_code==404


def test_remove_active_board_rejected(client):
    r=start(client,cycles=100,interval_s=.2)
    assert client.post('/api/boards/'+r['board_id']+'/delete',json={}).status_code==409


def test_baseline_failure_has_location_and_guidance(client,monkeypatch):
    class Broken:
        simulated=False
        command_log=[{'command':'sh -s','error':'SSH authentication failed'}]
        def inspect(self):raise RuntimeError('SSH authentication failed')
    monkeypatch.setattr(module,'adapter',lambda b:Broken())
    board=client.post('/api/boards',json={'name':'mock','mode':'ssh','host':'192.0.2.1','username':'user'}).json()
    r=client.post('/api/runs',json={'board_id':board['id'],'cycles':1}).json()
    done=wait(client,r['id'],lambda r:r['state']=='completed')
    assert done['cycles']==[] and done['outcome']=='error'
    assert done['failure']['stage']=='Baseline Linux readiness'
    assert 'username' in str(done['failure']['next_checks'])
    assert done['startup_evidence']['command_log'][0]['command']=='sh -s'
    assert client.get('/api/state').json()['database_path']==str(module.DB.resolve())


def test_cycle_failure_has_guidance_and_separate_script_output(client,monkeypatch):
    class FailedScript:
        simulated=False
        def inspect(self):return {'boot_id':'mock'}
        def script(self,*args):return 7,'device absent','permission denied'
        def evidence(self):return 'mock kernel'
    monkeypatch.setattr(module,'adapter',lambda b:FailedScript())
    b=client.post('/api/boards',json={'name':'mock','mode':'ssh','host':'192.0.2.1','username':'user'}).json()
    s=client.post('/api/scripts',json={'name':'check','source':'false','confirmed':True}).json()
    r=client.post('/api/runs',json={'board_id':b['id'],'test':'custom','script_id':s['id'],'allow_script':True,'cycles':1,'failure_policy':'abort'}).json()
    done=wait(client,r['id'],lambda r:r['state']=='completed');c=done['cycles'][0]
    assert c['failure']['stage']=='Execute custom script'
    assert c['script_output']=={'exit_code':7,'stdout':'device absent','stderr':'permission denied','combined':False}
