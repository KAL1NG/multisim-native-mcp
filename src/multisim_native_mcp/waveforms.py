"""Multisim ASCII RAW data and numeric exports."""
from __future__ import annotations

import csv
import io
import math
import os
from pathlib import Path


_AXIS_UNITS = {'voltage': 'V', 'current': 'A', 'time': 's', 'frequency': 'Hz'}


def _decode_raw(raw_bytes: bytes) -> str:
    """Decode ASCII RAW bytes, falling back from UTF-8 to Windows/GBK/Latin-1 locales."""
    if raw_bytes.startswith(b'\xef\xbb\xbf'):
        try:
            return raw_bytes.decode('utf-8-sig', errors='strict')
        except UnicodeDecodeError:
            pass
    encodings = ['utf-8']
    if os.name == 'nt':
        encodings.append('mbcs')
    encodings.append('gb18030')
    for encoding in encodings:
        try:
            return raw_bytes.decode(encoding, errors='strict')
        except (LookupError, UnicodeDecodeError):
            continue
    return raw_bytes.decode('latin-1', errors='replace')


def is_dc_sweep(data: dict) -> bool:
    """Return True when the plot represents a DC transfer/sweep rather than an OP point."""
    if data.get('digital') or data.get('complex'):
        return False
    variables = data.get('variables') or []
    if not variables:
        return False
    kind = (variables[0].get('kind') or '').casefold()
    if kind not in ('voltage', 'current'):
        return False
    plot_name = (data.get('plot') or '').casefold()
    native_name = (variables[0].get('native_name') or '').casefold()
    if 'dc transfer' in plot_name or 'dc sweep' in plot_name or 'sweep' in native_name:
        return True
    if 'operating' in plot_name:
        return False
    return len(variables) > 1 and len(data.get('rows') or ()) > 1


def plot_axis_kind(data: dict) -> str | None:
    """Return the independent axis variable kind ('time', 'frequency', 'voltage', 'current') or None."""
    variables = data.get('variables') or []
    if not variables:
        return None
    kind = (variables[0].get('kind') or '').casefold()
    if data.get('digital') or kind == 'time':
        return 'time'
    if kind == 'frequency':
        return 'frequency'
    if is_dc_sweep(data):
        return kind
    return None


def parse_raw(path: Path) -> dict:
    plots=[]
    text = _decode_raw(Path(path).read_bytes())
    stream = io.StringIO(text, newline=None)
    while True:
        headers={};variables=[];rows=[];nonempty=False
        for line in stream:
            nonempty=nonempty or bool(line.strip())
            if line.strip()=='Variables:':break
            if ':' in line:
                key,value=line.split(':',1);headers[key.strip()]=value.strip()
        if not headers:
            if nonempty:raise ValueError('Unexpected trailing RAW content')
            break
        count=int(headers.get('No. Variables',0));points=int(headers.get('No. Points',0))
        if count<=0 or points<=0:
            raise RuntimeError('Simulator did not produce a nonempty result plot: '+str(headers))
        for line in stream:
            if line.strip()=='Values:':break
            if not line.strip():continue
            fields=line.split(None,3)
            if len(fields)<3 or int(fields[0])!=len(variables):raise ValueError('Malformed native vector metadata')
            kind = fields[2]
            variables.append({'index':int(fields[0]),'native_name':fields[1],'kind':kind,
                              'name':fields[3].strip() if len(fields)>3 else fields[1],
                              'unit':_AXIS_UNITS.get(kind.casefold())})
        if len(variables)!=count:raise ValueError('Native variable count mismatch')
        complex_plot='complex' in headers.get('Flags','').split()
        digital=headers.get('DigitalFlags')=='Yes'
        if digital:
            for variable in variables:
                if variable['kind'].casefold()!='time':variable['unit']=None
        for n in range(points):
            if digital:
                line=next((line.strip() for line in stream if line.strip()),None)
                if line is None:raise ValueError('Native sample count mismatch')
                values=[float(v.strip()) for v in line.split(',')]
                if count!=2 or len(values)!=3 or not all(math.isfinite(v) for v in values):
                    raise ValueError('Malformed digital transition record')
                rows.append(values);continue
            row=[]
            for col in range(count):
                line=next((line.strip() for line in stream if line.strip()),None)
                if line is None:raise ValueError('Native sample count mismatch')
                if col==0:
                    fields=line.split(None,1)
                    if len(fields)!=2 or int(fields[0])!=n:raise ValueError('Native sample index mismatch')
                    line=fields[1]
                value=[float(v.strip()) for v in line.split(',')] if complex_plot else float(line)
                if complex_plot and len(value)!=2:raise ValueError('Malformed complex sample')
                if not all(math.isfinite(v) for v in (value if isinstance(value,list) else [value])):
                    raise ValueError('Simulator returned a nonfinite sample')
                row.append(value)
            rows.append(row)
        plots.append({'title':headers.get('Title'),'plot':headers.get('Plotname'),'points':points,
                      'variables':variables,'complex':complex_plot,'digital':digital,'rows':rows,'unit_system':'SI'})
    if not plots or plots[0]['digital']:raise ValueError('No analog result plot')
    return {**plots[0],'additional_plots':plots[1:]}


def get_plot(data: dict, plot_index: int = 0) -> dict:
    """Return plot `plot_index` from a parsed RAW result without mutating `data`."""
    if isinstance(plot_index, bool) or not isinstance(plot_index, int):
        raise ValueError('Invalid waveform plot index')
    plots = [data, *data.get('additional_plots', [])]
    if not 0 <= plot_index < len(plots):
        raise ValueError('Invalid waveform plot index')
    return plots[plot_index]


def _variable_matches(variable: dict, signal: str) -> bool:
    target = signal.casefold()
    return target in (variable['name'].casefold(), variable['native_name'].casefold())


def digital_events(plot: dict) -> tuple[list[float], list[float]]:
    """Convert `[time, rising, falling]` rows into strictly increasing `(times, levels)`."""
    rows = plot.get('rows') or []
    if not rows:
        raise ValueError('Digital waveform plot has no samples')
    times: list[float] = []
    levels: list[float] = []
    state = 0.0
    for idx, row in enumerate(rows):
        if len(row) != 3:
            raise ValueError('Malformed digital transition record')
        t, rise, fall = float(row[0]), float(row[1]), float(row[2])
        if times and t < times[-1]:
            raise ValueError('Waveform axis must be monotonic')
        if idx == 0:
            state = 1.0 if (rise and not fall) else 0.0
            times.append(t)
            levels.append(state)
            continue
        if rise and not fall:
            state = 1.0
        elif fall and not rise:
            state = 0.0
        elif rise and fall:
            state = 1.0 - state
        if t == times[-1]:
            levels[-1] = state
        else:
            times.append(t)
            levels.append(state)
    return times, levels


def find_digital_plot(data: dict, signal: str, plot_index: int | None = None) -> tuple[dict, dict]:
    """Locate a digital plot and variable matching `signal`."""
    if plot_index is not None:
        plot = get_plot(data, plot_index)
        if not plot.get('digital'):
            raise ValueError(f'Plot {plot_index} is not a digital plot')
        matches = [v for v in plot['variables'][1:] if _variable_matches(v, signal)]
        if len(matches) != 1:
            raise ValueError('Expected one waveform signal: ' + signal)
        return plot, matches[0]
    candidates = []
    for plot in (data, *data.get('additional_plots', [])):
        if not plot.get('digital'):
            continue
        for variable in plot['variables'][1:]:
            if _variable_matches(variable, signal):
                candidates.append((plot, variable))
    if len(candidates) != 1:
        raise ValueError('Expected one waveform signal: ' + signal)
    return candidates[0]


def resolve_digital_series(data: dict, signal: str, plot_index: int | None = None) -> tuple[list[float], list[float]]:
    """Reconstruct step-function `(xs, ys)` samples from a digital `[time, rising, falling]` plot."""
    plot, _ = find_digital_plot(data, signal, plot_index=plot_index)
    times, levels = digital_events(plot)
    xs = [times[0]]
    ys = [levels[0]]
    for t, level in zip(times[1:], levels[1:]):
        if level != ys[-1]:
            xs.append(t)
            ys.append(ys[-1])
        xs.append(t)
        ys.append(level)
    if (
        plot is not data
        and not data.get('digital')
        and not data.get('complex')
        and data.get('variables')
        and (data['variables'][0].get('kind') or '').casefold() == 'time'
        and data.get('rows')
    ):
        t_end = float(data['rows'][-1][0])
        if t_end > xs[-1]:
            xs.append(t_end)
            ys.append(ys[-1])
    return xs, ys


def numeric(value):
    return complex(*value) if isinstance(value,list) else float(value)


def summarize(data):
    result=[]
    for i,variable in enumerate(data['variables']):
        values=[abs(numeric(row[i])) if data['complex'] else row[i] for row in data['rows']]
        result.append({**variable,'first':data['rows'][0][i],'last':data['rows'][-1][i],
                       'min':min(values),'max':max(values),
                       'summary_domain':'magnitude' if data['complex'] else 'real'})
    return result


def export_csv(data,path):
    with Path(path).open('w',newline='',encoding='utf-8-sig') as stream:
        writer=csv.writer(stream)
        writer.writerow([part+(' ['+v['unit']+']' if v.get('unit') else '') for v in data['variables'] for part in
                         ([v['name']+'.real',v['name']+'.imag'] if data['complex'] else [v['name']])])
        for row in data['rows']:
            writer.writerow([part for value in row for part in (value if isinstance(value,list) else [value])])


def signal_index(data,name):
    matches=[v['index'] for v in data['variables'] if name.casefold() in
             (v['name'].casefold(),v['native_name'].casefold())]
    if len(matches)!=1:raise ValueError('Expected one waveform signal: '+name)
    return matches[0]
