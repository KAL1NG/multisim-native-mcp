"""Standalone bilingual experiment reports and waveform/Bode plots."""
import base64
import cmath
import csv
import html
import math
from pathlib import Path
from .waveforms import (
    get_plot,
    numeric,
    parse_raw,
    plot_axis_kind,
    resolve_digital_series,
    signal_index,
)


_PALETTE = ('#1764c0', '#d97706', '#059669', '#dc2626', '#7c3aed')


def _decimate_indices(xs, ys, max_buckets=400):
    if len(xs) <= 2:
        return list(range(len(xs)))
    stride = max(1, len(xs) // max_buckets)
    selected = {0, len(xs) - 1}
    for i in range(0, len(xs), stride):
        bucket = range(i, min(i + stride, len(xs)))
        selected.add(min(bucket, key=ys.__getitem__))
        selected.add(max(bucket, key=ys.__getitem__))
    return sorted(selected)


class _PlotCanvas:
    """Share layout, colors and trace geometry between the SVG and PNG outputs."""

    def __init__(self, height, format):
        self.width = 960
        self.height = height
        self.format = format
        if format == 'svg':
            self.elements = [
                f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{height}" viewBox="0 0 {self.width} {height}">',
                '<rect width="100%" height="100%" fill="white"/>',
            ]
        else:
            from PIL import Image, ImageDraw
            self.image = Image.new('RGB', (self.width, height), 'white')
            self.draw = ImageDraw.Draw(self.image)
            self.fonts = {}

    def text(self, x, y, label, size=12, color='#17212f', right=False):
        label = str(label)
        if self.format == 'svg':
            anchor = ' text-anchor="end"' if right else ''
            self.elements.append(f'<text x="{x:.2f}" y="{y:.2f}" font-family="sans-serif" font-size="{size}" fill="{color}"{anchor}>{html.escape(label)}</text>')
        else:
            from PIL import ImageFont
            import os
            cjk = any('\u2e80' <= char <= '\u9fff' for char in label)
            key = (size, cjk)
            if key not in self.fonts:
                path = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts' / ('msyh.ttc' if cjk else 'segoeui.ttf')
                try:
                    self.fonts[key] = ImageFont.truetype(str(path), size)
                except OSError:
                    self.fonts[key] = ImageFont.load_default(size=size)
            self.draw.text((x, y), label, font=self.fonts[key], fill=color, anchor='rs' if right else 'ls')

    def line(self, points, color, width=1):
        if self.format == 'svg':
            coords = ' '.join(f'{x:.2f},{y:.2f}' for x, y in points)
            self.elements.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="{width}"/>')
        else:
            self.draw.line(points, fill=color, width=round(width))

    def grid_line(self, x1, y1, x2, y2, color):
        if self.format == 'svg':
            self.elements.append(f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="{color}"/>')
        else:
            self.draw.line((x1, y1, x2, y2), fill=color)

    def point(self, x, y, color):
        if self.format == 'svg':
            self.elements.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="5" fill="{color}"/>')
        else:
            self.draw.ellipse((x-5, y-5, x+5, y+5), fill=color)

    def render(self):
        if self.format == 'svg':
            return ''.join(self.elements) + '</svg>'
        from io import BytesIO
        output = BytesIO()
        self.image.save(output, format='PNG')
        return output.getvalue()


def _signal_unit_text(variable):
    return variable.get('unit') or {'voltage': 'V', 'current': 'A', 'time': 's', 'frequency': 'Hz'}.get(
        (variable.get('kind') or '').casefold(), ''
    )


def _legend_rows(labels):
    rows, row, used = [], [], 0
    for index, label in enumerate(labels):
        width = min(830, max(85, 8 * len(label) + 27))
        if row and used + width > 830:
            rows.append(row)
            row, used = [], 0
        row.append((80 + used, label, _PALETTE[index % len(_PALETTE)]))
        used += width
    return rows + [row] if row else rows


def _legend(canvas, rows, y):
    for index, row in enumerate(rows):
        for x, label, color in row:
            baseline = y + 19 * index
            canvas.grid_line(x, baseline - 4, x + 12, baseline - 4, color)
            canvas.text(x + 17, baseline, label, color=color)


def _draw_panel(canvas, top, label, traces, axis, axis_unit, point_unit='', reference_line=None):
    left, right, height = 80, 910, 140
    low = min(min(ys) for _, _, ys, _ in traces)
    high = max(max(ys) for _, _, ys, _ in traces)
    x_start, x_stop = traces[0][1][0], traces[0][1][-1]
    span = x_stop - x_start or 1
    def y_pixel(value):
        return top + height / 2 if high == low else top + height * (high - value) / (high - low)

    if label:
        canvas.text(left, top - 10, label, size=15)
    for i in range(1, 4):
        gx, gy = left + (right - left) * i / 4, top + height * i / 4
        canvas.grid_line(gx, top, gx, top + height, '#e5e9f0')
        canvas.grid_line(left, gy, right, gy, '#e5e9f0')
    if reference_line is not None and low < reference_line < high:
        y = y_pixel(reference_line)
        canvas.grid_line(left, y, right, y, '#94a3b8')
    canvas.grid_line(left, top, left, top + height, '#94a3b8')
    canvas.grid_line(left, top + height, right, top + height, '#94a3b8')
    for i, (_, xs, ys, color) in enumerate(traces):
        if len(xs) == 1:
            x, y = (left + right) / 2, y_pixel(ys[0])
            canvas.point(x + 3 * i, y, color)
            if len(traces) == 1:
                canvas.text(x + 10, y + 4, f'{ys[0]:.6g}' + (f' {point_unit}' if point_unit else ''), size=13, color=color)
        else:
            points = [(left + (right-left) * (xs[i] - x_start) / span, y_pixel(ys[i]))
                      for i in _decimate_indices(xs, ys)]
            canvas.line(points, color, width=2)
    canvas.text(8, top + 12, f'{high:.5g}', color='#334155')
    canvas.text(8, top + 74, f'{(high + low) / 2:.5g}', color='#64748b')
    canvas.text(8, top + 140, f'{low:.5g}', color='#334155')
    canvas.text(left, top + 164, f'{axis[0]:.6g}', color='#334155')
    canvas.text(right, top + 164, f'{axis[-1]:.6g} {axis_unit}', color='#334155', right=True)


def _waveform_plot(data, signals, title=None, parsed=None, plot_index=0, *, format='svg', overlay=False):
    if not signals:
        raise ValueError('Choose waveform signals')
    if not data.get('rows'):
        raise ValueError('Waveform plot has no samples')

    digital = bool(data.get('digital'))
    complex_plot = bool(data.get('complex'))
    axis_kind = plot_axis_kind(data)
    axis = [numeric(row[0]).real for row in data['rows']] if axis_kind else list(range(len(data['rows'])))
    log = complex_plot and min(axis) > 0
    xs = [math.log10(x) for x in axis] if log else axis
    axis_unit = {'frequency': 'Hz (log)' if log else 'Hz', 'time': 's', 'voltage': 'V', 'current': 'A'}.get(axis_kind, 'sample')
    traces = []
    for index, signal in enumerate(signals):
        unit = ''
        if digital:
            trace_axis, ys = resolve_digital_series(parsed if parsed is not None else data, signal,
                                                    plot_index=plot_index if parsed is not None else None)
            trace_xs = trace_axis
        else:
            column = signal_index(data, signal)
            variable = next(v for v in data['variables'] if v['index'] == column)
            unit = _signal_unit_text(variable)
            trace_axis, trace_xs = axis, xs
            ys = [abs(numeric(row[column])) if complex_plot else float(row[column]) for row in data['rows']]
        label = signal + (f' [{unit}]' if unit else '')
        color = _PALETTE[index % len(_PALETTE)] if overlay else _PALETTE[0]
        traces.append((label, trace_xs, ys, color, unit, trace_axis))

    if overlay and len({trace[4] for trace in traces}) > 1:
        raise ValueError('Overlay signals must have the same units')
    if overlay and any(trace[1] != traces[0][1] for trace in traces):
        raise ValueError('Overlay signals must use the same sample axis')
    legend = _legend_rows(trace[0] for trace in traces) if overlay else []
    header = (36 if title else 0) + 19 * len(legend)
    canvas = _PlotCanvas(header + 220 * (1 if overlay else len(traces)), format)
    if title:
        canvas.text(80, 26, title, size=18)
    suffix = ' | magnitude' if complex_plot else ' | digital' if digital else ''
    if overlay:
        _legend(canvas, legend, 45 if title else 16)
        label = 'Magnitude' if complex_plot else 'Digital' if digital else ''
        _draw_panel(canvas, header + 36, label, [trace[:4] for trace in traces], traces[0][5], axis_unit, traces[0][4])
    else:
        for index, trace in enumerate(traces):
            _draw_panel(canvas, header + index * 220 + 36, trace[0] + suffix, [trace[:4]], trace[5], axis_unit, trace[4])
    return canvas.render()


def waveform_svg(data, signals, title=None, parsed=None, plot_index=0):
    return _waveform_plot(data, signals, title, parsed, plot_index)


def _bode_plot(data, signals, reference, title=None, *, format='svg'):
    if not signals:
        raise ValueError('Choose waveform signals')
    if not data.get('rows'):
        raise ValueError('Waveform plot has no samples')
    ref_idx = signal_index(data, reference)
    freqs = [numeric(row[0]).real for row in data['rows']]
    log = min(freqs) > 0
    xs = [math.log10(freq) for freq in freqs] if log else freqs
    magnitudes, phases = [], []
    for index, signal in enumerate(signals):
        column = signal_index(data, signal)
        dbs, degrees = [], []
        for row in data['rows']:
            denominator = numeric(row[ref_idx])
            if abs(denominator) == 0:
                raise ValueError('Reference signal is zero')
            ratio = numeric(row[column]) / denominator
            magnitude = abs(ratio)
            dbs.append(20 * math.log10(magnitude) if magnitude else -300)
            phase = math.degrees(cmath.phase(ratio))
            if degrees:
                phase = degrees[-1] + ((phase - degrees[-1] + 180) % 360 - 180)
            degrees.append(phase)
        color = _PALETTE[index % len(_PALETTE)]
        magnitudes.append((signal, xs, dbs, color))
        phases.append((signal, xs, degrees, color))
    legend = _legend_rows(f'{signal} / {reference}' for signal in signals)
    top = 58 + 19 * len(legend)
    canvas = _PlotCanvas(top + 410, format)
    canvas.text(80, 26, title or f"{data.get('plot') or 'AC Analysis'} — Bode Plot (ref: {reference})", size=18)
    _legend(canvas, legend, 46)
    unit = 'Hz (log)' if log else 'Hz'
    _draw_panel(canvas, top, 'Magnitude (dB)', magnitudes, freqs, unit, 'dB', reference_line=0)
    _draw_panel(canvas, top + 220, 'Phase (deg)', phases, freqs, unit, 'deg', reference_line=-180)
    return canvas.render()



def export_waveform_plot(
    raw_path: str,
    output_path: str,
    signals: list[str] | None = None,
    reference: str | None = None,
    title: str | None = None,
    overwrite: bool = False,
    plot_index: int = 0,
    overlay: bool = False,
) -> dict:
    """Render an SVG or PNG waveform or dual-panel AC Bode plot from an ASCII RAW file."""
    if not isinstance(overwrite, bool):
        raise ValueError('overwrite must be boolean')
    if not isinstance(overlay, bool):
        raise ValueError('overlay must be boolean')
    if isinstance(plot_index, bool) or not isinstance(plot_index, int) or plot_index < 0:
        raise ValueError('Invalid waveform plot index')
    raw = Path(raw_path)
    if not raw.is_file() or raw.suffix.lower() != '.raw':
        raise ValueError('Choose an existing .raw file')
    out = Path(output_path)
    format = out.suffix.lower().removeprefix('.')
    if not out.is_absolute() or not out.parent.is_dir() or format not in ('svg', 'png') or out.is_dir():
        raise ValueError('Choose an absolute .svg or .png output path in an existing directory')
    if out.exists() and not overwrite:
        raise FileExistsError('Output waveform plot already exists')
    if signals is not None and (
        not isinstance(signals, list) or not signals or any(not isinstance(s, str) or not s.strip() for s in signals)
    ):
        raise ValueError('Choose waveform signals')
    if reference is not None and (not isinstance(reference, str) or not reference.strip()):
        raise ValueError('Invalid reference signal')

    parsed = parse_raw(raw)
    data = get_plot(parsed, plot_index)
    if signals is None:
        if data.get('digital'):
            signals = [v['name'] for v in data['variables'][1:]] or [v['name'] for v in data['variables'][:1]]
        else:
            offset = 1 if plot_axis_kind(data) is not None else 0
            candidates = data['variables'][offset:]
            if reference is not None:
                ref_cf = reference.casefold()
                filtered = [
                    v for v in candidates
                    if ref_cf not in (v['name'].casefold(), v['native_name'].casefold())
                ]
                candidates = filtered or candidates
            candidates = candidates or data['variables']
            if overlay and reference is None and candidates:
                unit = _signal_unit_text(candidates[0])
                candidates = [v for v in candidates if _signal_unit_text(v) == unit]
            signals = [v['name'] for v in candidates[:3]]
    else:
        signals = list(signals)

    if reference is not None:
        if not data.get('complex'):
            raise ValueError('Reference Bode plot requires a complex AC plot')
        output = _bode_plot(data, signals, reference, title=title, format=format)
    else:
        plot_title = title or data.get('title') or data.get('plot') or raw.stem
        output = _waveform_plot(data, signals, title=plot_title, parsed=parsed, plot_index=plot_index,
                                format=format, overlay=overlay)

    encoded = output.encode('utf-8') if isinstance(output, str) else output
    with out.open('wb' if overwrite else 'xb') as destination:
        destination.write(encoded)
    return {
        'path': str(out),
        'raw_path': str(raw),
        'signals': signals,
        'plot': data['plot'],
        'bytes': out.stat().st_size,
        'format': format,
    }


def export_report(record,directory,language='zh',title=None,signals=None,overwrite=False):
    if language not in ('zh','en'):raise ValueError('Choose zh or en')
    out=Path(directory)
    if not out.is_absolute() or not out.is_dir():raise ValueError('Choose an existing absolute output directory')
    trials=record.get('result',{}).get('trials',[]);complete=[t for t in trials if t.get('status')=='complete']
    if not complete:raise ValueError('Experiment has no completed numeric trial')
    best=record['result'].get('best');trial=next((t for t in complete if t['index']==best),complete[0])
    data=parse_raw(Path(trial['analysis']['raw_path']))
    offset=1 if plot_axis_kind(data) is not None else 0
    default_signals=[v['name'] for v in data['variables'][offset:offset+3]] or [v['name'] for v in data['variables'][:3]]
    signals=signals or default_signals
    svg=waveform_svg(data,signals)
    image=Path(record['schematic_path']);png=image.read_bytes()
    names=['report.html','report.md','measurements.csv','circuit.png','waveforms.svg']
    if not overwrite and any((out/n).exists() for n in names):raise FileExistsError('Report output already exists')
    zh=language=='zh';title=title or ('电路实验报告' if zh else 'Circuit experiment report')
    labels=['实验','状态','候选','参数','指标','数值','单位','候选可行'] if zh else ['Experiment','Status','Trial','Parameters','Metric','Value','Unit','Feasible']
    rows=[]
    for t in trials:
        parameters=', '.join(f"{p['ref']}[{p['index']}]={p['value']:g}" for p in t['parameters'])
        for m in t.get('measurements',[]):
            rows.append([str(t['index']),parameters,m['id'],f"{m['value']:.10g}",m['unit'],str(t.get('feasible',False))])
        if t.get('error'):rows.append([str(t['index']),parameters,'error',t['error'],'','False'])
    headings=labels[2:]
    table='<table><thead><tr>'+''.join('<th>'+html.escape(c)+'</th>' for c in headings)+'</tr></thead><tbody>'
    table+=''.join('<tr>'+''.join('<td>'+html.escape(str(c))+'</td>' for c in row)+'</tr>' for row in rows)+'</tbody></table>'
    acceptance=trial.get('acceptance',{})
    criteria=acceptance.get('criteria',[])
    if criteria:
        criteria_rows=[]
        for c in criteria:
            condition=[]
            if 'min' in c:condition.append('≥ '+str(c['min']))
            if 'max' in c:condition.append('≤ '+str(c['max']))
            if 'target' in c:condition.append(str(c['target'])+' ± '+str(max(c.get('absolute_tolerance',0),abs(c['target'])*c.get('relative_tolerance',0))))
            criteria_rows.append([c['measurement'],', '.join(condition),str(c['value']),('通过' if c['passed'] else '失败') if zh else ('Pass' if c['passed'] else 'Fail')])
        criteria_head=['指标','要求','实测值','结果'] if zh else ['Metric','Requirement','Measured','Result']
        details='<table><tr>'+''.join('<th>'+html.escape(c)+'</th>' for c in criteria_head)+'</tr>'
        details+=''.join('<tr>'+''.join('<td>'+html.escape(c)+'</td>' for c in row)+'</tr>' for row in criteria_rows)+'</table>'
        acceptance_md='| '+' | '.join(criteria_head)+' |\n| --- | --- | --- | --- |\n'
        acceptance_md+=''.join('| '+' | '.join(row)+' |\n' for row in criteria_rows)
    else:
        text='未设置验收条件。' if zh else 'No acceptance criteria configured.'
        details='<p>'+text+'</p>';acceptance_md=text+'\n'
    caption='验收结果' if zh else 'Acceptance results'
    document=f'''<!doctype html><html lang="{'zh-CN' if zh else 'en'}"><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>body{{font:16px/1.6 system-ui,sans-serif;max-width:1100px;margin:40px auto;padding:0 24px;color:#17212f}}img,svg{{max-width:100%;height:auto}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ccd4df;padding:8px;text-align:left}}th{{background:#edf2f8}}pre{{white-space:pre-wrap}}</style>
<h1>{html.escape(title)}</h1><p>{labels[0]}: {record['id']} · {labels[1]}: {html.escape(record['status'])}</p>
<h2>{'电路' if zh else 'Circuit'}</h2><img alt="Circuit" src="data:image/png;base64,{base64.b64encode(png).decode()}">
<h2>{'波形' if zh else 'Waveforms'}</h2>{svg}<h2>{'测量结果' if zh else 'Measurements'}</h2>{table}
<h2>{caption}</h2>{details}</html>'''
    def md(value):return str(value).replace('|','\\|').replace('\n',' ')
    markdown=f'# {title}\n\n{labels[0]}: `{record["id"]}`\n\n{labels[1]}: {record["status"]}\n\n![Circuit](circuit.png)\n\n![Waveforms](waveforms.svg)\n\n'
    markdown+='| '+' | '.join(headings)+' |\n| '+' | '.join(['---']*len(headings))+' |\n'
    markdown+=''.join('| '+' | '.join(md(c) for c in row)+' |\n' for row in rows)
    markdown+=f'\n## {caption}\n\n{acceptance_md}'
    (out/'report.html').write_text(document,encoding='utf-8');(out/'report.md').write_text(markdown,encoding='utf-8')
    (out/'circuit.png').write_bytes(png);(out/'waveforms.svg').write_text(svg,encoding='utf-8')
    with (out/'measurements.csv').open('w',newline='',encoding='utf-8-sig') as stream:
        writer=csv.writer(stream);writer.writerow(headings);writer.writerows(rows)
    return {'experiment_id':record['id'],'trial_index':trial['index'],'files':{n:str((out/n).resolve()) for n in names}}
