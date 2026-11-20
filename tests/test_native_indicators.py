import time

import pytest

from multisim_native_mcp.service import EditorService


pytestmark = pytest.mark.native


def test_hexadecimal_displays_leds_and_logic_probes(tmp_path):
    host = EditorService()
    try:
        host.create('Native indicator states', str(tmp_path / 'indicators.ms14'))
        host.configure_wiring(connect_touching=False, autowire_on_connection=False)
        placements = []
        connections = []

        def place(name, ref, x, y, **options):
            placements.append({'operation': 'place', 'arguments': {
                'name': name, 'ref': ref, 'x': x, 'y': y, 'anchor': 'center', **options,
            }})

        def wire(start, start_pin, end, end_pin):
            connections.append({'operation': 'wire', 'arguments': {
                'source': {'ref': start, 'pin': start_pin}, 'target': {'ref': end, 'pin': end_pin},
            }})

        place('DC_POWER', 'V1', 90, 360, value=5)
        place('GROUND', '0', 117, 657)
        wire('V1', '2', '0', '1')
        expected_digits = {}
        models = ['DCD_HEX', 'DCD_HEX_BLUE', 'DCD_HEX_DIG_GREEN']
        for digit, expected in enumerate('0123456789ABCDEF'):
            ref = f'DS{digit+1}'
            place(models[digit % len(models)], ref, 54 + (digit % 8) * 117, 81 + (digit // 8) * 147)
            expected_digits[ref] = expected
            for bit in range(4):
                wire('V1' if digit & (1 << bit) else '0', '1', ref, str(bit+1))

        expected_leds = {}
        for i, (part, lit) in enumerate([('LED_red', True), ('LED_green', False),
                                         ('LED_BLUE_RATED', True), ('LED_GREEN_RATED', False)], start=1):
            resistor, led = f'R{i}', f'LED{i}'
            y = 375 if i < 3 else 510
            x = 210 if i % 2 else 440
            place('RESISTOR_VIRTUAL', resistor, x, y, value=330)
            place(part, led, x + 117, y)
            wire('V1' if lit else '0', '1', resistor, '1')
            wire(resistor, '2', led, 'A')
            wire(led, 'K', '0', '1')
            expected_leds[led] = lit

        place('PROBE_DIG', 'P1', 693, 405)
        place('PROBE_DIG_YELLOW', 'P2', 828, 405)
        place('PROBE_DIG_BLUE', 'P3', 828, 555)
        wire('V1', '1', 'P1', '1')
        wire('0', '1', 'P2', '1')
        host.batch(placements)
        host.batch(connections)
        netlist = host.netlist()
        assert not netlist['failed'], netlist['messages']
        source = next(line.split() for line in netlist['content'].splitlines() if line.lower().startswith('vv1 '))
        assert source[1] != '0' and source[2] == '0', source
        host.configure_interactive(time_step=.001, max_time_step=.001, real_time=True)
        assert host.control_interactive('start', 15)['transition_confirmed']

        deadline = time.monotonic() + 10
        while True:
            status = host.interactive_status(include_displays=True)
            digits = {d['ref']: d['decoded'] for d in status['display_states'] if d['kind'] == 'hex_display'}
            leds = {d['ref']: d['lit'] for d in status['display_states'] if d['kind'] == 'led'}
            probes = {d['ref']: d['level'] for d in status['display_states'] if d['kind'] == 'digital_probe'}
            if digits == expected_digits and leds == expected_leds and probes == {'P1': 1, 'P2': 0, 'P3': None}:
                break
            assert time.monotonic() < deadline, (digits, leds, probes, status['error_text'])
            time.sleep(.05)

        frame = host.export_interactive_image(str(tmp_path / 'indicators.png'), active_component='LED2', wait_timeout=5)
        assert next(d for d in frame['display_states'] if d['ref'] == 'LED2')['state'] == 'off'
        assert next(d for d in frame['display_states'] if d['ref'] == 'DS16')['decoded'] == 'F'
        assert host.control_interactive('stop', 15)['transition_confirmed']
        assert host.interactive_status(include_displays=True)['display_states'] == []
    finally:
        host.close()
