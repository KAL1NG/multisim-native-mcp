import time

import pytest

from multisim_native_mcp.service import EditorService


pytestmark = pytest.mark.native


def test_named_potentiometer_parameters_save_and_change_the_live_divider(tmp_path):
    host = EditorService()
    source = tmp_path / 'potentiometer.ms14'
    try:
        host.create('Potentiometer divider', str(source))
        host.configure_wiring(connect_touching=False, autowire_on_connection=False)
        parts = [
            ('DC_POWER', 'V1', 90, 90, {'voltage': 10}),
            ('GROUND', '0', 117, 567, {}),
            ('POTENTIOMETER_VIRTUAL', 'RV1', 360, 225, {'resistance': 2000, 'wiper_step': 10}),
            ('RESISTOR_VIRTUAL', 'R1', 540, 324, {'resistance': 330}),
            ('PROBE_DIG', 'P1', 630, 225, {}),
        ]
        for name, ref, x, y, params in parts:
            host.edit('place', {'name': name, 'ref': ref, 'x': x, 'y': y, 'params': params})
        for a, ap, b, bp in [('V1','2','0','1'), ('V1','1','RV1','1'), ('RV1','3','0','1'),
                              ('RV1','2','R1','1'), ('R1','2','0','1'), ('RV1','2','P1','1')]:
            host.edit('wire', {'source': {'ref': a, 'pin': ap}, 'target': {'ref': b, 'pin': bp}})

        connectivity = host.get_connectivity()['components']
        nets = {(c['ref'], p['name']): p['net'] for c in connectivity for p in c['pins']}
        assert nets['V1','1'] == nets['RV1','1'] != '0', nets
        assert nets['V1','2'] == nets['RV1','3'] == nets['R1','2'] == '0', nets
        assert nets['RV1','2'] == nets['R1','1'] == nets['P1','1'], nets
        assert len({nets['V1','1'], nets['RV1','2'], '0'}) == 3, nets

        def check_level(expected):
            assert host.control_interactive('start', 15)['transition_confirmed']
            deadline = time.monotonic() + 8
            while True:
                status = host.interactive_status(include_displays=True)
                probe = next(d for d in status['display_states'] if d['ref'] == 'P1')
                if probe['level'] == expected and status['simulation_time_s'] and status['simulation_time_s'] >= .02:
                    break
                assert time.monotonic() < deadline, (probe['level'], status['simulation_time_s'], status['error_text'])
                time.sleep(.05)
            assert host.control_interactive('stop', 15)['transition_confirmed']

        host.configure_interactive(time_step=.001, max_time_step=.001, real_time=True)
        # The loaded midpoint falls from about 2 V to 0.5 V as total resistance increases.
        check_level(1)
        host.edit('setParameter', {'ref': 'RV1', 'name': 'resistance', 'value': 12000})
        assert host.save_source()['verification']['passed']
        host.close()
        host.open_circuit(str(source))
        params = {p['name']: p for p in host.call('parameters', {'ref': 'RV1'})['parameters'] if 'name' in p}
        assert params['resistance']['value'] == 12000
        assert params['wiper_step']['value'] == 10
        host.configure_interactive(time_step=.001, max_time_step=.001, real_time=True)
        check_level(0)
    finally:
        host.close()
