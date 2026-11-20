import math
import pytest
from multisim_native_mcp.measurements import measure


def data(rows,complex=False):
    return {'rows':rows,'complex':complex,'variables':[{'index':i,'name':n,'native_name':n} for i,n in enumerate(['time','out','in'])]}


def test_adaptive_time_weighting_and_window():
    d=data([[0,0],[.1,.1],[1,1]])
    r=measure(d,[{'metric':m,'signal':'out','start':.2,'stop':.8} for m in ['mean','rms','peak_to_peak']])
    assert [v['value'] for v in r]==pytest.approx([.5,math.sqrt(.28),.6])


@pytest.mark.parametrize('polarity', [1, -1])
def test_settling_time_uses_last_band_entry_and_interpolates(polarity):
    waveform = data([[time, polarity * value] for time, value in [(1, 0), (2, 9), (3, 10), (4, 11), (5, 10), (6, 10)]])
    waveform['variables'][0]['kind'] = 'time'
    request = {'metric': 'settling_time', 'signal': 'out'}
    result = measure(waveform, [request])[0]
    assert result['value'] == pytest.approx(3.8)
    assert result['unit'] == 's' and result['tolerance'] == 0.02
    assert result['final_value'] == polarity * 10
    assert measure(waveform, [{**request, 'tolerance': 0.12}])[0]['value'] == pytest.approx(8.8/9)
    with pytest.raises(ValueError, match='outside the settling band'):
        measure(waveform, [{**request, 'final_value': polarity * 12}])
    with pytest.raises(ValueError, match='must not be boolean'):
        measure(waveform, [{**request, 'tolerance': True}])


def test_crossings_duty_and_frequency():
    d=data([[i/4,v] for i,v in enumerate([0,1,0,1,0,1,0])])
    r=measure(d,[{'metric':m,'signal':'out','threshold':.5} for m in ['frequency','duty_cycle']])
    assert [v['value'] for v in r]==pytest.approx([2,.5])


def test_complex_transfer():
    d=data([[[100,0],[.5,-.5],[1,0]]],True)
    r=measure(d,[{'metric':m,'signal':'out','reference':'in','frequency_hz':100} for m in ['gain_db','phase_deg']])
    assert [v['value'] for v in r]==pytest.approx([-3.01029995664,-45])


@pytest.mark.parametrize('req',[
    {'metric':'unknown','signal':'out'}, {'metric':'mean','signal':'absent'},
    {'metric':'mean','signal':'out','start':-1}, {'metric':'frequency','signal':'out'},
])
def test_reject_unmeasurable_requests(req):
    with pytest.raises(ValueError):measure(data([[0,0],[1,1]]),[req])


def test_frequency_zero_dt_and_new_time_and_dc_metrics():
    # Degenerate duplicate-timestamp rising crossings raise ValueError instead of ZeroDivisionError
    degenerate = data([[0.0, 1.0], [0.5, 0.0], [0.5, 1.0], [0.5, 0.0], [0.5, 1.0], [1.0, 1.0]])
    with pytest.raises(ValueError, match='distinct times'):
        measure(degenerate, [{'metric': 'frequency', 'signal': 'out', 'threshold': 0.5}])

    # Period, rise_time, fall_time, overshoot, value_at
    # Piecewise waveform: 0->10V linear in 1s (10%-90% = 0.8s), overshoots to 12V, falls to 0V linear in 2s (90%-10% = 1.6s), repeats
    pts = [
        [0.0, 0.0],
        [1.0, 10.0],
        [2.0, 10.0],
        [4.0, 0.0],
        [5.0, 0.0],
        [6.0, 10.0],
    ]
    res = {
        m['metric']: m
        for m in measure(
            data(pts),
            [
                {'metric': 'period', 'signal': 'out', 'threshold': 5.0},
                {'metric': 'rise_time', 'signal': 'out'},
                {'metric': 'fall_time', 'signal': 'out'},
                {'metric': 'value_at', 'signal': 'out', 'at': 0.25},
            ],
        )
    }
    assert res['period']['value'] == pytest.approx(5.0) and res['period']['unit'] == 's'
    assert res['rise_time']['value'] == pytest.approx(0.8) and res['rise_time']['unit'] == 's'
    assert res['fall_time']['value'] == pytest.approx(1.6) and res['fall_time']['unit'] == 's'
    assert res['value_at']['value'] == pytest.approx(2.5) and res['value_at']['at'] == 0.25

    # Rising & falling overshoot
    step_up = data([[0.0, 0.0], [0.5, 12.0], [1.0, 10.0]])
    assert measure(step_up, [{'metric': 'overshoot', 'signal': 'out'}])[0]['value'] == pytest.approx(20.0)
    step_down = data([[0.0, 10.0], [0.5, -1.0], [1.0, 0.0]])
    assert measure(step_down, [{'metric': 'overshoot', 'signal': 'out'}])[0]['value'] == pytest.approx(10.0)
    with pytest.raises(ValueError, match='Overshoot'):
        measure(data([[0.0, 5.0], [1.0, 5.0]]), [{'metric': 'overshoot', 'signal': 'out'}])
    with pytest.raises(ValueError, match='rise'):
        measure(data([[0.0, 5.0], [1.0, 5.0]]), [{'metric': 'rise_time', 'signal': 'out'}])
    with pytest.raises(ValueError, match='fall'):
        measure(data([[0.0, 0.0], [1.0, 5.0]]), [{'metric': 'fall_time', 'signal': 'out'}])
    with pytest.raises(ValueError, match='value_at'):
        measure(step_up, [{'metric': 'value_at', 'signal': 'out'}])

    # Descending DC sweep value_at
    dc_desc = {
        'plot': 'DC Transfer Characteristic',
        'complex': False,
        'digital': False,
        'variables': [
            {'index': 0, 'name': 'vv1 voltage (v)', 'native_name': 'v1', 'kind': 'voltage'},
            {'index': 1, 'name': 'V(out)', 'native_name': 'n2', 'kind': 'voltage'},
        ],
        'rows': [[5.0, 2.5], [2.5, 1.25], [0.0, 0.0]],
    }
    assert measure(dc_desc, [{'metric': 'value_at', 'signal': 'V(out)', 'at': 3.0}])[0]['value'] == pytest.approx(1.5)


def test_new_ac_metrics_magnitude_bandwidth_and_phase_margin():
    # First-order RC low-pass with fc = 1000 Hz, plus open-loop gain 10 / (1 + j f/100)^2
    freqs = [1.0, 10.0, 100.0, 300.0, 1000.0, 3000.0, 10000.0]
    rows = []
    for f in freqs:
        rc = 1.0 / complex(1.0, f / 1000.0)
        ol = 10.0 / (complex(1.0, f / 100.0) ** 2)
        rows.append([[f, 0.0], [rc.real, rc.imag], [ol.real, ol.imag], [1.0, 0.0]])
    ac_data = {
        'plot': 'AC Analysis',
        'complex': True,
        'digital': False,
        'variables': [
            {'index': 0, 'name': 'frequency', 'native_name': 'frequency', 'kind': 'frequency'},
            {'index': 1, 'name': 'V(rc)', 'native_name': 'rc', 'kind': 'voltage'},
            {'index': 2, 'name': 'V(ol)', 'native_name': 'ol', 'kind': 'voltage'},
            {'index': 3, 'name': 'V(in)', 'native_name': 'in', 'kind': 'voltage'},
        ],
        'rows': rows,
    }
    res = {
        m['id']: m
        for m in measure(
            ac_data,
            [
                {'id': 'mag_abs', 'metric': 'magnitude', 'signal': 'V(rc)', 'frequency_hz': 1000.0},
                {'id': 'mag_rel', 'metric': 'magnitude', 'signal': 'V(rc)', 'reference': 'V(in)', 'frequency_hz': 1000.0},
                {'id': 'bw', 'metric': 'bandwidth_3db', 'signal': 'V(rc)', 'reference': 'V(in)'},
                {'id': 'pm', 'metric': 'phase_margin', 'signal': 'V(ol)', 'reference': 'V(in)'},
                {'id': 'val_ac', 'metric': 'value_at', 'signal': 'V(rc)', 'at': 1000.0},
            ],
        )
    }
    assert res['mag_abs']['value'] == pytest.approx(2 ** -0.5, rel=1e-6) and res['mag_abs']['unit'] == 'V'
    assert res['mag_rel']['value'] == pytest.approx(2 ** -0.5, rel=1e-6) and res['mag_rel']['unit'] == ''
    assert res['bw']['value'] == pytest.approx(1000.0, rel=0.05) and res['bw']['unit'] == 'Hz'
    # Exact unity gain of 10 / (1 + (f/100)^2) is at f = 300 Hz, where phase = -2 * atan(3) = -143.13 deg -> PM = 36.87 deg
    assert res['pm']['value'] == pytest.approx(180.0 - 2 * math.degrees(math.atan(3.0)), abs=0.2)
    assert res['pm']['unit'] == 'deg'
    assert res['val_ac']['value'] == pytest.approx(2 ** -0.5, rel=1e-6)

    with pytest.raises(ValueError, match='never crosses 0 dB'):
        measure(ac_data, [{'metric': 'phase_margin', 'signal': 'V(rc)', 'reference': 'V(in)'}])


def test_digital_additional_plot_measurements():
    mixed = {
        'plot': 'Transient Analysis',
        'complex': False,
        'digital': False,
        'variables': [
            {'index': 0, 'name': 'time', 'native_name': 'time', 'kind': 'time'},
            {'index': 1, 'name': 'V(analog)', 'native_name': 'n1', 'kind': 'voltage'},
        ],
        'rows': [[0.0, 0.0], [0.004, 5.0]],
        'additional_plots': [
            {
                'plot': 'Transient Analysis Digital Node',
                'complex': False,
                'digital': True,
                'variables': [
                    {'index': 0, 'name': 'time', 'native_name': 'time', 'kind': 'time'},
                    {'index': 1, 'name': 'D(clk)', 'native_name': 'd_clk', 'kind': 'voltage'},
                ],
                'rows': [
                    [0.0, 0.0, 1.0],
                    [0.001, 1.0, 0.0],
                    [0.002, 0.0, 1.0],
                    [0.003, 1.0, 0.0],
                    [0.004, 0.0, 1.0],
                ],
            }
        ],
    }
    # Works both with explicit plot_index=1 and via automatic unique digital signal fallback (plot_index=0)
    explicit = {
        m['metric']: m
        for m in measure(
            mixed,
            [
                {'metric': 'frequency', 'signal': 'D(clk)', 'plot_index': 1},
                {'metric': 'period', 'signal': 'D(clk)', 'plot_index': 1},
                {'metric': 'duty_cycle', 'signal': 'D(clk)', 'plot_index': 1},
                {'metric': 'mean', 'signal': 'D(clk)', 'plot_index': 1},
                {'metric': 'value_at', 'signal': 'D(clk)', 'at': 0.0015, 'plot_index': 1},
            ],
        )
    }
    assert explicit['frequency']['value'] == pytest.approx(500.0)
    assert explicit['period']['value'] == pytest.approx(0.002)
    assert explicit['duty_cycle']['value'] == pytest.approx(0.5)
    assert explicit['mean']['value'] == pytest.approx(0.5)
    assert explicit['value_at']['value'] == pytest.approx(1.0)
    assert explicit['frequency']['plot_index'] == 1

    fallback = measure(mixed, [{'metric': 'max', 'signal': 'D(clk)'}])[0]
    assert fallback['value'] == pytest.approx(1.0) and 'plot_index' not in fallback
