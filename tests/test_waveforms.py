from pathlib import Path
import pytest
from multisim_native_mcp.service import parse_raw, EditorService
from multisim_native_mcp.waveforms import get_plot, is_dc_sweep, plot_axis_kind, resolve_digital_series


def raw_file(tmp_path, content):
    path=tmp_path/'analysis.raw';path.write_text(content, encoding='utf-8');return path


def test_real_sample_grid_and_native_names(tmp_path):
    data=parse_raw(raw_file(tmp_path, '''Title: Divider
Plotname: Transient Analysis
Flags: real
No. Variables: 2
No. Points: 2
Variables:
0 time time
1 v(2) voltage V(2)
Values:
0 0
6
1 0.001
6
'''))
    assert data['rows'] == [[0.0,6.0],[0.001,6.0]]
    assert data['variables'][1]['name'] == 'V(2)'
    assert data['points'] == 2


@pytest.mark.parametrize('count,points',[('0','1'),('1','0'),('-1','1'),('1','-1')])
def test_empty_or_oversized_plots(tmp_path,count,points):
    with pytest.raises(RuntimeError):parse_raw(raw_file(tmp_path,f'No. Variables: {count}\nNo. Points: {points}\nVariables:\n'))


@pytest.mark.parametrize('value',['nan','inf','-inf'])
def test_nonfinite_samples(tmp_path,value):
    text=f'No. Variables: 1\nNo. Points: 1\nVariables:\n0 v(1) voltage\nValues:\n0 {value}\n'
    with pytest.raises(ValueError,match='nonfinite'):parse_raw(raw_file(tmp_path,text))


def test_truncated_waveform(tmp_path):
    text='No. Variables: 2\nNo. Points: 1\nVariables:\n0 time time\n1 v(1) voltage\nValues:\n0 0\n'
    with pytest.raises(ValueError,match='sample count'):parse_raw(raw_file(tmp_path,text))


def test_unexpected_trailing_content(tmp_path):
    text='No. Variables: 1\nNo. Points: 1\nVariables:\n0 time time\nValues:\n0 0\nextra sample\n'
    with pytest.raises(ValueError,match='trailing'):parse_raw(raw_file(tmp_path,text))


@pytest.mark.parametrize('operation,args',[
    ('route',{'points':[{'x':0,'y':0}]}),
    ('route',{'points':[{'x':0,'y':0},{'x':float('inf'),'y':0}]}),
    ('transform',{'angle':float('nan')}),
    ('setParameter',{'index':-1,'value':1}),
    ('setParameter',{'index':1,'value':float('nan')}),
    ('rename',{'ref':'R1\0invalid'}),
    ('sheetSize',{'width':0,'height':100}),
])
def test_invalid_edits(operation,args):
    with pytest.raises(ValueError):EditorService.validate(operation,args)


def test_gbk_and_latin1_raw_header_fallback_and_dc_sweep_axes(tmp_path):
    gbk_raw = tmp_path / 'gbk_dc.raw'
    gbk_text = (
        'Title: ** 分压器直流扫描 **\n'
        'Plotname: DC Transfer Characteristic\n'
        'Flags: real\n'
        'No. Variables: 3\n'
        'No. Points: 3\n'
        'Variables:\n'
        '\t0\tn1\tvoltage\tvv1 voltage (v)\n'
        '\t1\tn2\tvoltage\tV(out)\n'
        '\t2\tn3\tcurrent\tI(V1)\n'
        'Values:\n'
        ' 0\t0.0\n\t0.0\n\t0.0\n'
        ' 1\t2.5\n\t1.25\n\t-0.00125\n'
        ' 2\t5.0\n\t2.5\n\t-0.0025\n'
    )
    gbk_raw.write_bytes(gbk_text.encode('gb18030'))
    parsed = parse_raw(gbk_raw)
    assert '分压器直流扫描' in parsed['title']
    assert is_dc_sweep(parsed) and plot_axis_kind(parsed) == 'voltage'
    assert parsed['variables'][0]['name'] == 'vv1 voltage (v)'
    assert parsed['rows'][-1] == [5.0, 2.5, -0.0025]

    latin_raw = tmp_path / 'latin_curr.raw'
    latin_bytes = (
        b'Title: Source \xff\xfe\xfd\n'
        b'Plotname: DC Transfer Characteristic\n'
        b'Flags: real\n'
        b'No. Variables: 2\n'
        b'No. Points: 2\n'
        b'Variables:\n'
        b'0 i1 current ii1 current (a)\n'
        b'1 n2 voltage V(1)\n'
        b'Values:\n'
        b'0 0.0\n0.0\n'
        b'1 0.01\n10.0\n'
    )
    latin_raw.write_bytes(latin_bytes)
    parsed_curr = parse_raw(latin_raw)
    assert is_dc_sweep(parsed_curr) and plot_axis_kind(parsed_curr) == 'current'


def test_get_plot_and_resolve_digital_series(tmp_path):
    raw = raw_file(tmp_path, '''Title: Mixed
Plotname: Transient Analysis
Flags: real
No. Variables: 2
No. Points: 3
Variables:
0 time time
1 n1 voltage V(1)
Values:
0 0.0
0.0
1 0.001
5.0
2 0.004
5.0

Plotname: Transient Analysis Digital Node
DigitalFlags: Yes
Flags: real
No. Variables: 2
No. Points: 3
Variables:
0 time time
1 d_clk voltage D(CLK)
Values:
0.0,0,1
0.001,1,0
0.003,0,1
''')
    parsed = parse_raw(raw)
    assert get_plot(parsed, 0)['plot'] == 'Transient Analysis'
    assert get_plot(parsed, 1)['digital'] is True
    for bad in (-1, 2, True, '0'):
        with pytest.raises(ValueError):
            get_plot(parsed, bad)
    xs, ys = resolve_digital_series(parsed, 'D(CLK)')
    assert xs[0] == 0.0 and xs[-1] == 0.004
    assert ys == [0.0, 0.0, 1.0, 1.0, 0.0, 0.0]
