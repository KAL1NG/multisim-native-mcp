import json
from pathlib import Path
import pytest
from PIL import Image
from multisim_native_mcp.reports import export_report, export_waveform_plot, waveform_svg


def test_reports_escape_text_preserve_measurements_and_protect_outputs(tmp_path):
    raw=tmp_path/'data.raw';raw.write_text('No. Variables: 2\nNo. Points: 2\nVariables:\n0 time time\n1 out voltage\nValues:\n0 0\n1\n1 1\n2\n')
    image=tmp_path/'source.png';Image.new('RGB',(10,10)).save(image)
    record={'id':'a'*32,'status':'complete','schematic_path':str(image),'result':{'best':0,'trials':[
        {'index':0,'status':'complete','parameters':[{'ref':'R1','index':1,'value':1000}],
         'analysis':{'raw_path':str(raw)},'measurements':[{'id':'m','value':1.5,'unit':'V'}],
         'feasible':True,'acceptance':{'passed':True}}]}}
    for lang in ['zh','en']:
        out=tmp_path/lang;out.mkdir()
        result=export_report(record,str(out),lang,'<test>')
        html=(out/'report.html').read_text(encoding='utf-8')
        assert '&lt;test&gt;' in html and '<test>' not in html
        assert 'data:image/png;base64,' in html and '<svg ' in html and '1.5' in html
        assert len(result['files'])==5 and all(Path(p).is_file() for p in result['files'].values())
        with pytest.raises(FileExistsError):export_report(record,str(out),lang)


def test_single_point_op_svg_single_var_report_and_standalone_waveform_bode_plots(tmp_path):
    # 1-variable single-point OP RAW
    op_raw = tmp_path / 'op.raw'
    op_raw.write_text(
        'Title: Single Node OP\n'
        'Plotname: DC Operating Point\n'
        'Flags: real\n'
        'No. Variables: 1\n'
        'No. Points: 1\n'
        'Variables:\n'
        '0 n1 voltage V(out)\n'
        'Values:\n'
        '0 3.3\n',
        encoding='utf-8',
    )
    image = tmp_path / 'circuit.png'
    Image.new('RGB', (12, 12)).save(image)
    record = {
        'id': 'b' * 32,
        'status': 'complete',
        'schematic_path': str(image),
        'result': {
            'best': 0,
            'trials': [
                {
                    'index': 0,
                    'status': 'complete',
                    'parameters': [{'ref': 'R1', 'index': 1, 'value': 2200}],
                    'analysis': {'raw_path': str(op_raw)},
                    'measurements': [{'id': 'vout', 'value': 3.3, 'unit': 'V'}],
                    'feasible': True,
                    'acceptance': {'passed': True},
                }
            ],
        },
    }
    report_dir = tmp_path / 'op_report'
    report_dir.mkdir()
    export_report(record, str(report_dir), 'en', 'OP Report')
    op_svg_text = (report_dir / 'waveforms.svg').read_text(encoding='utf-8')
    assert '<circle ' in op_svg_text and '3.3 V' in op_svg_text and '<polyline ' not in op_svg_text

    # Standalone export_waveform_plot: OP, Bode AC, and Digital plot_index
    op_out = tmp_path / 'standalone_op.svg'
    op_res = export_waveform_plot(str(op_raw), str(op_out))
    assert op_res['format'] == 'svg' and op_res['bytes'] > 100 and op_out.is_file()
    with pytest.raises(FileExistsError):
        export_waveform_plot(str(op_raw), str(op_out))
    with pytest.raises(ValueError, match='complex AC'):
        export_waveform_plot(str(op_raw), str(tmp_path / 'bad_bode.svg'), reference='V(out)')

    ac_raw = tmp_path / 'ac_rc.raw'
    ac_raw.write_text(
        'Title: RC Filter\n'
        'Plotname: AC Analysis\n'
        'Flags: complex\n'
        'No. Variables: 3\n'
        'No. Points: 3\n'
        'Variables:\n'
        '0 frequency frequency\n'
        '1 vin voltage V(in)\n'
        '2 vout voltage V(out)\n'
        'Values:\n'
        '0 10,0\n1,0\n0.9999,-0.01\n'
        '1 1000,0\n1,0\n0.5,-0.5\n'
        '2 100000,0\n1,0\n0.0001,-0.01\n'
        '\n'
        'Plotname: Digital Trace\n'
        'DigitalFlags: Yes\n'
        'Flags: real\n'
        'No. Variables: 2\n'
        'No. Points: 2\n'
        'Variables:\n'
        '0 time time\n'
        '1 d0 voltage D(0)\n'
        'Values:\n'
        '0,0,1\n'
        '0.001,1,0\n',
        encoding='utf-8',
    )
    bode_out = tmp_path / 'bode.svg'
    bode_res = export_waveform_plot(str(ac_raw), str(bode_out), reference='V(in)', title='RC Bode')
    bode_svg = bode_out.read_text(encoding='utf-8')
    assert bode_res['signals'] == ['V(out)']
    assert 'Magnitude (dB)' in bode_svg and 'Phase (deg)' in bode_svg and 'RC Bode' in bode_svg

    bode_png = tmp_path / 'bode.png'
    assert export_waveform_plot(str(ac_raw), str(bode_png), reference='V(in)')['format'] == 'png'
    stacked = tmp_path / 'stacked.png'
    overlaid = tmp_path / 'overlaid.png'
    for output, overlay in [(stacked, False), (overlaid, True)]:
        result = export_waveform_plot(str(ac_raw), str(output), ['V(in)', 'V(out)'], title='波形', overlay=overlay)
        assert result['format'] == 'png'
        assert result['signals'] == ['V(in)', 'V(out)']
    with Image.open(bode_png) as bode, Image.open(stacked) as stack, Image.open(overlaid) as overlay:
        assert bode.format == 'PNG' and bode.height > overlay.height
        assert stack.width == overlay.width and stack.height > overlay.height
        colors = {rgb for _, rgb in overlay.getcolors(maxcolors=65536)}
        assert {(23, 100, 192), (217, 119, 6)} <= colors
    with pytest.raises(FileExistsError):
        export_waveform_plot(str(ac_raw), str(overlaid))

    dig_out = tmp_path / 'digital.svg'
    dig_res = export_waveform_plot(str(ac_raw), str(dig_out), plot_index=1)
    assert dig_res['signals'] == ['D(0)'] and '<polyline ' in dig_out.read_text(encoding='utf-8')
