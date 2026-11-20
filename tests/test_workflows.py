import copy
import json
import os
import shutil
import subprocess
import threading

import pytest
from pydantic import ValidationError

from multisim_native_mcp.paths import RESOURCE_DIR
from multisim_native_mcp.workflow_contracts import WorkflowPlan
from multisim_native_mcp.workflow_values import resolve
from multisim_native_mcp.workflows import NeedsInput, WorkflowManager, remap_bindings


def circuit(pointer='c1'):
    return {'page':{'width':960,'height':720},'wires':[], 'components':[
        {'id':pointer,'ref':'VCC','local_ref':'VCC','transform':[1,0,0,1,180,180],
         'pins':[{'id':pointer+'p','name':'1','x':180,'y':180,'connections':0}], 'labels':[],
         'parameters':[{'index':0,'value':5}]}]}


class Host:
    def __init__(self,tmp_path):
        self.lock=threading.RLock();self.agent=True;self.state=circuit()
        self.source=None;self.working=tmp_path/'working.ms14';self.working.write_bytes(b'checkpoint')
        self.analysis_started=threading.Event();self.native_call_count=0;self.native_call_seconds=0
    def call(self,operation,args=None):
        self.native_call_count+=1
        if operation=='circuitState':return copy.deepcopy(self.state)
        if operation=='wiringOptions':return args or {}
        raise AssertionError(operation)
    def checkpoint(self):return {'path':str(self.working)}
    def open_copy(self,path):self.agent=True;self.state=circuit('c2')
    def open_recovery(self,checkpoint,document=None):self.open_copy(checkpoint['path'])


@pytest.mark.parametrize('plan',[
    {'steps':[{'id':'a','kind':'edit','operations':[{'operation':'move','arguments':{'ref':{'$ref':'future.component.id'},'dx':9,'dy':0}}]}]},
    {'steps':[{'id':'a','kind':'session','mode':'open'}]},
    {'steps':[{'id':'a','kind':'session','mode':'create'}]},
    {'steps':[{'id':'a','kind':'close'},{'id':'b','kind':'netlist'}]},
    {'steps':[{'id':'a','kind':'analysis','measurements':[],'criteria':[{'id':'missing','target':1}]}]},
    {'steps':[{'id':'a','kind':'analysis','options':{'analysis':'ac','ac_start':100,'ac_stop':10}}]},
])
def test_plan_preflight_rejects_invalid_dependency_or_stage(plan):
    with pytest.raises(ValidationError):WorkflowPlan.model_validate(plan)


def test_result_references_and_bounded_arithmetic():
    b={'r':{'component':{'id':'c1','pins':[{'x':180}]}}}
    assert resolve({'ref':{'$ref':'r.component.id'},'x':{'$add':[{'$ref':'r.component.pins.0.x'},9]}},b)=={'ref':'c1','x':189}
    assert resolve({'$sub':[20,9]},b)==11
    for value in ({'$ref':'r.constructor'},{'$ref':'missing'}, {'$add':[1,True]}):
        with pytest.raises(ValueError):resolve(value,b)


def test_shared_reference_rebinding_uses_unique_geometry():
    before=circuit();second=copy.deepcopy(before['components'][0]);second.update(id='other',transform=[1,0,0,1,540,180]);second['pins']=[{'id':'otherp','name':'1','x':540,'y':180}]
    before['components'].append(second);after=copy.deepcopy(before)
    for i,c in enumerate(after['components']):c['id']='new'+str(i);c['pins'][0]['id']='newpin'+str(i)
    b=remap_bindings({'power':{'component':before['components'][0]}},before,after)
    assert b['power']['component']['id']=='new0'
    after['components'].append(copy.deepcopy(after['components'][0]))
    assert '$invalid_handle' in remap_bindings({'id':'c1'},before,after)['id']
    moved=copy.deepcopy(before);moved['components'][0]['transform'][4]+=9
    assert remap_bindings({'id':'c1'},before,moved)['id']=='c1'


def test_reopen_does_not_trust_reused_addresses_for_identical_power_symbols():
    before=circuit('old1');peer=copy.deepcopy(before['components'][0])
    peer.update(id='old2',transform=[1,0,0,1,540,180]);peer['pins'][0].update(id='old2pin',x=540)
    before['components'].append(peer);before['handle_epoch']=[1,1]
    after=copy.deepcopy(before);after['handle_epoch']=[1,2]
    after['components'][0]['id']='old2';after['components'][1]['id']='old1'
    after['components'][0]['pins'][0]['id']='old2pin';after['components'][1]['pins'][0]['id']='old1pin'
    rebound=remap_bindings({'power':'old1'},before,after)
    assert rebound['power']=='old2'


def test_session_delta_preserves_cache_and_detects_handle_changes(tmp_path):
    h=Host(tmp_path);manager=WorkflowManager(h,tmp_path/'records')
    first=manager.session_state();revision=first['revision']
    assert manager.session_state(revision)=={'revision':revision,'changed':False}
    h.state['components'][0]['parameters'][0]['value']=12
    changed=manager.session_state(revision)
    assert changed['changed'] and not changed['full']
    assert 'parameters' not in changed['components'][0]
    assert manager.cache['components'][0]['parameters'][0]['value']==12
    previous=changed['revision'];h.state['components'][0]['id']='new'
    assert manager.session_state(previous)['changed']


def test_failed_phase_resume_preserves_completed_stages(tmp_path):
    h=Host(tmp_path);manager=WorkflowManager(h,tmp_path/'records');calls=[]
    def stage(s,record):
        calls.append(s['id'])
        if s['id']=='check' and calls.count('check')==1:raise NeedsInput('Choose criteria',{'available':['output']})
        return {'passed':True}
    manager._stage=stage
    plan={'steps':[{'id':'configure','kind':'wiring','connect_touching':False},{'id':'check','kind':'layout'}]}
    failed=manager.start(plan)
    assert failed['status']=='needs_input' and failed['next_step']==1
    assert failed['failure']['details']=={'available':['output']}
    resumed=manager.control(failed['id'],'resume')
    assert resumed['status']=='complete' and calls==['configure','check','check']
    assert resumed['stats']['retries']==1 and resumed['stats']['external_calls']==2


def test_long_wait_cancel_and_revision_conflict(tmp_path):
    h=Host(tmp_path);manager=WorkflowManager(h,tmp_path/'records');entered=threading.Event()
    def stage(s,record):entered.set();assert manager.cancel_event.wait(5);return {'stopped':True}
    manager._stage=stage
    plan={'steps':[{'id':'stage','kind':'wiring','connect_touching':False}]}
    manager._wait_value(100)
    assert manager.active is None
    running=manager.start(plan,wait_timeout=0);assert entered.wait(5)
    cancelled=manager.control(running['id'],'cancel',wait_timeout=5)
    assert cancelled['status']=='cancelled'
    conflict=manager.start({**plan,'expected_revision':'stale'})
    assert conflict['status']=='needs_input' and 'revision' in conflict['error']
    assert h.state==circuit()


def test_restart_marks_interrupted_and_resume_rebinds_saved_alias(tmp_path):
    h=Host(tmp_path);manager=WorkflowManager(h,tmp_path/'records')
    record={'id':'a'*32,'status':'running','plan':{'steps':[{'id':'done','kind':'wiring'},{'id':'check','kind':'layout'}]},
            'next_step':1,'completed':[{'id':'done','kind':'wiring'}], 'bindings':{'done':{},'power':{'component':circuit()['components'][0]}},
            'stats':{'external_calls':1,'retries':0},'events':[],'resume_checkpoint':h.checkpoint()}
    state=manager._capture();record.update(state=state,revision=state['revision']);manager.store.write(record)
    h.agent=False;manager=WorkflowManager(h,tmp_path/'records')
    assert manager.store.read(record['id'])['status']=='interrupted'
    manager._stage=lambda stage,record:{'passed':True}
    result=manager.control(record['id'],'resume')
    assert result['status']=='complete',result
    assert manager.status(record['id'],detail=True)['bindings']['power']['component']['id']=='c2'


def test_output_preflight_happens_before_any_stage(tmp_path):
    h=Host(tmp_path);manager=WorkflowManager(h,tmp_path/'records');called=[]
    manager._stage=lambda s,r:called.append(s['id'])
    existing=tmp_path/'exists.ms14';existing.write_bytes(b'keep')
    result=manager.start({'steps':[{'id':'edit','kind':'wiring'},{'id':'save','kind':'save','output_path':str(existing)}]})
    assert result['status']=='needs_input' and not called and existing.read_bytes()==b'keep'


def test_interactive_workflow_reports_document_configuration_for_subsequent_save(tmp_path):
    h=Host(tmp_path);manager=WorkflowManager(h,tmp_path/'records');calls=[]
    def configure(*args,**kwargs):
        calls.append(kwargs);return {'persisted_in_circuit':True,'saved_to_file':False}
    h.configure_interactive=configure
    h.control_interactive=lambda action,timeout:{'transition_confirmed':True,'action':action}
    result=manager.start({'steps':[{'id':'live','kind':'interactive','time_step':.001,'persist':True}]})
    assert result['status']=='complete' and calls==[{'persist':True}]
    assert result['results']['live']['configuration']['persisted_in_circuit']


def test_packed_native_slice_resolves_bindings_and_stops_before_bad_native_calls():
    source=(RESOURCE_DIR/'editor_agent.js').read_text(encoding='utf-8')
    section=source[source.index('function sequenceValue('):source.index('const editorHandlers=')]
    harness=r'''
const assert=require('node:assert/strict');let calls=[],cancelHandler;const jobs=[];
function recv(type,handler){cancelHandler=handler;}
function send(message){}
const editorHandlers={place:a=>{calls.push(a);return {component:{id:'c'+calls.length,pins:[{x:a.x}]}};}};
function wire(a){calls.push(a);return {id:'wire'};}
function move(a){calls.push(a);return a;}
const source=JSON.parse(require('node:fs').readFileSync(0,'utf8')).source;
eval(source+`
 const first=editSequence({operations:[{operation:'place',bind:'part',arguments:{name:'R',x:180,y:90}},
  {operation:'move',arguments:{ref:{$ref:'part.component.id'},dx:{$sub:[{$ref:'part.component.pins.0.x'},9]},dy:0}}]});
 assert.equal(first.failed,false);assert.deepEqual(calls[1],{ref:'c1',dx:171,dy:0});
 const failed=editSequence({operations:[{operation:'move',arguments:{ref:'c1',dx:'bad',dy:0}}]});
 assert.equal(failed.failed,true);assert.equal(calls.length,2);
 assert.throws(()=>sequenceValue({$ref:'part.constructor'},{part:{}}),/Unresolved/);
 calls=[];
 editorHandlers.place=a=>{calls.push(a);cancelHandler({token:'cancel-me'});return {id:'part'};};
 const cancelled=editSequence({cancel_token:'cancel-me',operations:[
  {operation:'place',arguments:{name:'R',x:180,y:90}},
  {operation:'place',arguments:{name:'R',x:270,y:90}}]});
 assert.equal(cancelled.failed,true);assert.equal(cancelled.failed_operation_index,1);
 assert.match(cancelled.error,/cancelled/);assert.equal(calls.length,1);
 cancelHandler({token:'cancel-me'});
 assert.equal(cancelledEditSequences.size,0);
 const retried=editSequence({cancel_token:'retry',operations:[{operation:'move',arguments:{ref:'c1',dx:9,dy:0}}]});
 assert.equal(retried.failed,false);
`);
console.log('ok');
'''
    result=subprocess.run([shutil.which('node'),'-e',harness],input=json.dumps({'source':section}),text=True,capture_output=True,check=True,timeout=15)
    assert result.stdout.strip()=='ok'


def test_primary_value_preflight_uses_value_slot_and_collects_pin_errors(tmp_path):
    h=Host(tmp_path);manager=WorkflowManager(h,tmp_path/'records')
    from multisim_native_mcp.workflows import digest
    request={'name':'RESISTOR_VIRTUAL','family':'','group':'','manufacturer':''}
    manager.catalog[digest(request)]={'pins':[{'name':'1'},{'name':'2'}],
        'parameters':[{'index':0,'role':'model_option'},{'index':1,'role':'value'}]}
    manager.prepare=lambda requests:None
    ops=[{'operation':'place','bind':'r','arguments':{'name':'RESISTOR_VIRTUAL','value':'1k'}},
         {'operation':'setParameter','arguments':{'ref':{'$ref':'r.component.id'},'role':'value','value':2200}}]
    manager._preflight_edits(ops,{})
    assert ops[0]['arguments']['parameters']==[{'index':1,'expression':'1k'}]
    assert ops[1]['arguments']['index']==1
    invalid=[{'operation':'place','bind':'r','arguments':{'name':'RESISTOR_VIRTUAL','anchor':'pin','pin':'bad'}},
             {'operation':'wire','arguments':{'source':{'ref':{'$ref':'r.component.id'},'pin':'also_bad'}}}]
    with pytest.raises(NeedsInput) as error:manager._preflight_edits(invalid,{})
    assert len(error.value.result['issues'])==2


def test_existing_component_selection_is_unique_and_address_independent(tmp_path):
    h=Host(tmp_path);manager=WorkflowManager(h,tmp_path/'records');manager.cache=copy.deepcopy(h.state)
    other=copy.deepcopy(h.state['components'][0]);other.update(id='second',transform=[1,0,0,1,540,180]);other['pins'][0].update(id='secondpin',x=540)
    manager.cache['components'].append(other)
    record={'bindings':{}}
    selected=manager._stage({'id':'select','kind':'select','components':{'supply':{'ref':'VCC','pin':'1','x':540,'y':180}}},record)
    assert selected['components']['supply']['id']=='second'
    with pytest.raises(NeedsInput):manager._stage({'id':'select','kind':'select','components':{'supply':{'ref':'VCC'}}},record)


def test_runtime_budget_cancels_at_a_supported_boundary(tmp_path):
    h=Host(tmp_path);manager=WorkflowManager(h,tmp_path/'records')
    def stage(s,r):assert manager.cancel_event.wait(5);return {'stopped':True}
    manager._stage=stage
    result=manager.start({'max_runtime':.05,'steps':[{'id':'stage','kind':'wiring'}]},wait_timeout=5)
    assert result['status']=='cancelled' and result['error']=='Requested workflow runtime reached'


def test_native_edit_slices_keep_bindings_local_and_one_undo_checkpoint(tmp_path):
    from multisim_native_mcp.service import EditorService
    h=EditorService();seen=[];checkpoint={'path':str(tmp_path/'checkpoint.ms14')}
    h.checkpoint=lambda:checkpoint
    def call(op,args=None):
        if op=='simulationInfo':return {'state':0}
        if op=='markModified':return {}
        assert op=='editSequence';seen.append(copy.deepcopy(args));bindings=dict(args['bindings']);results=[]
        for edit in args['operations']:
            a=resolve(edit['arguments'],bindings);value={'id':a.get('ref','native-text')}
            results.append(value)
            if edit.get('bind'):bindings[edit['bind']]=value
        return {'failed':False,'results':results,'bindings':bindings}
    h.call=call
    ops=[{'operation':'addText','bind':'first','arguments':{'text':'test','x':0,'y':0}}]
    ops += [{'operation':'addText','arguments':{'text':'test','x':n,'y':0}} for n in range(7)]
    ops += [{'operation':'move','arguments':{'ref':{'$ref':'first.id'},'dx':9,'dy':0}}]
    result=h.edit_sequence(ops,{'large_analysis':{'unneeded':[0]*1000}})
    assert len(seen)==2 and seen[0]['bindings']=={} and set(seen[1]['bindings'])=={'first'}
    assert 'large_analysis' in result['bindings'] and len(h.undo_stack)==1


def test_resume_rebinds_from_job_state_after_an_external_state_read(tmp_path):
    h=Host(tmp_path);manager=WorkflowManager(h,tmp_path/'records')
    def stage(s,r):
        if not r.get('retried'):
            r['bindings']['power']={'component':copy.deepcopy(h.state['components'][0])}
            r['retried']=True;raise NeedsInput('Select a criterion')
        return {'passed':True}
    manager._stage=stage
    failed=manager.start({'steps':[{'id':'check','kind':'layout'}]})
    h.state=circuit('new')
    current=manager.session_state()
    result=manager.control(failed['id'],'resume',expected_revision=current['revision'])
    assert result['status']=='complete',result
    assert manager.status(result['id'],detail=True)['bindings']['power']['component']['id']=='new'


def test_a_second_client_does_not_interrupt_a_live_owner(tmp_path):
    manager=WorkflowManager(Host(tmp_path),tmp_path/'records')
    record={'id':'b'*32,'status':'running','owner_pid':os.getpid()}
    manager.store.write(record)
    observer=WorkflowManager(None,tmp_path/'records')
    assert observer.store.read(record['id'])['status']=='running'


def test_record_write_failure_releases_waiters_and_execution_slot(tmp_path):
    h=Host(tmp_path);manager=WorkflowManager(h,tmp_path/'records');write=manager.store.write;calls=[]
    def failing(record):
        calls.append(record['id'])
        if len(calls)>1:raise OSError('storage unavailable')
        return write(record)
    manager.store.write=failing
    result=manager.start({'steps':[{'id':'stage','kind':'wiring'}]})
    assert result['status']=='failed' and manager.active is None and manager.finished.is_set()
    assert 'storage unavailable' in manager.status(result['id'])['persistence_error']


def test_cancel_is_posted_without_waiting_for_the_editor_lock(tmp_path):
    from types import SimpleNamespace
    from multisim_native_mcp.service import EditorService
    h=EditorService();messages=[];h.agent=SimpleNamespace(post=messages.append)
    h._active_edit_sequence='active-token'
    manager=WorkflowManager(h,tmp_path/'records');manager.active='workflow'
    manager.record={'status':'running'}
    with h.lock:
        thread=threading.Thread(target=manager._request_cancel,args=('workflow','User cancelled'))
        thread.start();thread.join(1)
        assert not thread.is_alive()
    assert manager.cancel_event.is_set()
    assert messages==[{'type':'cancel-edit-sequence','token':'active-token'}]
    h.agent=None


def test_cancel_during_component_preparation_restores_and_skips_later_parts(tmp_path):
    h=Host(tmp_path);manager=WorkflowManager(h,tmp_path/'records');manager.active='workflow'
    original=h.call;calls=[];restored=[];h.restore=lambda snapshot:restored.append(snapshot)
    def call(op,args=None):
        calls.append(op)
        if op=='wiringOptions':return {'connect_touching':False}
        if op=='librarySearch':return {'results':[{'Component_Name':args['query']}]}
        if op=='place':
            manager.cancel_event.set()
            return {'component':{'pins':[]},'placement':{'actual':{'x':180,'y':180}},'parameters':[]}
        return original(op,args)
    h.call=call
    with pytest.raises(InterruptedError,match='component preparation'):
        manager.prepare([{'name':'FIRST'},{'name':'SECOND'}])
    assert calls.count('place')==1 and calls.count('librarySearch')==1
    assert len(restored)==1 and calls[-2:]==['wiringOptions','circuitState']


def test_cancelled_native_slice_rolls_back_one_stage_and_clears_token(tmp_path):
    from multisim_native_mcp.service import EditorService,NativeEditError
    h=EditorService();checkpoint={'path':str(tmp_path/'checkpoint.ms14')};restored=[]
    h.checkpoint=lambda:checkpoint;h.restore=lambda value:restored.append(value)
    def call(op,args=None):
        if op=='simulationInfo':return {'state':0}
        assert op=='editSequence' and args['cancel_token']==h._active_edit_sequence
        return {'failed':True,'failed_operation_index':1,'error':'Workflow cancelled between native edit operations'}
    h.call=call
    with pytest.raises(NativeEditError,match='cancelled') as error:
        h.edit_sequence([{'operation':'addText','arguments':{'text':'test','x':0,'y':0}}]*2,{})
    assert error.value.details['rolled_back'] and restored==[checkpoint]
    assert not h.undo_stack and h._active_edit_sequence is None


def test_hexadecimal_workflow_capture_normalizes_lowercase_digits():
    from multisim_native_mcp.workflow_contracts import Capture
    assert Capture(output_path='display.png', expected_digit='f').expected_digit == 'F'
    with pytest.raises(ValueError):
        Capture(output_path='display.png', expected_digit='G')


def test_select_sheet_export_capture_dc_options_manufacturer_cancel_and_intra_stage_preflight(tmp_path):
    # 1. SelectSheetStage, ExportStage, Capture, DC AnalysisOptions, ComponentSelector validation
    plan = WorkflowPlan.model_validate({
        'steps': [
            {'id': 'sheet_idx', 'kind': 'select_sheet', 'index': 0},
            {'id': 'sheet_title', 'kind': 'select_sheet', 'title': 'Child'},
            {'id': 'sel', 'kind': 'select', 'components': {'pwr': {'component_ref': 'VCC', 'pin': '1', 'x': 180, 'y': 180}}},
            {'id': 'fit', 'kind': 'edit', 'operations': [{'operation': 'native_fit_sheet', 'arguments': {'margin': 18}}]},
            {
                'id': 'dc',
                'kind': 'analysis',
                'options': {'analysis': 'dc', 'dc_source': 'V1', 'dc_start': 0.0, 'dc_stop': 5.0, 'dc_step': 1.0},
                'measurements': [{'id': 'vmid', 'metric': 'value_at', 'signal': {'component_ref': 'R1', 'pin': '2'}, 'at': 2.5}],
                'criteria': [{'id': 'vmid', 'target': 1.25}],
            },
            {
                'id': 'exp',
                'kind': 'export',
                'output_path': str(tmp_path / 'crop.png'),
                'scale': 1.5,
                'region': {'left': 0, 'top': 0, 'right': 200, 'bottom': 150},
                'padding': 9,
            },
            {
                'id': 'live',
                'kind': 'interactive',
                'captures': [
                    {
                        'output_path': str(tmp_path / 'cap.png'),
                        'dpi': 96,
                        'scale': 2.0,
                        'fit_content': True,
                        'padding': 12,
                        'show_frame': True,
                        'show_grid': True,
                    }
                ],
            },
        ]
    })
    assert plan.steps[2].components['pwr'].ref == 'VCC'

    for invalid_step in [
        {'id': 's', 'kind': 'select_sheet'},
        {'id': 's', 'kind': 'select_sheet', 'index': 0, 'title': 'A'},
        {'id': 's', 'kind': 'select_sheet', 'index': True},
        {'id': 's', 'kind': 'export', 'output_path': str(tmp_path / 'a.png'), 'fit_content': True, 'region': {'left': 0, 'top': 0, 'right': 10, 'bottom': 10}},
        {'id': 's', 'kind': 'analysis', 'options': {'analysis': 'dc', 'dc_source': 'V1', 'dc_start': 0.0, 'dc_stop': 5.0, 'dc_step': -1.0}},
    ]:
        with pytest.raises(ValidationError):
            WorkflowPlan.model_validate({'steps': [invalid_step]})

    # 2. select_sheet execution by index, sheet_id, unique title, and ambiguous title error while preserving bindings
    h = Host(tmp_path)
    sheets_list = [
        {'index': 0, 'id': 'sh0', 'title': 'Main', 'selected': True},
        {'index': 1, 'id': 'sh1', 'title': 'Child', 'selected': False},
        {'index': 2, 'id': 'sh2', 'title': 'Dup', 'selected': False},
        {'index': 3, 'id': 'sh3', 'title': 'Dup', 'selected': False},
    ]
    selected_calls = []

    def sheet_call(op, args=None):
        if op == 'sheets':
            return sheets_list
        if op == 'selectSheet':
            selected_calls.append(args['index'])
            return {'index': args['index'], 'selected': True}
        if op == 'circuitState':
            return circuit('c_other_sheet')
        if op == 'signalForPin':
            return {'signal': f"V({args['ref']}_{args['pin']})"}
        if op == 'librarySearch':
            selected_calls.append(('search', args.get('manufacturer')))
            return {
                'results': [
                    {'Component_Name': 'LM358N', 'Manufacturer_Name': 'TI'},
                    {'Component_Name': 'LM358N', 'Manufacturer_Name': 'ON Semi'},
                ]
            }
        if op == 'place':
            return {'component': {'pins': [{'name': '1', 'x': 180, 'y': 180}]}, 'placement': {'actual': {'x': 180, 'y': 180}}, 'parameters': []}
        if op == 'wiringOptions':
            return {'connect_touching': False}
        raise AssertionError(op)

    h.call = sheet_call
    h.restore = lambda s: None
    manager = WorkflowManager(h, tmp_path / 'records')
    rec = {'bindings': {'saved_part': {'component': {'id': 'c1'}}}}
    assert manager._stage({'id': 's1', 'kind': 'select_sheet', 'title': 'Child'}, rec)['index'] == 1
    assert manager._stage({'id': 's2', 'kind': 'select_sheet', 'sheet_id': 'sh0'}, rec)['index'] == 0
    assert rec['bindings']['saved_part']['component']['id'] == 'c1'
    with pytest.raises(NeedsInput, match='exactly one sheet'):
        manager._stage({'id': 's3', 'kind': 'select_sheet', 'title': 'Dup'}, rec)

    # _signal component_ref alias
    assert manager._signal({'component_ref': 'R1', 'pin': '2'}) == 'V(R1_2)'
    with pytest.raises(ValueError, match='Conflicting'):
        manager._signal({'ref': 'R1', 'component_ref': 'R2', 'pin': '2'})

    # prepare() forwards manufacturer to librarySearch and filters Manufacturer_Name
    prep = manager.prepare([{'name': 'LM358N', 'manufacturer': 'TI'}], refresh=True)
    assert ('search', 'TI') in selected_calls and prep['prepared'] == 1

    # 3. Intra-stage copy/replace setParameter + named params + $add dict value in _preflight_edits
    from multisim_native_mcp.workflows import digest
    req = {'name': 'CLOCK_VOLTAGE', 'family': '', 'group': '', 'manufacturer': ''}
    manager.catalog[digest(req)] = {
        'pins': [{'name': '1'}, {'name': '2'}],
        'parameters': [
            {'index': 0, 'role': 'model_option'},
            {'index': 1, 'name': 'frequency', 'role': 'value'},
            {'index': 5, 'name': 'voltage'},
        ],
    }
    manager.prepare = lambda requests: None
    intra_ops = [
        {'operation': 'place', 'bind': 'clk', 'arguments': {'name': 'CLOCK_VOLTAGE', 'params': {'frequency': '2k', 'voltage': 5}}},
        {'operation': 'place', 'bind': 'clk2', 'arguments': {'name': 'CLOCK_VOLTAGE', 'value': {'$add': [1000, 500]}}},
        {'operation': 'copy', 'bind': 'copied_clk', 'arguments': {'ref': {'$ref': 'clk.component.id'}, 'new_ref': 'V2', 'x': 270, 'y': 90}},
        {'operation': 'setParameter', 'arguments': {'ref': {'$ref': 'copied_clk.component.id'}, 'value': 4000}},
        {'operation': 'setParameter', 'arguments': {'ref': {'$ref': 'clk.component.id'}, 'name': 'voltage', 'value': 3.3}},
    ]
    manager._preflight_edits(intra_ops, {})
    assert intra_ops[1]['arguments']['value'] == {'$add': [1000, 500]}
    assert 'index' not in intra_ops[3]['arguments'] and intra_ops[3]['arguments']['role'] == 'value'
    assert intra_ops[4]['arguments']['index'] == 5

    # 4. Cancelled workflow clears stale failure dict in _execute() finally:
    h2 = Host(tmp_path)
    mgr2 = WorkflowManager(h2, tmp_path / 'records2')

    def cancel_and_raise(s, r):
        mgr2.cancel_event.set()
        raise RuntimeError('transient failure during cancellation')

    mgr2._stage = cancel_and_raise
    cancelled_res = mgr2.start({'steps': [{'id': 'w', 'kind': 'wiring'}]})
    assert cancelled_res['status'] == 'cancelled' and 'failure' not in cancelled_res

    # 5. Interactive capture forwards render options and checks overwrite on expected_digit
    h3 = Host(tmp_path)
    h3.configure_interactive = lambda *a, **kw: {'configured': True}
    h3.control_interactive = lambda action, timeout: {'transition_confirmed': True, 'action': action}
    h3.interactive_status = lambda: {'state_name': 'running'}
    capture_kwargs = []

    def fake_export_interactive(out_p, overwrite=False, *a, **kw):
        capture_kwargs.append(kw)
        from pathlib import Path
        Path(out_p).write_bytes(b'png')
        return {'path': out_p, 'display_states': [{'ref': 'DS1', 'decoded': '5'}], 'capture_mode': 'instantaneous'}

    h3.export_interactive_image = fake_export_interactive
    mgr3 = WorkflowManager(h3, tmp_path / 'records3')
    mgr3.cache = {'components': [{'id': 'ds_id', 'ref': 'DS1', 'pins': []}]}
    cap_out = tmp_path / 'digit5.png'
    cap_res = mgr3._stage(
        {
            'id': 'live',
            'kind': 'interactive',
            'overwrite': False,
            'captures': [{'output_path': str(cap_out), 'active_component': 'DS1', 'expected_digit': '5', 'dpi': 192, 'scale': 1.5, 'show_grid': True}],
        },
        {'id': 'a' * 32, 'bindings': {}},
    )
    assert cap_res['passed'] and cap_out.is_file()
    assert capture_kwargs[-1]['dpi'] == 192 and capture_kwargs[-1]['scale'] == 1.5 and capture_kwargs[-1]['show_grid'] is True
    with pytest.raises(FileExistsError):
        mgr3._stage(
            {
                'id': 'live2',
                'kind': 'interactive',
                'overwrite': False,
                'captures': [{'output_path': str(cap_out), 'active_component': 'DS1', 'expected_digit': '5'}],
            },
            {'id': 'a' * 32, 'bindings': {}},
        )
