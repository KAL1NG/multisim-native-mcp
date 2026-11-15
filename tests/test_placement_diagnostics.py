import json
import shutil
import subprocess

import pytest

from multisim_native_mcp.layout import check_layout
from multisim_native_mcp.netlist_diagnostics import hidden_power_diagnostics,explain_analysis_failure
from multisim_native_mcp.paths import RESOURCE_DIR
from multisim_native_mcp.service import EditorService


@pytest.mark.parametrize('rail,bridge',[('VSS','CMOS_RCV__NON__1'),('VDD','CMOS_DRV__NON__1'),('VCC','TTL_RCV'),('GND','TTL_DRV')])
def test_implicit_power_scan_ignores_subcircuits_and_global_declarations(rail,bridge):
    text=f'''* power diagnostics
.global {rail}
xU2.MR 0 dU2.MR
+ VDD {rail} {bridge}
.subckt local {rail} 0
Vinternal {rail} 0 5
.ends local
'''
    parts=[{'ref':'U2','library':{'name':'counter'}}]
    found=hidden_power_diagnostics(text,parts)
    issue=next(d for d in found if d['node']==rail)
    assert issue['components']==[{'ref':'U2','name':'counter'}]
    assert 'counter' in issue['message'] and rail in issue['message']
    fixed=hidden_power_diagnostics(text+f'Vrail {rail} 0 0\nVdd VDD 0 5')
    assert not fixed


def test_no_hidden_rail_inference_from_model_names_or_local_nodes():
    assert not hidden_power_diagnostics('xU1 1 2 VDD_CUSTOM\n.model VSS D\n* VCC VSS\n')
    assert not hidden_power_diagnostics('xU1 1 VSS custom_supply\nxU2.MR 0 1 VDD VSS CMOS_RCV__NON__1\nV1 VDD 0 5')


def test_implicit_rail_with_passive_island_or_capacitor_only_is_floating():
    bridge='xU2.MR 0 1 VDD VSS CMOS_RCV__NON__1\nV1 VDD 0 5\n'
    for connection in ('R1 VSS isolated 1k','C1 VSS 0 1u','I1 VSS 0 1m'):
        found=hidden_power_diagnostics(bridge+connection)
        assert len(found)==1 and found[0]['reason']=='floating_dc_network'
    assert not hidden_power_diagnostics(bridge+'R1 VSS a 1k\nR2 a 0 1k')


def test_failed_analysis_enriches_empty_text_without_inventing_error_enum_names():
    error={'index':3,'command':4,'code':3}
    raw={'error_text':'','stage':'analysis','errors':[error],'trace':[{'stage':'analysis','command':'tran .001 1','errors':[error]}]}
    diagnostics=hidden_power_diagnostics('xU2.MR 0 1 VDD VSS CMOS_RCV__NON__1\nV1 VDD 0 5')
    result=explain_analysis_failure(raw,diagnostics,'tran',False)
    assert 'VSS' in result['error_text'] and 'command id 4' in result['error_text']
    assert result['error_details'][0]['contexts']==[{'stage':'analysis','command':'tran .001 1'}]
    assert result['hints'] and result['error_details'][0]['code']==3
    assert not explain_analysis_failure(raw,[],'tran',True)['hints']
    assert 'tran .001 1' in explain_analysis_failure(raw,[],'tran',False)['error_text']


def test_missing_hidden_rail_stops_before_solver_and_records_readable_reason(tmp_path):
    h=EditorService();h.working=tmp_path/'circuit.ms14'
    diagnostics=hidden_power_diagnostics('xU2.MR 0 1 VDD VSS CMOS_RCV__NON__1\nV1 VDD 0 5')
    h.netlist=lambda:{'failed':False,'diagnostics':diagnostics}
    h.call=lambda *args:pytest.fail('A known missing power rail must not enter the native solver')
    with pytest.raises(RuntimeError,match='U2.*VSS'):h.run_analysis('tran')
    record=json.loads(next(tmp_path.glob('analysis-*.json')).read_text())
    assert record['native']['stage']=='power-rail-preflight' and record['native']['error_text']
    assert record['status']=='failed'


def test_native_empty_failure_text_is_enriched_in_persisted_diagnostics(tmp_path):
    h=EditorService();h.working=tmp_path/'circuit.ms14'
    h.netlist=lambda:{'failed':False,'diagnostics':[]}
    error={'index':4,'command':1,'code':20}
    h.call=lambda *args:{'failed':True,'stage':'analysis','error_text':'','errors':[error],
                          'trace':[{'stage':'analysis','command':'op','errors':[error]}]}
    with pytest.raises(RuntimeError,match="executing 'op'"):h.run_analysis()
    record=json.loads(next(tmp_path.glob('analysis-*.json')).read_text())
    assert record['native']['error_details'][0]['code']==20
    assert record['native']['error_text']


def test_floating_dc_rail_is_advisory_for_uic_runs(tmp_path):
    h=EditorService();h.working=tmp_path/'circuit.ms14'
    diagnostics=hidden_power_diagnostics('xU2.MR 0 1 VDD VSS CMOS_RCV__NON__1\nV1 VDD 0 5\nC1 VSS 0 1u IC=0')
    assert diagnostics[0]['reason']=='floating_dc_network'
    h.netlist=lambda:{'failed':False,'diagnostics':diagnostics}
    calls=[]
    def call(op,args):
        calls.append(op);return {'failed':True,'stage':'analysis','error_text':'test solver failure'}
    h.call=call
    with pytest.raises(RuntimeError,match='Native analysis failed at analysis'):h.run_analysis('tran',use_initial_conditions=True)
    assert calls==['simulate']


def test_layout_separates_body_and_labels_including_attached_wires():
    def box(l,t,r,b):return dict(left=l,top=t,right=r,bottom=b)
    a={'id':'a','ref':'U1','pins':[],'body_bounds':box(0,0,20,20),'bounds':box(0,0,60,40),
       'labels':[{'id':'label','kind':'value','text':'LM555CM','bounds':box(25,25,60,40)}]}
    b={'id':'b','ref':'X2','pins':[],'body_bounds':box(50,25,70,40),'bounds':box(50,25,70,40),'labels':[]}
    w={'id':'wire','source':{'id':'p','ref':'U1','component_id':'a','x':30,'y':20},'target':{'id':'j','x':30,'y':50},
       'points':[{'x':30,'y':20},{'x':30,'y':50}]}
    issues=check_layout([a,b],[w])['issues']
    assert {i['kind'] for i in issues}=={'label_overlap','wire_overlaps_label'}
    assert all(i['collision_target']=='label' and i['suggestion']=='move_component_label' for i in issues)
    b['body_bounds']=box(10,10,30,30)
    assert any(i['kind']=='component_overlap' and i['collision_target']=='body' for i in check_layout([a,b],[])['issues'])


@pytest.mark.parametrize('args',[
    {'angle':float('nan')},{'angle':True},{'mirror_axis':'diagonal'},{'value':1,'expression':'1u'},
    {'expression':''},{'expression':1},{'value':float('inf')},{'value':True},
])
def test_placement_options_validate_before_native_mutation(args):
    with pytest.raises(ValueError):EditorService.validate('place',{'name':'CAPACITOR_VIRTUAL','x':0,'y':0,**args})


def test_standalone_placement_forwards_inline_arguments(monkeypatch):
    from multisim_native_mcp import server
    calls=[]
    monkeypatch.setattr(server.host,'edit',lambda op,args:calls.append((op,args)) or {})
    server.native_place_component('CAPACITOR_VIRTUAL',180,180,angle=-90,mirror_axis='horizontal',expression='1u',anchor='pin',pin='1')
    assert calls[0][1]['angle']==-90 and calls[0][1]['expression']=='1u'


def test_same_path_reuse_checks_native_selected_document_and_keeps_unsaved_state(tmp_path):
    source=tmp_path/'source.ms14';source.write_bytes(b'unchanged')
    h=EditorService();h.source=h.working=source;h.isolated=False
    class Process:
        def poll(self):return None
    h.process=Process();calls=[]
    def call(op,args=None):
        calls.append(op);assert op=='inspect'
        return {'projectPath':str(source),'modified':True}
    h.call=call
    result=h.open_circuit(str(source))
    assert result['reused'] and result['modified'] and not result['handles_invalidated']
    assert calls==['inspect'] and source.read_bytes()==b'unchanged'
    h.isolated=True
    with pytest.raises(RuntimeError,match='close'):h.open_circuit(str(source))
    h.isolated=False;h.call=lambda *a:{'projectPath':str(tmp_path/'other.ms14')}
    with pytest.raises(RuntimeError,match='close'):h.open_circuit(str(source))
    h.process=None


def test_engineering_format_preserves_small_values_and_spice_mega_case():
    source=(RESOURCE_DIR/'editor_agent.js').read_text(encoding='utf-8')
    source=source[source.index('function engineeringExpression('):source.index('function allocateObject(')]
    harness='''const assert=require('node:assert/strict');
    const source=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
    eval(source+`\nassert.equal(engineeringExpression(1e-6),'1u');
    assert.equal(engineeringExpression(1e-8),'10n');
    assert.equal(engineeringExpression(10000),'10k');
    assert.equal(engineeringExpression(1e6),'1Meg');
    assert.equal(engineeringExpression(-.00022),'-220u');
    assert.equal(engineeringExpression(0),'0');`);'''
    done=subprocess.run([shutil.which('node'),'-e',harness],input=json.dumps(source),text=True,capture_output=True)
    assert done.returncode==0,done.stderr
