"""Numeric acceptance criteria and multiplexed seven-segment decoding."""
import bisect
import collections
from .measurements import finite
from .waveforms import digital_events, find_digital_plot
from .contracts import normalize_criteria


SEGMENTS={'1111110':'0','0110000':'1','1101101':'2','1111001':'3','0110011':'4',
          '1011011':'5','1011111':'6','1110000':'7','1111111':'8','1111011':'9',
          '1110111':'A','0011111':'b','1001110':'C','0111101':'d','1001111':'E','1000111':'F'}


def verify(measurements,criteria):
    values={m['id']:m['value'] for m in measurements};results=[]
    criteria=normalize_criteria(criteria,set(values))
    for criterion in criteria:
        key=criterion['measurement']
        if key not in values:raise ValueError('Unknown measurement: '+key)
        value=finite(values[key]);checks=[]
        for bound in ('min','max'):
            if bound in criterion:
                b=finite(criterion[bound]);checks.append(value>=b if bound=='min' else value<=b)
        if 'target' in criterion:
            target=finite(criterion['target']);absolute=finite(criterion.get('absolute_tolerance',0));relative=finite(criterion.get('relative_tolerance',0))
            if absolute<0 or relative<0:raise ValueError('Tolerances must be nonnegative')
            checks.append(abs(value-target)<=max(absolute,abs(target)*relative))
        if not checks:raise ValueError('Criterion needs min, max or target')
        results.append({**criterion,'value':value,'passed':all(checks)})
    return {'passed':all(c['passed'] for c in results),'criteria':results}


def _resolve_display_signal(data, signal):
    matches = [
        v['index'] for v in data['variables']
        if signal.casefold() in (v['name'].casefold(), v['native_name'].casefold())
    ]
    if len(matches) > 1:
        raise ValueError('Expected one waveform signal: ' + signal)
    if len(matches) == 1:
        return ('analog', matches[0], None)
    dplot, _ = find_digital_plot(data, signal)
    times, levels = digital_events(dplot)
    rows = dplot['rows']
    pre_level = 0.0 if (rows[0][1] and not rows[0][2]) else (1.0 if (rows[0][2] and not rows[0][1]) else levels[0])
    return ('digital', (times, levels, pre_level), times)


def _eval_digital(spec, t):
    times, levels, pre_level = spec
    idx = bisect.bisect_right(times, t) - 1
    return pre_level if idx < 0 else levels[idx]


def _signal_active(source, analog_row, t, analog_threshold, digital_threshold, active_high):
    if source[0] == 'analog':
        return (analog_row[source[1]] >= analog_threshold) == active_high
    return (_eval_digital(source[1], t) >= digital_threshold) == active_high


def decode_display(data,digits,expected=None,start=None,stop=None,threshold=2.5,active_high=True,
                   select_threshold=2.5,select_active_high=True,settling=0.00002,min_dwell=0.00001):
    if data['complex']:raise ValueError('Display decoding needs transient samples')
    if not digits:raise ValueError('Provide digits in display order')
    if expected is not None and len(expected)!=len(digits):raise ValueError('Expected display length differs from digit count')
    threshold=finite(threshold);select_threshold=finite(select_threshold)
    settling=finite(settling);min_dwell=finite(min_dwell)
    if settling<0 or min_dwell<=0:raise ValueError('Require settling >= 0 and min_dwell > 0')

    sources = []
    digital_times_list = []
    for digit in digits:
        if len(digit['segments']) != 7:
            raise ValueError('Segments must be ordered a,b,c,d,e,f,g')
        seg_sources = [_resolve_display_signal(data, s) for s in digit['segments']]
        sel_source = _resolve_display_signal(data, digit['select'])
        for src in (*seg_sources, sel_source):
            if src[2] is not None:
                digital_times_list.append(src[2])
        sources.append((seg_sources, sel_source))

    duration=[collections.Counter() for _ in digits];visits=[0]*len(digits)
    previous=None;conflict=0.;blank=0.

    if not digital_times_list:
        begin=data['rows'][0][0] if start is None else finite(start);end=data['rows'][-1][0] if stop is None else finite(stop)
        if not data['rows'][0][0]<=begin<end<=data['rows'][-1][0]:raise ValueError('Invalid display time window')
        changed=begin
        indices=[([seg[1] for seg in segs],sel[1]) for segs,sel in sources]
        for row,next_row in zip(data['rows'],data['rows'][1:]):
            a=max(begin,row[0]);b=min(end,next_row[0])
            if a>=b:continue
            selected=tuple(i for i,(_,sel) in enumerate(indices) if (row[sel]>=select_threshold)==select_active_high)
            if selected!=previous:previous=selected;changed=a
            a=max(a,changed+settling)
            if a>=b:continue
            if len(selected)>1:conflict+=b-a;continue
            if not selected:blank+=b-a;continue
            digit=selected[0];segments=indices[digit][0]
            bits=''.join('1' if (row[i]>=threshold)==active_high else '0' for i in segments)
            duration[digit][SEGMENTS.get(bits,'unknown:'+bits)]+=b-a
            visits[digit]+=1
    else:
        analog_times = [r[0] for r in data['rows']]
        max_end = max([analog_times[-1], *(ts[-1] for ts in digital_times_list if ts)])
        begin = analog_times[0] if start is None else finite(start)
        end = max_end if stop is None else finite(stop)
        if not analog_times[0] <= begin < end <= max_end:
            raise ValueError('Invalid display time window')
        changed = begin
        dig_seg_thresh = threshold if 0.0 < threshold < 1.0 else 0.5
        dig_sel_thresh = select_threshold if 0.0 < select_threshold < 1.0 else 0.5
        boundaries = sorted({
            begin,
            end,
            *(t for t in analog_times if begin < t < end),
            *(t for ts in digital_times_list for t in ts if begin < t < end),
        })
        for a, b in zip(boundaries, boundaries[1:]):
            if a >= b:
                continue
            row_idx = max(0, bisect.bisect_right(analog_times, a) - 1)
            analog_row = data['rows'][row_idx]
            selected = tuple(
                i for i, (_, sel) in enumerate(sources)
                if _signal_active(sel, analog_row, a, select_threshold, dig_sel_thresh, select_active_high)
            )
            if selected != previous:
                previous = selected
                changed = a
            a = max(a, changed + settling)
            if a >= b:
                continue
            if len(selected) > 1:
                conflict += b - a
                continue
            if not selected:
                blank += b - a
                continue
            digit = selected[0]
            seg_sources = sources[digit][0]
            bits = ''.join(
                '1' if _signal_active(seg, analog_row, a, threshold, dig_seg_thresh, active_high) else '0'
                for seg in seg_sources
            )
            duration[digit][SEGMENTS.get(bits, 'unknown:' + bits)] += b - a
            visits[digit] += 1

    result=[]
    for i,hist in enumerate(duration):
        observed={k:v for k,v in hist.items() if v>=min_dwell}
        best=max(observed,key=observed.get) if observed else None
        passed=bool(observed) and len(observed)==1 and not best.startswith('unknown:')
        if expected is not None:passed=passed and best==expected[i]
        result.append({'label':digits[i].get('label',str(i)),'decoded':best,'observed_seconds':dict(hist),
                       'stable_seconds':sum(observed.values()),'samples':visits[i],'passed':passed})
    return {'decoded':''.join(d['decoded'] if d['decoded'] and len(d['decoded'])==1 else '?' for d in result),
            'expected':expected,'passed':all(d['passed'] for d in result) and conflict<min_dwell,
            'digits':result,'conflict_seconds':conflict,'blank_seconds':blank,'start':begin,'stop':end}
