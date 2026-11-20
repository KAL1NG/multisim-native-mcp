import threading
from pathlib import Path
import pytest
from multisim_native_mcp.jobs import ExperimentStore,ExperimentManager


def test_restart_marks_unfinished_jobs_interrupted(tmp_path):
    store=ExperimentStore(tmp_path);key='a'*32
    store.write({'id':key,'status':'running','created':1})
    manager=ExperimentManager(None,tmp_path)
    assert manager.store.read(key)['status']=='interrupted'
    assert manager.store.list()[0]['id']==key
    with pytest.raises(ValueError):manager.store.read('../escape')


def test_background_cancel_and_persistent_result(tmp_path,monkeypatch):
    source=tmp_path/'source.ms14';source.write_bytes(b'native-checkpoint')
    class Host:
        lock=threading.RLock();agent=True;analysis_started=threading.Event()
        def checkpoint(self):return {'path':str(source)}
        def export_image(self,path):Path(path).write_bytes(b'image')
    started=threading.Event()
    def sweep(host,**kwargs):
        started.set();assert kwargs['cancel'].wait(5)
        return {'status':'cancelled','trials':[],'restored':True}
    monkeypatch.setattr('multisim_native_mcp.jobs.run_sweep',sweep)
    manager=ExperimentManager(Host(),tmp_path/'records')
    job=manager.start([{'ref':'R1','index':1,'values':[1]}],{},[{'id':'m','metric':'mean','signal':'V(1)'}])
    assert started.wait(5)
    assert manager.cancel(job['id'])['requested']
    manager.shutdown()
    persisted=ExperimentManager(None,tmp_path/'records').store.read(job['id'])
    assert persisted['status']=='cancelled' and persisted['result']['restored']


def test_experiment_manager_preserves_live_owner_pid_and_interrupts_dead_pid(tmp_path):
    import os
    store = ExperimentStore(tmp_path)
    live_id = '1' * 32
    dead_id = '2' * 32
    store.write({'id': live_id, 'status': 'running', 'created': 1, 'owner_pid': os.getpid()})
    store.write({'id': dead_id, 'status': 'running', 'created': 1, 'owner_pid': 99999999})
    observer = ExperimentManager(None, tmp_path)
    assert observer.store.read(live_id)['status'] == 'running'
    assert observer.store.read(dead_id)['status'] == 'interrupted'
