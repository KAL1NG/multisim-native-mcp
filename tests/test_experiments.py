import threading
import pytest
from multisim_native_mcp.experiments import run_sweep,validate_spec


class FakeHost:
    def __init__(self):self.lock=threading.RLock();self.value=10;self.restored=False
    def call(self,op,args):
        if op=='parameters':return {'parameters':[{'index':1,'value':self.value}]}
        self.value=args['value'];self.restored=self.value==10
    def checkpoint(self):return {'path':'checkpoint','value':self.value}
    def restore(self,c):self.value=c['value'];self.restored=True
    def validate(self,*a):pass
    def run_analysis(self,**a):raise RuntimeError('convergence failure')


def test_failed_trials_restore_original_parameters():
    host=FakeHost()
    r=run_sweep(host,[{'ref':'R1','index':1,'values':[1,2]}],{'analysis':'op'},[{'id':'v','metric':'mean','signal':'V(1)'}])
    assert r['status']=='failed' and len(r['trials'])==2 and r['restored']
    assert host.value==10 and host.restored


def test_cancel_before_first_trial_also_restores():
    host=FakeHost();cancel=threading.Event();cancel.set()
    r=run_sweep(host,[{'ref':'R1','index':1,'values':[1,2]}],{},[{'metric':'mean','signal':'V(1)'}],cancel=cancel)
    assert r['status']=='cancelled' and r['trials']==[] and host.restored


def test_bound_cartesian_product_before_native_changes():
    assert validate_spec([{'ref':r,'index':1,'values':list(range(11))} for r in ['R1','R2']],{},[{'metric':'mean','signal':'V(1)'}],[],None)==121


def test_sweep_aliases_named_slots_empty_expression_restoration_and_id_remapping(tmp_path):
    raw_path = tmp_path / 'dc.raw'
    raw_path.write_text(
        'Plotname: DC Transfer Characteristic\n'
        'Flags: real\n'
        'No. Variables: 2\n'
        'No. Points: 2\n'
        'Variables:\n'
        '0 v1 voltage vv1 voltage (v)\n'
        '1 n2 voltage V(out)\n'
        'Values:\n'
        '0 0.0\n0.0\n'
        '1 5.0\n2.5\n',
        encoding='utf-8',
    )

    class RemapHost:
        def __init__(self):
            self.lock = threading.RLock()
            self.set_calls = []
            self.current_id = 'cid_old'
            self.sim_state = 0

        def call(self, op, args=None):
            if op == 'simulationInfo':
                return {'state': self.sim_state}
            if op == 'parameters':
                assert args['ref'] == 'cid_old'
                return {
                    'ci': '0x1234',
                    'parameters': [
                        {'index': 0, 'value': 0, 'expression': '0', 'role': 'model_option'},
                        {'index': 1, 'value': 2200.0, 'expression': '', 'name': 'resistance', 'role': 'value'},
                    ],
                }
            if op == 'setParameter':
                self.set_calls.append(dict(args))
                return {}
            raise AssertionError(op)

        def checkpoint(self):
            return {'path': str(tmp_path / 'ckpt.ms14')}

        def restore(self, c):
            raise AssertionError('Restore should not be needed when parameter restoration succeeds')

        def validate(self, op, args):
            pass

        def run_analysis(self, **kwargs):
            assert kwargs['analysis'] == 'dc' and kwargs['dc_source'] == 'V1'
            if self.current_id == 'cid_old':
                self.current_id = 'cid_new'
                return {'raw_path': str(raw_path), 'handles_invalidated': True, 'id_map': {'cid_old': 'cid_new'}}
            return {'raw_path': str(raw_path), 'handles_invalidated': False}

    host = RemapHost()
    res = run_sweep(
        host,
        [{'component_ref': 'cid_old', 'name': 'resistance', 'values': [1000.0, 3300.0]}],
        {'analysis': 'dc', 'dc_source': 'V1', 'dc_start': 0.0, 'dc_stop': 5.0, 'dc_step': 2.5},
        [{'id': 'vout', 'metric': 'value_at', 'signal': 'V(out)', 'at': 5.0}],
        objective={'id': 'vout', 'goal': 'target', 'target': 2.5},
    )
    assert res['status'] == 'complete' and res['restored'] is True and res['best'] == 0
    # Trial 0 used cid_old, Trial 1 remapped to cid_new, Restoration used cid_new with value=2200.0 and NO empty expression="" call!
    assert host.set_calls == [
        {'ref': 'cid_old', 'index': 1, 'value': 1000.0},
        {'ref': 'cid_new', 'index': 1, 'value': 3300.0},
        {'ref': 'cid_new', 'index': 1, 'value': 2200.0},
    ]

    # Interactive simulation running blocks sweep before mutating parameters
    host.sim_state = 1
    with pytest.raises(RuntimeError, match='Stop interactive simulation'):
        run_sweep(host, [{'ref': 'cid_old', 'values': [1000.0]}], {'analysis': 'op'}, [{'id': 'v', 'metric': 'mean', 'signal': 'V(out)'}])

    # Reject bools and conflicting aliases in validate_spec
    for bad_params, bad_obj in [
        ([{'ref': 'R1', 'component_ref': 'R2', 'index': 1, 'values': [1]}], None),
        ([{'ref': 'R1', 'index': True, 'values': [1]}], None),
        ([{'ref': 'R1', 'index': 1, 'values': [True]}], None),
        ([{'ref': 'R1', 'index': 1, 'name': 'resistance', 'values': [1]}], None),
        ([{'ref': 'R1', 'index': 1, 'values': [1]}], {'id': 'a', 'measurement': 'b', 'goal': 'min'}),
    ]:
        with pytest.raises(ValueError):
            validate_spec(bad_params, {'analysis': 'op'}, [{'id': 'a', 'metric': 'mean', 'signal': 'V(1)'}], [], bad_obj)
