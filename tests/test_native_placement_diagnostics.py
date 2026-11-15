import json

import pytest

from multisim_native_mcp.service import EditorService
from multisim_native_mcp.workflows import WorkflowManager

pytestmark=pytest.mark.native


def test_inline_transform_anchor_values_power_refs_and_reopen(tmp_path):
    h=EditorService();source=tmp_path/'placement.ms14'
    try:
        h.create('Placement contracts',str(source))
        h.configure_wiring(connect_touching=False,autowire_on_connection=False)
        manager=WorkflowManager(h,tmp_path/'records')
        assert 'clockwise' in manager.prepare([{'name':'LED_RED','family':'LED','group':'Diodes'}])['components'][0]['rotation_convention']
        for i,(angle,mirror) in enumerate([(-90,None),(90,None),(180,'horizontal'),(0,'vertical')]):
            a={'name':'LED_RED','family':'LED','group':'Diodes','ref':f'D{i+1}','x':180+i*144,'y':180,'anchor':'pin','pin':'A','angle':angle}
            if mirror:a['mirror_axis']=mirror
            placed=h.edit('place',a);c=placed['component']
            pin=next(p for p in c['pins'] if p['name']=='A')
            assert (pin['x'],pin['y'])==(a['x'],a['y'])
            assert placed['labels'] and placed['placement']['actual']=={'x':a['x'],'y':a['y']}
            if angle==-90:assert next(p for p in c['pins'] if p['name']=='K')['x']>pin['x']
            if angle==90:assert next(p for p in c['pins'] if p['name']=='K')['x']<pin['x']
        for i,value in enumerate([1e-6,1e-8,'10n']):
            placed=h.edit('place',{'name':'CAPACITOR_VIRTUAL','ref':f'C{i+1}','x':180+i*180,'y':360,'anchor':'center','angle':90,'value':value})
            parameter=next(p for p in placed['parameters'] if p.get('role')=='value')
            assert parameter['expression'] in ('1u','10n')
            assert parameter['value'] is None or parameter['value']==pytest.approx(1e-6 if i==0 else 1e-8)
        for name,ref in [('GROUND','0'),('VDD','VDD'),('VSS','VSS'),('VCC','VCC')]:
            first=h.edit('place',{'name':name,'ref':ref,'x':90,'y':450})
            second=h.edit('place',{'name':name,'ref':ref,'x':270,'y':450})
            assert first['component']['id']!=second['component']['id']
            assert second['component']['ref']!=ref or name!='GROUND'
            assert any(w['code']=='reference_auto_assigned' for w in second['warnings'])
        modified=h.call('inspect')['modified'];before=h.call('circuitState')
        result=manager.start({'steps':[{'id':'session','kind':'session','mode':'open','source_path':str(source)}]},wait_timeout=30)
        assert result['status']=='complete',result
        assert h.call('inspect')['modified']==modified
        assert h.call('circuitState')['components'][0]['id']==before['components'][0]['id']
        edited=manager.start({'steps':[{'id':'edit','kind':'edit','operations':[
            {'operation':'place','bind':'resistor','arguments':{'name':'RESISTOR_VIRTUAL','ref':'R1','x':600,'y':540,'anchor':'pin','pin':'1','angle':90,'mirror_axis':'vertical','expression':'68k'}},
            {'operation':'place','bind':'ground','arguments':{'name':'GROUND','ref':'0','x':720,'y':540,'anchor':'pin','pin':'1'}},
            {'operation':'wire','arguments':{'source':{'ref':{'$ref':'resistor.component.id'},'pin':'2'},'target':{'ref':{'$ref':'ground.component.id'},'pin':'1'}}},
        ]}]},wait_timeout=30)
        assert edited['status']=='complete',edited
        detail=manager.status(edited['id'],detail=True)
        assert detail['bindings']['resistor']['parameters'][1]['expression']=='68k'
        assert h.save_source()['verification']['passed']
        h.close();h.open_circuit(str(source))
        state=h.call('circuitState',{'include_parameters':True})
        assert len(state['components'])==17
        assert all(c['body_bounds'] and c['labels'] for c in state['components'])
    finally:h.close()


def test_hidden_cmos_rails_and_native_analysis_diagnostics(tmp_path):
    h=EditorService()
    try:
        h.create('Hidden CMOS power',str(tmp_path/'hidden.ms14'))
        h.configure_wiring(connect_touching=False,autowire_on_connection=False)
        h.edit('place',{'name':'4017BD_5V','family':'CMOS_5V','group':'CMOS','ref':'U2','x':360,'y':180})
        h.edit('place',{'name':'VDD','x':90,'y':90})
        ground=h.edit('place',{'name':'GROUND','x':90,'y':360})
        for pin in ('MR','~CP1','CP0'):
            h.edit('wire',{'source':{'ref':'U2','pin':pin},'target':{'ref':ground['component']['id'],'pin':'1'}})
        netlist=h.netlist()
        assert not netlist['failed']
        assert any(d['node']=='VSS' and d['components']==[{'ref':'U2','name':'4017BD_5V'}] for d in netlist['diagnostics']),netlist
        with pytest.raises(RuntimeError,match='VSS'):
            h.run_analysis('tran',.001,.01,True)
        record=json.loads(sorted(h.folder().glob('analysis-*.json'))[-1].read_text())
        assert record['native']['error_text'] and record['native']['stage']=='power-rail-preflight'
        # VSS is a native 0 V global source, already referenced to SPICE ground.
        h.edit('place',{'name':'VSS','x':180,'y':360})
        checked=h.netlist()
        assert not checked['diagnostics'],checked
        assert h.run_analysis('tran',.001,.01,True)['points']>1
        assert h.save_source()['verification']['passed']
    finally:h.close()
