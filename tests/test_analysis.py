import json
import threading
import pytest
from multisim_native_mcp.service import EditorService
from multisim_native_mcp.waveforms import parse_raw, summarize, export_csv


def test_complex_and_digital_plots(tmp_path):
    raw=tmp_path/'mixed.raw'
    raw.write_text('''Title: RC
Plotname: AC Analysis
Flags: complex
No. Variables: 2
No. Points: 1
Variables:
0 frequency frequency
1 n2 voltage V(2)
Values:
0 100,0
0.5,-0.5

Plotname: Transient Analysis Digital Node
DigitalFlags: Yes
Flags: real
No. Variables: 2
No. Points: 2
Variables:
0 time time
1 n3 voltage D(3)
Values:
0,0,0
0.001,1,0
''')
    data=parse_raw(raw)
    assert data['additional_plots'][0]['rows'][1]==[0.001,1,0]
    assert summarize(data)[1]['max']==pytest.approx(2**-.5)
    csv=tmp_path/'ac.csv';export_csv(data,csv)
    assert 'V(2).imag' in csv.read_text(encoding='utf-8-sig')


def test_failure_records_stage_without_export(tmp_path):
    host=EditorService();host.working=tmp_path/'working.ms14'
    host.netlist=lambda: {'failed':False,'handles_invalidated':False}
    calls=[]
    def call(op,args):
        calls.append(op)
        return {'failed':True,'stage':'load-netlist','trace':[{'stage':'load-netlist','errors':[{'code':4}]}]}
    host.call=call
    with pytest.raises(RuntimeError,match='load-netlist'):host.run_analysis()
    assert calls==['simulate']
    record=json.loads(next(tmp_path.glob('analysis-*.json')).read_text())
    assert record['status']=='failed' and record['native']['trace'][0]['errors']


def test_netlist_failure_is_also_persisted(tmp_path):
    host=EditorService();host.working=tmp_path/'working.ms14'
    host.netlist=lambda:{'failed':True,'messages':'floating pin','content':'native source'}
    with pytest.raises(RuntimeError,match='floating pin'):host.run_analysis()
    record=json.loads(next(tmp_path.glob('analysis-*.json')).read_text())
    assert record['status']=='failed' and record['netlist']['messages']=='floating pin'


@pytest.mark.parametrize('options',[
    {'ac_sweep':'dec;quit'}, {'ac_points':0}, {'ac_start':0}, {'ac_stop':float('inf')},
    {'use_initial_conditions':True},
])
def test_invalid_ac_sweeps(options):
    with pytest.raises(ValueError):EditorService().run_analysis('ac',**options)


def test_run_analysis_forwards_invalidated_handles_and_supports_dc_sweep(tmp_path):
    host = EditorService()
    host.working = tmp_path / 'working.ms14'
    host.netlist = lambda: {
        'failed': False,
        'handles_invalidated': True,
        'handle_generation': 7,
        'id_map': {'old_c1': 'new_c1'},
        'unresolved_ids': ['old_txt'],
        'state': {'components': [{'id': 'new_c1', 'ref': 'V1'}], 'wires': []},
    }
    captured = {}

    def call(op, args=None):
        captured[op] = args
        if op == 'simulate':
            return {'failed': False, 'command': 'dc vV1 0 5 2.5'}
        if op == 'simulationExport':
            from pathlib import Path
            Path(args['path']).write_text(
                'Title: DC Divider\n'
                'Plotname: DC Transfer Characteristic\n'
                'Flags: real\n'
                'No. Variables: 2\n'
                'No. Points: 3\n'
                'Variables:\n'
                '0 v1 voltage vv1 voltage (v)\n'
                '1 n2 voltage V(out)\n'
                'Values:\n'
                '0 0\n0\n'
                '1 2.5\n1.25\n'
                '2 5\n2.5\n',
                encoding='utf-8',
            )
            return {'result': 0}
        raise AssertionError(op)

    host.call = call
    res = host.run_dc_sweep('V1', 0.0, 5.0, 2.5)
    assert captured['simulate']['analysis'] == 'dc'
    assert captured['simulate']['dc_source'] == 'V1'
    assert res['handles_invalidated'] is True
    assert res['handle_generation'] == 7
    assert res['id_map'] == {'old_c1': 'new_c1'}
    assert res['unresolved_ids'] == ['old_txt']
    assert res['state']['components'][0]['id'] == 'new_c1'
    assert res['points'] == 3


def test_netlist_topology_refresh_maps_identities_across_all_sheets(tmp_path):
    host = EditorService()
    host.topology_dirty = True
    host.handle_generation = 3
    before_states = [
        {
            'sheet_index': 0,
            'components': [{'id': 's0_old', 'ref': 'R1', 'local_ref': 'R1', 'transform': [1, 0, 0, 1, 90, 90], 'pins': []}],
            'wires': [],
        },
        {
            'sheet_index': 1,
            'components': [{'id': 's1_old', 'ref': 'R2', 'local_ref': 'R2', 'transform': [1, 0, 0, 1, 180, 90], 'pins': []}],
            'wires': [],
        },
    ]
    after_states = [
        {
            'sheet_index': 0,
            'components': [{'id': 's0_new', 'ref': 'R1', 'local_ref': 'R1', 'transform': [1, 0, 0, 1, 90, 90], 'pins': []}],
            'wires': [],
        },
        {
            'sheet_index': 1,
            'components': [{'id': 's1_new', 'ref': 'R2', 'local_ref': 'R2', 'transform': [1, 0, 0, 1, 180, 90], 'pins': []}],
            'wires': [],
        },
    ]
    state_calls = []

    def call(op, args=None):
        if op == 'simulationInfo':
            return {'state': 0}
        if op == 'projectCircuitState':
            state_calls.append(1)
            return {'states': before_states if len(state_calls) == 1 else after_states}
        if op == 'netlist':
            return {'failed': False, 'content': '* clean netlist\n'}
        raise AssertionError(op)

    host.call = call
    host.checkpoint = lambda: {'path': str(tmp_path / 'ckpt.ms14'), 'sheet_index': 1}
    host.restore = lambda ckpt: setattr(host, 'topology_dirty', False) or setattr(host, 'handle_generation', 4) or {}
    out = host.netlist()
    assert out['handles_invalidated'] is True
    assert out['id_map'] == {'s0_old': 's0_new', 's1_old': 's1_new'}
    assert out['state']['sheet_index'] == 1


def test_restore_restarts_only_owned_processes_with_numeric_context():
    host = EditorService()
    host.numeric_session_used = True
    calls = []
    checkpoint = {'path': 'checkpoint.ms14'}
    host.call = lambda operation, args: calls.append((operation, args)) or {}
    host._restart_from_checkpoint = lambda args: calls.append(('restart', args)) or {'host_restarted': True}

    host.owned = True
    assert host.restore(checkpoint)['host_restarted']
    host.owned = False
    host.restore(checkpoint)

    assert calls == [('restart', checkpoint), ('restoreSnapshot', checkpoint)]


def test_resolve_signal_rejects_unresolved_id_and_remaps_rebound_id():
    host = EditorService()
    host.topology_dirty = True
    calls = []
    host.netlist = lambda: (
        setattr(host, 'topology_dirty', False)
        or {
            'failed': False,
            'handles_invalidated': True,
            'handle_generation': 5,
            'id_map': {'0xold_ok': '0xnew_ok'},
            'unresolved_ids': ['0xold_gone'],
        }
    )
    host.call = lambda op, args=None: calls.append((op, args)) or {'signal': f"V({args['ref']}_{args['pin']})"}

    with pytest.raises(ValueError, match='could not be rebound'):
        host.resolve_signal('0xold_gone', '1')
    assert calls == []

    host.topology_dirty = True
    resolved = host.resolve_signal('0xold_ok', '2')
    assert resolved['signal'] == 'V(0xnew_ok_2)'
    assert resolved['handles_invalidated'] is True
    assert resolved['handle_generation'] == 5
    assert calls == [('signalForPin', {'ref': '0xnew_ok', 'pin': '2'})]
