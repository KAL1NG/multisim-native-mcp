from pathlib import Path
import time

import pytest

from multisim_native_mcp import server
from multisim_native_mcp.layout import check_layout, intersects
from multisim_native_mcp.service import EditorService, NativeEditError
from multisim_native_mcp.workflows import WorkflowManager

pytestmark = pytest.mark.native


def _finish_workflow(manager: WorkflowManager, result: dict) -> dict:
    for _ in range(12):
        if result['status'] not in ('queued', 'running', 'cancel_requested'):
            return result
        result = manager.status(result['id'], 30)
    raise AssertionError(f'Workflow did not finish: {result}')


def test_native_unique_net_labels_and_immediate_netlist_sync(tmp_path):
    h = EditorService()
    try:
        h.create('Wire labels', str(tmp_path / 'label-wire.ms14'))
        h.call('wiringOptions', {'connect_touching': False, 'autowire_on_connection': False})
        for name, ref, x, y, val in [
            ('DC_POWER', 'V1', 108, 180, 10),
            ('RESISTOR_VIRTUAL', 'R1', 270, 180, 1000),
            ('RESISTOR_VIRTUAL', 'R2', 450, 180, 1000),
            ('GROUND', '0', 108, 360, None),
        ]:
            args = {'name': name, 'ref': ref, 'x': x, 'y': y, 'anchor': 'pin', 'pin': '1'}
            if val is not None:
                args['value'] = val
            h.edit('place', args)
        w_a = h.edit('wire', {'source': {'ref': 'V1', 'pin': '1'}, 'target': {'ref': 'R1', 'pin': '1'}})
        w_b = h.edit('wire', {'source': {'ref': 'R1', 'pin': '2'}, 'target': {'ref': 'R2', 'pin': '1'}})
        h.edit('wire', {'source': {'ref': 'R2', 'pin': '2'}, 'target': {'ref': '0', 'pin': '1'}})
        h.edit('wire', {'source': {'ref': 'V1', 'pin': '2'}, 'target': {'ref': '0', 'pin': '1'}})

        # Empty / whitespace wire names rejected
        for bad_name in ('', '   '):
            with pytest.raises(ValueError):
                h.edit('labelWire', {'id': w_a['id'], 'name': bad_name})

        # Label net A and verify immediate reflection in netlist()
        labelled = h.edit('labelWire', {'id': w_a['id'], 'name': 'NET_ALPHA'})
        assert labelled.get('topology_changed') is True
        nl1 = h.netlist()
        assert not nl1['failed'] and 'net_alpha' in nl1['content'].lower()

        # Re-find wires after netlist refresh
        wires_now = h.call('wires')['wires']
        w_a_now = next(w for w in wires_now if {w['source'].get('ref'), w['target'].get('ref')} == {'V1', 'R1'})
        w_b_now = next(w for w in wires_now if {w['source'].get('ref'), w['target'].get('ref')} == {'R1', 'R2'})

        # Rename net A -> immediately reflected in netlist() without stale cache!
        h.edit('labelWire', {'id': w_a_now['id'], 'name': 'NET_RENAMED'})
        nl2 = h.netlist()
        assert not nl2['failed']
        assert 'net_renamed' in nl2['content'].lower() and 'net_alpha' not in nl2['content'].lower()

        # Duplicate net name on distinct electrical net rejected cleanly (case-insensitively) without modal deadlock
        for dup in ('NET_RENAMED', 'net_renamed'):
            wires_now = h.call('wires')['wires']
            w_b_now = next(w for w in wires_now if {w['source'].get('ref'), w['target'].get('ref')} == {'R1', 'R2'})
            with pytest.raises(NativeEditError, match='already exists') as error:
                h.edit('labelWire', {'id': w_b_now['id'], 'name': dup})
            assert error.value.details['rolled_back']

        # Save source completes cleanly with zero modal dialog hang
        saved = h.save_source()
        assert saved['verification']['passed']
    finally:
        h.close()


def test_native_shared_vdd_reconnect_replace_and_obstacle_route(tmp_path, monkeypatch):
    h = EditorService()
    monkeypatch.setattr(server, 'host', h)
    try:
        h.create('Shared VDD', str(tmp_path / 'shared-vdd.ms14'))
        h.call('wiringOptions', {'connect_touching': False, 'autowire_on_connection': False, 'autowire_on_move': False})

        vdd1 = h.edit('place', {'name': 'VDD', 'x': 180, 'y': 180, 'anchor': 'center'})['component']
        vdd2 = h.edit('place', {'name': 'VDD', 'x': 540, 'y': 180, 'anchor': 'center'})['component']
        assert vdd1['ref'] == vdd2['ref'] == 'VDD' and vdd1['id'] != vdd2['id']
        vdd_pin = vdd1['pins'][0]['name']

        h.edit('place', {'name': 'RESISTOR_VIRTUAL', 'ref': 'R1', 'x': 180, 'y': 360, 'anchor': 'center', 'value': 1000})
        h.edit('place', {'name': 'RESISTOR_VIRTUAL', 'ref': 'R2', 'x': 540, 'y': 360, 'anchor': 'center', 'value': 2000})
        obs = h.edit('place', {'name': 'RESISTOR_VIRTUAL', 'ref': 'R_OBS', 'x': 360, 'y': 270, 'anchor': 'center', 'value': 4700})
        gnd = h.edit('place', {'name': 'GROUND', 'x': 360, 'y': 486, 'anchor': 'center'})['component']

        w1 = h.edit('wire', {'source': {'ref': vdd1['id'], 'pin': vdd_pin}, 'target': {'ref': 'R1', 'pin': '1'}})
        h.edit('wire', {'source': {'ref': vdd2['id'], 'pin': vdd_pin}, 'target': {'ref': 'R2', 'pin': '1'}})
        h.edit('wire', {'source': {'ref': 'R1', 'pin': '2'}, 'target': {'ref': gnd['id'], 'pin': gnd['pins'][0]['name']}})

        # 1. Reconnect target of w1 (preserving shared VDD source endpoint by component_id!)
        reconnected = h.edit('reconnect', {'id': w1['id'], 'target': {'ref': 'R2', 'pin': '2'}})
        assert reconnected['source']['component_id'] == vdd1['id']
        assert reconnected['target']['ref'] == 'R2' and reconnected['target']['pin'] == '2'

        # 2. Plan & auto-route wire with engine='obstacle' when shared VDD symbols exist
        routed = server.native_auto_route_wire(reconnected['id'], clearance=9, engine='obstacle')
        assert routed['routing_engine'] == 'obstacle'
        obs_box = obs['placement']['body_bounds']
        pts = routed['wire']['points']
        assert not any(intersects(a, b, obs_box) for a, b in zip(pts, pts[1:]))

        # 3. Replace R2 (whose wires connect to BOTH shared VDD symbols!) with CAPACITOR_VIRTUAL
        replaced_r2 = h.edit('replace', {'ref': 'R2', 'name': 'CAPACITOR_VIRTUAL'})
        assert replaced_r2['component']['ref'] == 'R2'
        assert replaced_r2['reconnected_wires'] == 2

        # 4. Replace one shared VDD symbol (vdd2) by component_id with VCC without disturbing vdd1
        vdds_now = [c for c in h.call('components')['components'] if c['ref'] == 'VDD']
        assert len(vdds_now) == 2
        vdd_right = max(vdds_now, key=lambda c: c['transform'][4])
        vcc_probe = h.edit('place', {'name': 'VCC', 'x': 720, 'y': 180})['component']
        vcc_pin = vcc_probe['pins'][0]['name']
        h.edit('remove', {'ref': vcc_probe['id']})

        vdds_now = [c for c in h.call('components')['components'] if c['ref'] == 'VDD']
        vdd_right = max(vdds_now, key=lambda c: c['transform'][4])
        replaced_vdd = h.edit('replace', {'ref': vdd_right['id'], 'name': 'VCC', 'pin_map': {vdd_pin: vcc_pin}})
        assert replaced_vdd['reconnected_wires'] == 1
        remaining_vdds = [c for c in h.call('components')['components'] if c['ref'] == 'VDD']
        assert len(remaining_vdds) == 1
        assert h.save_source()['verification']['passed']
    finally:
        h.close()


def test_native_library_search_named_params_rename_copy_collapse_and_persist_tstart(tmp_path, monkeypatch):
    h = EditorService()
    manager = WorkflowManager(h, tmp_path / 'wf-records')
    monkeypatch.setattr(server, 'host', h)
    monkeypatch.setattr(server, 'workflows', manager)
    try:
        h.create('Component parameters and transient settings', str(tmp_path / 'component-parameters.ms14'))
        h.call('wiringOptions', {'connect_touching': False, 'autowire_on_connection': False, 'autowire_on_move': False})

        # 1. librarySearch Manufacturer_Name, simulatable_only, LIKE wildcard escaping, exact-match ranking, and prepare(manufacturer=...)
        exact_vdd = server.native_search_library('VDD', limit=1)
        assert exact_vdd['results'][0]['Component_Name'] == 'VDD'

        escaped = server.native_search_library('R*?[1]#', limit=5)
        assert isinstance(escaped['results'], list)

        lm_search = server.native_search_library('LM358', limit=15, simulatable_only=True)
        assert lm_search['results']
        assert all(r.get('Simulatable') is True and 'Manufacturer_Name' in r for r in lm_search['results'])
        with_mfr = next((r for r in lm_search['results'] if r.get('Manufacturer_Name')), None)
        assert with_mfr is not None
        mfr = with_mfr['Manufacturer_Name']
        comp_name = with_mfr['Component_Name']
        filtered = server.native_search_library(comp_name, limit=10, manufacturer=mfr, simulatable_only=True)
        assert filtered['results'] and all(r['Manufacturer_Name'].casefold() == mfr.casefold() for r in filtered['results'])
        prep = manager.prepare([{'name': comp_name, 'manufacturer': mfr}], refresh=True)
        assert prep['prepared'] == 1

        # 2. Named parameters & expanded descriptors (VDD, DC_CURRENT, AC_VOLTAGE, CLOCK_VOLTAGE, OPAMP_3T_VIRTUAL, LED)
        vdd = h.edit('place', {'name': 'VDD', 'x': 90, 'y': 90})['component']
        r_vdd = h.edit('place', {'name': 'RESISTOR_VIRTUAL', 'ref': 'R_VDD', 'x': 90, 'y': 216, 'value': 1000})['component']
        gnd = h.edit('place', {'name': 'GROUND', 'x': 90, 'y': 360})['component']
        h.edit('wire', {'source': {'ref': vdd['id'], 'pin': vdd['pins'][0]['name']}, 'target': {'ref': 'R_VDD', 'pin': '1'}})
        h.edit('wire', {'source': {'ref': 'R_VDD', 'pin': '2'}, 'target': {'ref': gnd['id'], 'pin': gnd['pins'][0]['name']}})
        server.native_set_parameter(vdd['id'], value=3.3)

        isrc = h.edit('place', {'name': 'DC_CURRENT', 'ref': 'I1', 'x': 270, 'y': 180})['component']
        r_curr = h.edit('place', {'name': 'RESISTOR_VIRTUAL', 'ref': 'R_I', 'x': 414, 'y': 180, 'value': 1000})['component']
        h.edit('wire', {'source': {'ref': 'I1', 'pin': isrc['pins'][0]['name']}, 'target': {'ref': 'R_I', 'pin': '1'}})
        h.edit('wire', {'source': {'ref': 'I1', 'pin': isrc['pins'][1]['name']}, 'target': {'ref': gnd['id'], 'pin': gnd['pins'][0]['name']}})
        h.edit('wire', {'source': {'ref': 'R_I', 'pin': '2'}, 'target': {'ref': gnd['id'], 'pin': gnd['pins'][0]['name']}})
        server.native_set_parameter('I1', value=0.002)

        vac = server.native_place_component('AC_VOLTAGE', 576, 90, reference='VAC1', include_parameters=True)
        vac_names = {p.get('name') for p in vac['parameters']}
        assert {'voltage_pk', 'frequency', 'ac_magnitude'} <= vac_names
        server.native_set_parameter('VAC1', name='frequency', expression='2k')
        server.native_set_parameter('VAC1', name='ac_magnitude', value=2.5)
        vac_after = server.native_get_parameters('VAC1')['parameters']
        assert next(p for p in vac_after if p.get('name') == 'ac_magnitude')['value'] == pytest.approx(2.5)
        h.edit('remove', {'ref': 'VAC1'})

        clk = server.native_place_component(
            'CLOCK_VOLTAGE', 576, 216, reference='VCLK1',
            params={'frequency': '2k', 'duty_cycle': 25, 'voltage': 5},
            include_parameters=True,
        )
        clk_by_name = {p.get('name'): p for p in clk['parameters'] if p.get('name')}
        assert {'frequency', 'duty_cycle', 'voltage', 'rise_time', 'fall_time'} <= set(clk_by_name)
        assert clk_by_name['duty_cycle']['value'] == pytest.approx(25)
        h.edit('remove', {'ref': 'VCLK1'})

        opamp = server.native_place_component('OPAMP_3T_VIRTUAL', 576, 324, reference='U_OP', include_parameters=True)
        assert {'open_loop_gain', 'input_resistance', 'output_resistance', 'v_pos', 'v_neg'} <= {
            p.get('name') for p in opamp['parameters']
        }
        h.edit('remove', {'ref': 'U_OP'})

        # Verify OP voltage of 3.3V VDD and 2mA * 1k = 2V DC_CURRENT
        op_res = h.run_analysis('op')
        vdd_sig = server.native_resolve_signal('R_VDD', '1')['signal']
        curr_sig = server.native_resolve_signal('R_I', '1')['signal']
        vec_map = {v['name'].casefold(): v['last'] for v in op_res['vectors']}
        assert abs(vec_map[vdd_sig.casefold()]) == pytest.approx(3.3, abs=1e-6)
        assert abs(vec_map[curr_sig.casefold()]) == pytest.approx(2.0, abs=1e-6)

        # Reference labels stay upright after a rotated copy.
        renamed = h.edit('rename', {'ref': 'R_I', 'new_ref': 'R_SENSE'})
        ref_lbl = next(l for l in h.call('componentLabels', {'ref': 'R_SENSE'})['labels'] if l['kind'] == 'reference')
        assert ref_lbl['text'] == 'R_SENSE'
        # Idempotent same-name rename succeeds cleanly
        assert h.edit('rename', {'ref': 'R_SENSE', 'new_ref': 'R_SENSE'})['ref'] == 'R_SENSE'

        h.edit('transform', {'ref': 'R_SENSE', 'angle': 90})
        copied = h.edit('copy', {'ref': 'R_SENSE', 'new_ref': 'R_COPY', 'x': 630, 'y': 180})
        copy_labels = h.call('componentLabels', {'ref': 'R_COPY'})['labels']
        a, b, c, d = copied['component']['transform'][:4]
        assert {label['kind'] for label in copy_labels} == {'reference', 'value'}
        for lbl in copy_labels:
            x, y = lbl['transform'][:2]
            assert (a*x + c*y, b*x + d*y) == pytest.approx((1, 0), abs=1e-3)
        h.edit('remove', {'ref': copied['component']['id']})

        # Move the wire's two endpoint pins to the same position.
        h.edit('place', {'name': 'RESISTOR_VIRTUAL', 'ref': 'R_CA', 'x': 540, 'y': 450, 'anchor': 'pin', 'pin': '2'})
        h.edit('place', {'name': 'RESISTOR_VIRTUAL', 'ref': 'R_CB', 'x': 630, 'y': 450, 'anchor': 'pin', 'pin': '1'})
        w_col = h.edit('wire', {'source': {'ref': 'R_CA', 'pin': '2'}, 'target': {'ref': 'R_CB', 'pin': '1'}})
        h.edit('move', {'ref': 'R_CA', 'dx': 90, 'dy': 0})
        w_after = next(w for w in h.call('wires')['wires'] if w['id'] == w_col['id'])
        assert len(w_after['points']) >= 2
        state_now = h.call('circuitState')
        assert all(i['kind'] != 'missing_route' for i in check_layout(state_now['components'], state_now['wires'])['issues'])
        h.edit('remove', {'ref': 'R_CA'})
        h.edit('remove', {'ref': 'R_CB'})

        # 4. run_analysis(..., persist=True) succeeds even when document previously had TSTART=0.05 > stop!
        h.simulation_settings(
            'analysis', 'TRAN',
            changes=[{'path': ['ANALYSIS', 'TSTART'], 'value': 0.05}, {'path': ['ANALYSIS', 'TSTOP'], 'value': 0.1}],
        )
        tran_persisted = h.run_analysis('tran', step=1e-4, stop=0.002, persist=True)
        assert tran_persisted['vectors'][0]['last'] == pytest.approx(0.002)
        assert h.save_source()['verification']['passed']
    finally:
        manager.shutdown()
        h.close()


def test_native_dc_sweep_connectivity_fit_sheet_plot_waveform_and_multisheet_workflow(tmp_path, monkeypatch):
    h = EditorService()
    manager = WorkflowManager(h, tmp_path / 'wf-records')
    monkeypatch.setattr(server, 'host', h)
    monkeypatch.setattr(server, 'workflows', manager)
    try:
        h.create('DC sweep, fitSheet & multisheet', str(tmp_path / 'dc-multisheet.ms14'))
        h.call('wiringOptions', {'connect_touching': False, 'autowire_on_connection': False})

        # Place voltage divider partially at negative/off-page coordinates, then fit_sheet!
        placed_off = h.edit('place', {'name': 'DC_POWER', 'ref': 'V1', 'x': -72, 'y': -36, 'anchor': 'pin', 'pin': '1', 'value': 10})
        assert any(w['code'] == 'outside_page' for w in placed_off.get('warnings', []))
        h.edit('place', {'name': 'RESISTOR_VIRTUAL', 'ref': 'R1', 'x': 90, 'y': -36, 'anchor': 'pin', 'pin': '1', 'value': 1000})
        h.edit('place', {'name': 'RESISTOR_VIRTUAL', 'ref': 'R2', 'x': 270, 'y': -36, 'anchor': 'pin', 'pin': '1', 'value': 1000})
        h.edit('place', {'name': 'CAPACITOR_VIRTUAL', 'ref': 'C1', 'x': 270, 'y': 90, 'anchor': 'pin', 'pin': '1', 'value': 1e-6})
        h.edit('place', {'name': 'GROUND', 'ref': '0', 'x': -72, 'y': 180, 'anchor': 'pin', 'pin': '1'})
        for a, ap, b, bp in [
            ('V1', '1', 'R1', '1'),
            ('R1', '2', 'R2', '1'),
            ('R1', '2', 'C1', '1'),
            ('R2', '2', '0', '1'),
            ('C1', '2', '0', '1'),
            ('V1', '2', '0', '1'),
        ]:
            h.edit('wire', {'source': {'ref': a, 'pin': ap}, 'target': {'ref': b, 'pin': bp}})

        fitted = server.native_fit_sheet(margin=36, resize=True)
        assert fitted['shifted']['dx'] > 0 and fitted['shifted']['dy'] > 0
        assert fitted['shifted']['dx'] % 9 == 0 and fitted['shifted']['dy'] % 9 == 0
        assert fitted['after_bounds']['left'] >= 36 and fitted['after_bounds']['top'] >= 36

        # Connectivity, circuitState(include_nets=True), and native_resolve_signal
        ref_id = next(c['id'] for c in h.call('components')['components'] if c['ref'] == 'R2')
        mid = server.native_resolve_signal(ref_id, '1')
        assert mid['handles_invalidated'] and mid['component_id'] == mid['id_map'].get(ref_id, ref_id)
        conn = server.native_get_connectivity()
        assert 'wires' in conn and 'components' in conn and 'nets' in conn
        state_nets = server.native_get_circuit_state(include_nets=True)
        assert all('net' in w for w in state_nets['wires'])
        mid_sig = mid['signal']
        in_sig = server.native_resolve_signal('V1', '1')['signal']
        assert mid_sig.upper().startswith('V(') and in_sig.upper().startswith('V(')
        assert {(pin['ref'], pin['pin']) for pin in conn['nets'][mid['net']]} == {('R1', '2'), ('R2', '1'), ('C1', '1')}

        # Native DC sweep on V1 from 0V to 10V step 2V -> midpoint is V1 / 2 (5.0V at 10V)
        dc = server.native_run_dc_sweep('V1', 0.0, 10.0, 2.0)
        assert dc['points'] == 6
        dc_vectors = {vector['name'].casefold(): vector for vector in dc['vectors']}
        assert mid_sig.casefold() in dc_vectors, (mid_sig, in_sig, list(dc_vectors))
        mid_vec = dc_vectors[mid_sig.casefold()]
        assert mid_vec['first'] == pytest.approx(0.0, abs=1e-9)
        assert mid_vec['last'] == pytest.approx(5.0, abs=1e-7)
        measured = server.native_measure_waveform(dc['raw_path'], [
            {'id': 'out', 'metric': 'value_at', 'at': 10, 'signal': {'component_ref': 'R2', 'pin': '1'}},
        ])
        assert measured['measurements'][0]['value'] == pytest.approx(5)

        # Standalone SVG plot from DC sweep RAW
        dc_svg_path = tmp_path / 'dc-sweep.svg'
        dc_plot = server.native_plot_waveform(dc['raw_path'], str(dc_svg_path), signals=[mid_sig])
        assert dc_plot['format'] == 'svg' and dc_svg_path.is_file() and '<polyline ' in dc_svg_path.read_text(encoding='utf-8')

        # Run a small-signal AC sweep and render its Bode plot.
        h.edit('replace', {'ref': 'V1', 'name': 'AC_VOLTAGE'})
        h.edit('setParameter', {'ref': 'V1', 'name': 'ac_magnitude', 'value': 1})
        ac = server.native_run_ac_sweep('dec', 10, 10.0, 100000.0)
        in_sig_ac = server.native_resolve_signal('V1', '1')['signal']
        mid_sig_ac = server.native_resolve_signal('R2', '1')['signal']
        bode_svg_path = tmp_path / 'rc-bode.svg'
        bode_plot = server.native_plot_waveform(
            ac['raw_path'], str(bode_svg_path), signals=[mid_sig_ac], reference=in_sig_ac, title='Live RC Bode'
        )
        bode_text = bode_svg_path.read_text(encoding='utf-8')
        assert bode_plot['format'] == 'svg' and 'Magnitude (dB)' in bode_text and 'Phase (deg)' in bode_text
        verified = server.native_verify_waveform(ac['raw_path'], [
            {'id': 'gain', 'metric': 'magnitude', 'frequency_hz': 10,
             'signal': {'component_ref': 'R2', 'pin': '1'}, 'reference': {'component_ref': 'V1', 'pin': '1'}},
        ], [{'id': 'gain', 'target': 0.5, 'absolute_tolerance': 0.005}])
        assert verified['passed']

        # Multi-sheet select_sheet workflow
        wf_res = _finish_workflow(
            manager,
            manager.start({
                'steps': [
                    {'id': 'mk_sheet', 'kind': 'edit', 'operations': [{'operation': 'createSheet', 'arguments': {'title': 'AuxSheet'}}]},
                    {'id': 'go_aux', 'kind': 'select_sheet', 'title': 'AuxSheet'},
                    {'id': 'place_aux', 'kind': 'edit', 'operations': [
                        {'operation': 'place', 'arguments': {'name': 'RESISTOR_VIRTUAL', 'ref': 'R_AUX', 'x': 180, 'y': 180, 'value': 4700}}
                    ]},
                    {'id': 'go_main', 'kind': 'select_sheet', 'index': 0},
                    {'id': 'save', 'kind': 'save', 'save_to_source': True},
                ]
            }),
        )
        assert wf_res['status'] == 'complete', wf_res
        assert wf_res['results']['save']['verification']['passed']
        assert wf_res['results']['save']['verification']['sheets'] == 2
        assert any(c['ref'] == 'R1' for c in h.call('components')['components'])
    finally:
        manager.shutdown()
        h.close()


def test_native_rename_label_reopen_and_translate_sheet_keeps_wires(tmp_path):
    h = EditorService()
    try:
        h.create('Rename and translate', str(tmp_path / 'rename-translate.ms14'))
        h.call('wiringOptions', {'connect_touching': False, 'autowire_on_connection': False})
        for name, ref, x, y in [('DC_POWER', 'V1', 108, 180), ('RESISTOR_VIRTUAL', 'R1', 306, 180), ('GROUND', '0', 108, 360)]:
            h.edit('place', {'name': name, 'ref': ref, 'x': x, 'y': y, 'anchor': 'pin', 'pin': '1'})
        for a, ap, b, bp in [('V1', '1', 'R1', '1'), ('R1', '2', '0', '1'), ('V1', '2', '0', '1')]:
            h.edit('wire', {'source': {'ref': a, 'pin': ap}, 'target': {'ref': b, 'pin': bp}})
        wire_id = next(w['id'] for w in h.call('wires')['wires'] if {w['source']['ref'], w['target']['ref']} == {'V1', 'R1'})
        h.edit('labelWire', {'id': wire_id, 'name': 'SUPPLY'})
        before_topology = {(w['source'].get('ref'), w['source'].get('pin'), w['target'].get('ref'), w['target'].get('pin'))
                           for w in h.call('wires')['wires']}
        before_components = {c['ref']: c['transform'][4:] for c in h.call('components')['components']}

        moved = h.edit('translateSheet', {'dx': 18, 'dy': 27})
        assert moved is not None
        after_components = {c['ref']: c['transform'][4:] for c in h.call('components')['components']}
        for ref, (x, y) in before_components.items():
            assert after_components[ref][0] == pytest.approx(x + 18, abs=1)
            assert after_components[ref][1] == pytest.approx(y + 27, abs=1)
        wires = h.call('wires')['wires']
        assert {(w['source'].get('ref'), w['source'].get('pin'), w['target'].get('ref'), w['target'].get('pin')) for w in wires} == before_topology
        for wire in wires:
            for end, index in [('source', 0), ('target', -1)]:
                assert wire['points'][index] == {k: wire[end][k] for k in ('x', 'y')}
        netlist = h.netlist()
        assert not netlist['failed'] and 'SUPPLY' in netlist['content'].upper()

        h.edit('rename', {'ref': 'R1', 'new_ref': 'RLOAD'})
        label = next(l for l in h.call('componentLabels', {'ref': 'RLOAD'})['labels'] if l['kind'] == 'reference')
        assert label['text'] == 'RLOAD'
        out = tmp_path / 'renamed.ms14'
        assert h.save_copy(str(out))['verification']['passed']
        h.close()
        h.open_copy(str(out))
        label = next(l for l in h.call('componentLabels', {'ref': 'RLOAD'})['labels'] if l['kind'] == 'reference')
        assert label['text'] == 'RLOAD'
    finally:
        h.close()


def test_native_seven_seg_com_k_readout(tmp_path):
    h = EditorService()
    try:
        h.create('Common cathode display', str(tmp_path / 'com-k.ms14'))
        for name, ref, x, y in [('DC_POWER', 'V1', 90, 90), ('GROUND', '0', 90, 585), ('SEVEN_SEG_COM_K', 'DS1', 540, 270)]:
            h.edit('place', {'name': name, 'ref': ref, 'x': x, 'y': y})
        for i in range(7):
            h.edit('place', {'name': 'RESISTOR_VIRTUAL', 'ref': 'R' + str(i + 1), 'x': 300, 'y': 90 + i * 63, 'value': 330})
        links = [('V1', '2', '0', '1'), ('DS1', 'COM', '0', '1')]
        for i, segment in enumerate('ABCDEFG', start=1):
            ref, pin = ('V1', '1') if segment in 'ABDEG' else ('0', '1')
            links.extend([(ref, pin, f'R{i}', '1'), (f'R{i}', '2', 'DS1', segment)])
        for a, ap, b, bp in links:
            h.edit('wire', {'source': {'ref': a, 'pin': ap}, 'target': {'ref': b, 'pin': bp}})
        h.edit('setParameter', {'ref': 'V1', 'value': 5})
        h.configure_interactive(time_step=.001, max_time_step=.001, real_time=True)
        assert h.control_interactive('start', 15)['transition_confirmed']
        deadline = time.monotonic() + 15
        while True:
            displays = h.interactive_status(include_displays=True)['display_states']
            if any(display['ref'] == 'DS1' and display['decoded'] == '2' for display in displays):
                break
            assert time.monotonic() < deadline, displays
            time.sleep(.05)
        image = h.export_interactive_image(str(tmp_path / 'com-k.png'), active_component='DS1', wait_timeout=15)
        state = next(d for d in image['display_states'] if d['ref'] == 'DS1')
        assert state['model'] == 'SEVEN_SEG_COM_K' and state['decoded'] == '2'
        h.control_interactive('stop', 15)
    finally:
        h.close()
