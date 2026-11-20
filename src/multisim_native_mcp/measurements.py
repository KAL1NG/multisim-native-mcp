"""Measurements on native samples, including adaptive time grids."""
import bisect
import cmath
import math
from .waveforms import (
    find_digital_plot,
    get_plot,
    is_dc_sweep,
    numeric,
    plot_axis_kind,
    resolve_digital_series,
)
from .contracts import normalize_measurements


def finite(value):
    if isinstance(value, bool):
        raise ValueError('Measurement values must not be boolean')
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('Measurement values must be finite')
    return value


def interpolate(xs, ys, x):
    if math.isclose(x, xs[0], rel_tol=1e-12, abs_tol=1e-15):
        x = xs[0]
    if math.isclose(x, xs[-1], rel_tol=1e-12, abs_tol=1e-15):
        x = xs[-1]
    if not xs[0] <= x <= xs[-1]:
        raise ValueError('Requested coordinate is outside the waveform')
    i = bisect.bisect_right(xs, x) - 1
    if i == len(xs) - 1 or xs[i] == x:
        return ys[i]
    return ys[i] + (ys[i + 1] - ys[i]) * (x - xs[i]) / (xs[i + 1] - xs[i])


def _interpolate_left(xs, ys, x):
    if math.isclose(x, xs[0], rel_tol=1e-12, abs_tol=1e-15):
        x = xs[0]
    if math.isclose(x, xs[-1], rel_tol=1e-12, abs_tol=1e-15):
        x = xs[-1]
    if not xs[0] <= x <= xs[-1]:
        raise ValueError('Requested coordinate is outside the waveform')
    i = bisect.bisect_left(xs, x)
    if xs[i] == x:
        return ys[i]
    return ys[i - 1] + (ys[i] - ys[i - 1]) * (x - xs[i - 1]) / (xs[i] - xs[i - 1])


def _slice_series(xs, ys, start=None, stop=None, allow_decreasing=False):
    if not xs:
        raise ValueError('Waveform plot has no samples')
    if allow_decreasing and len(xs) > 1 and xs[0] > xs[-1] and all(b <= a for a, b in zip(xs, xs[1:])):
        xs = list(reversed(xs))
        ys = list(reversed(ys))
    if any(b < a for a, b in zip(xs, xs[1:])):
        raise ValueError('Waveform axis must be monotonic')
    if start is None and stop is None:
        return list(xs), list(ys)
    start_v = xs[0] if start is None else finite(start)
    stop_v = xs[-1] if stop is None else finite(stop)
    if start_v > stop_v:
        raise ValueError('Measurement start exceeds stop')
    if stop_v == start_v:
        return [start_v], [interpolate(xs, ys, start_v)]
    first = interpolate(xs, ys, start_v)
    pairs = [(start_v, first)] + [(x, y) for x, y in zip(xs, ys) if start_v < x < stop_v]
    if stop is None:
        pairs.extend((x, y) for x, y in zip(xs, ys) if x == xs[-1] and x > start_v)
    else:
        pairs.append((stop_v, _interpolate_left(xs, ys, stop_v)))
    return [p[0] for p in pairs], [p[1] for p in pairs]


def _extract_series(data, signal, start=None, stop=None, plot_index=0):
    target_plot = get_plot(data, plot_index)
    if target_plot.get('digital'):
        _, variable = find_digital_plot(data, signal, plot_index=plot_index)
        xs, ys = resolve_digital_series(data, signal, plot_index=plot_index)
        xs, ys = _slice_series(xs, ys, start, stop)
        return target_plot, variable, xs, ys

    matches = [
        v for v in target_plot['variables']
        if signal.casefold() in (v['name'].casefold(), v['native_name'].casefold())
    ]
    if len(matches) > 1:
        raise ValueError('Expected one waveform signal: ' + signal)
    if len(matches) == 1:
        variable = matches[0]
        index = variable['index']
        xs = [numeric(r[0]).real for r in target_plot['rows']]
        ys = [numeric(r[index]) for r in target_plot['rows']]
        xs, ys = _slice_series(xs, ys, start, stop, allow_decreasing=is_dc_sweep(target_plot))
        return target_plot, variable, xs, ys

    if plot_index == 0:
        dplot, dvar = find_digital_plot(data, signal)
        xs, ys = resolve_digital_series(data, signal)
        xs, ys = _slice_series(xs, ys, start, stop)
        return dplot, dvar, xs, ys

    raise ValueError('Expected one waveform signal: ' + signal)


def series(data, signal, start=None, stop=None, plot_index=0):
    _, _, xs, ys = _extract_series(data, signal, start=start, stop=stop, plot_index=plot_index)
    return xs, ys


def _signal_unit(plot, variable):
    if plot.get('digital'):
        return ''
    return {'voltage': 'V', 'current': 'A', 'time': 's', 'frequency': 'Hz'}.get(
        (variable.get('kind') or '').casefold()
    ) or variable.get('unit') or ''


def _ac_transfer_samples(data, xs, ys, reference, plot_index):
    _, _, rx, ry = _extract_series(data, reference, plot_index=plot_index)
    mags = []
    gains_db = []
    phases_deg = []
    for f, y in zip(xs, ys):
        den = interpolate(rx, ry, f)
        if abs(den) == 0:
            raise ValueError('Reference signal is zero')
        ratio = y / den
        mag = abs(ratio)
        mags.append(mag)
        gains_db.append(20.0 * math.log10(mag) if mag > 0 else -math.inf)
        phases_deg.append(math.degrees(cmath.phase(ratio)))
    return mags, gains_db, phases_deg


def _rise_time(xs, ys):
    low, high = min(ys), max(ys)
    if high == low:
        raise ValueError('Constant signal has no rise transition')
    v10 = low + 0.1 * (high - low)
    v90 = low + 0.9 * (high - low)
    t10 = None
    for a, b, u, v in zip(xs, xs[1:], ys, ys[1:]):
        if v > u:
            if u < v10 <= v or (u == v10 and t10 is None):
                t10 = a + (b - a) * (v10 - u) / (v - u)
            if t10 is not None and u < v90 <= v:
                t90 = a + (b - a) * (v90 - u) / (v - u)
                return t90 - t10
        elif v < u:
            if v < v10 <= u:
                t10 = None
    raise ValueError('Signal does not contain a full rising transition')


def _fall_time(xs, ys):
    low, high = min(ys), max(ys)
    if high == low:
        raise ValueError('Constant signal has no fall transition')
    v10 = low + 0.1 * (high - low)
    v90 = low + 0.9 * (high - low)
    t90 = None
    for a, b, u, v in zip(xs, xs[1:], ys, ys[1:]):
        if v < u:
            if v <= v90 < u or (u == v90 and t90 is None):
                t90 = a + (b - a) * (u - v90) / (u - v)
            if t90 is not None and v <= v10 < u:
                t10 = a + (b - a) * (u - v10) / (u - v)
                return t10 - t90
        elif v > u:
            if u <= v90 < v:
                t90 = None
    raise ValueError('Signal does not contain a full falling transition')


def _settling_time(xs, ys, final, tolerance):
    step = abs(final - ys[0])
    if xs[-1] <= xs[0] or step == 0:
        raise ValueError('Settling time requires a nonzero time window and step')
    low, high = final - tolerance * step, final + tolerance * step
    if not low <= ys[-1] <= high:
        raise ValueError('The waveform is outside the settling band at the end of the window')
    for index in range(len(ys) - 2, -1, -1):
        sample = ys[index]
        if not low <= sample <= high:
            boundary = low if sample < low else high
            fraction = (boundary - sample) / (ys[index + 1] - sample)
            return xs[index] - xs[0] + fraction * (xs[index + 1] - xs[index])
    return 0.0


def measure(data, requests):
    requests = normalize_measurements(requests)
    results = []
    ids = set()
    for n, request in enumerate(requests):
        metric = request['metric']
        signal = request['signal']
        identifier = request.get('id', str(n))
        if identifier in ids:
            raise ValueError('Measurement IDs must be unique')
        ids.add(identifier)
        plot_index = request.get('plot_index', 0)
        start = request.get('start')
        stop = request.get('stop')
        target_plot, variable, xs, ys = _extract_series(
            data, signal, start=start, stop=stop, plot_index=plot_index
        )
        unit = _signal_unit(target_plot, variable)
        extra = {}
        if plot_index > 0:
            extra['plot_index'] = plot_index

        if metric == 'value_at':
            at = finite(request['at'])
            sample = interpolate(xs, ys, at)
            value = abs(sample) if target_plot.get('complex') else sample
            extra['at'] = at
        elif metric in ('gain_db', 'phase_deg', 'magnitude', 'bandwidth_3db', 'phase_margin'):
            if not target_plot.get('complex'):
                raise ValueError('Gain and phase require an AC plot')
            if metric in ('gain_db', 'phase_deg'):
                frequency = finite(request['frequency_hz'])
                _, _, rx, ry = _extract_series(data, request['reference'], plot_index=plot_index)
                denominator = interpolate(rx, ry, frequency)
                if abs(denominator) == 0:
                    raise ValueError('Reference signal is zero')
                ratio = interpolate(xs, ys, frequency) / denominator
                if metric == 'gain_db' and abs(ratio) == 0:
                    raise ValueError('Gain is zero')
                value = 20 * math.log10(abs(ratio)) if metric == 'gain_db' else math.degrees(cmath.phase(ratio))
                unit = 'dB' if metric == 'gain_db' else 'deg'
                extra.update({'frequency_hz': frequency, 'reference': request['reference']})
            elif metric == 'magnitude':
                frequency = finite(request['frequency_hz'])
                sample = interpolate(xs, ys, frequency)
                if request.get('reference'):
                    _, _, rx, ry = _extract_series(data, request['reference'], plot_index=plot_index)
                    denominator = interpolate(rx, ry, frequency)
                    if abs(denominator) == 0:
                        raise ValueError('Reference signal is zero')
                    value = abs(sample / denominator)
                    unit = ''
                    extra.update({'frequency_hz': frequency, 'reference': request['reference']})
                else:
                    value = abs(sample)
                    extra['frequency_hz'] = frequency
            elif metric == 'bandwidth_3db':
                if len(xs) < 2:
                    raise ValueError('bandwidth_3db requires at least two frequency samples')
                mags, gains_db, _ = _ac_transfer_samples(
                    data, xs, ys, request['reference'], plot_index
                )
                drop_db = finite(request.get('threshold', 3.0))
                if drop_db <= 0:
                    raise ValueError('bandwidth_3db threshold drop in dB must be positive')
                if mags[0] == 0:
                    raise ValueError('Passband gain at first frequency point is zero')
                target_db = gains_db[0] - drop_db
                target_mag = mags[0] * (10.0 ** (-drop_db / 20.0))
                cutoff = None
                for f_a, f_b, g_a, g_b, m_a, m_b in zip(
                    xs, xs[1:], gains_db, gains_db[1:], mags, mags[1:]
                ):
                    if g_a >= target_db >= g_b and g_a > g_b:
                        if math.isfinite(g_b):
                            cutoff = f_a + (f_b - f_a) * (target_db - g_a) / (g_b - g_a)
                        else:
                            cutoff = f_a + (f_b - f_a) * (target_mag - m_a) / (m_b - m_a)
                        break
                if cutoff is None:
                    raise ValueError(f'Gain never drops by {drop_db:g} dB below passband gain')
                value = cutoff
                unit = 'Hz'
                extra['reference'] = request['reference']
            else:  # phase_margin
                if len(xs) < 2:
                    raise ValueError('phase_margin requires at least two frequency samples')
                mags, gains_db, phases_deg = _ac_transfer_samples(
                    data, xs, ys, request['reference'], plot_index
                )
                margin = None
                for f_a, f_b, g_a, g_b, m_a, m_b, p_a, p_b in zip(
                    xs, xs[1:], gains_db, gains_db[1:], mags, mags[1:], phases_deg, phases_deg[1:]
                ):
                    if g_a >= 0.0 >= g_b and g_a > g_b:
                        if math.isfinite(g_b):
                            frac = (0.0 - g_a) / (g_b - g_a)
                        else:
                            frac = (1.0 - m_a) / (m_b - m_a)
                        f_u = f_a + (f_b - f_a) * frac
                        delta_p = (p_b - p_a + 180.0) % 360.0 - 180.0
                        phase_u = p_a + frac * delta_p
                        pm = (180.0 + phase_u) % 360.0
                        if pm > 180.0:
                            pm -= 360.0
                        margin = 0.0 + pm
                        extra['unity_gain_frequency_hz'] = f_u
                        break
                if margin is None:
                    raise ValueError('Gain never crosses 0 dB downward')
                value = margin
                unit = 'deg'
                extra['reference'] = request['reference']
        else:
            if target_plot.get('complex'):
                raise ValueError('Time-domain measurements require a real plot')
            span = xs[-1] - xs[0]
            if metric == 'min':
                value = min(ys)
            elif metric == 'max':
                value = max(ys)
            elif metric == 'peak_to_peak':
                value = max(ys) - min(ys)
            elif metric == 'mean':
                value = sum((b - a) * (u + v) / 2 for a, b, u, v in zip(xs, xs[1:], ys, ys[1:])) / span if span else ys[0]
            elif metric == 'rms':
                value = math.sqrt(sum((b - a) * (u * u + u * v + v * v) / 3 for a, b, u, v in zip(xs, xs[1:], ys, ys[1:])) / span) if span else abs(ys[0])
            elif metric in ('frequency', 'duty_cycle', 'period'):
                if span <= 0:
                    raise ValueError('Measurement needs a nonzero time window')
                if 'threshold' not in request and min(ys) == max(ys):
                    raise ValueError('Constant signal needs an explicit threshold')
                threshold = finite(request.get('threshold', (min(ys) + max(ys)) / 2))
                rising = []
                high = 0.0
                for a, b, u, v in zip(xs, xs[1:], ys, ys[1:]):
                    if u < threshold <= v:
                        rising.append(a + (b - a) * (threshold - u) / (v - u))
                    if u >= threshold and v >= threshold:
                        high += b - a
                    elif (u >= threshold) != (v >= threshold):
                        cross = a + (b - a) * (threshold - u) / (v - u)
                        high += (cross - a) if u >= threshold else (b - cross)
                if metric in ('frequency', 'period'):
                    if len(rising) < 2:
                        raise ValueError('Frequency needs at least two rising crossings')
                    dt = rising[-1] - rising[0]
                    if dt <= 0:
                        raise ValueError('Frequency needs rising crossings at distinct times')
                    freq = (len(rising) - 1) / dt
                    if metric == 'frequency':
                        value = freq
                        unit = 'Hz'
                    else:
                        value = 1.0 / freq
                        unit = 's'
                else:
                    value = high / span
                    unit = 'fraction'
            elif metric == 'rise_time':
                if span <= 0:
                    raise ValueError('Measurement needs a nonzero time window')
                value = _rise_time(xs, ys)
                unit = 's'
            elif metric == 'fall_time':
                if span <= 0:
                    raise ValueError('Measurement needs a nonzero time window')
                value = _fall_time(xs, ys)
                unit = 's'
            elif metric == 'overshoot':
                # Percent overshoot relative to step (ys[-1] - ys[0]); for falling steps, measures undershoot below ys[-1].
                initial, steady = ys[0], ys[-1]
                step = steady - initial
                if step == 0:
                    raise ValueError('Overshoot requires distinct initial and final steady-state values')
                excursion = (max(ys) - steady) if step > 0 else (steady - min(ys))
                value = (excursion / abs(step)) * 100.0
                unit = '%'
            elif metric == 'settling_time':
                if target_plot.get('digital') or plot_axis_kind(target_plot) != 'time':
                    raise ValueError('Settling time requires a real transient waveform')
                final = request.get('final_value', ys[-1])
                tolerance = request.get('tolerance', 0.02)
                value = _settling_time(xs, ys, final, tolerance)
                unit = 's'
                extra.update(tolerance=tolerance, final_value=final)
            else:
                raise ValueError('Unsupported measurement: ' + metric)
        if not math.isfinite(value):
            raise ValueError('Nonfinite measurement result')
        results.append({
            'id': identifier, 'metric': metric, 'signal': signal,
            'value': value, 'unit': unit, 'start': xs[0], 'stop': xs[-1], **extra
        })
    return results
