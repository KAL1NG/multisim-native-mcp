"""Typed waveform requests shared by tools and persisted experiments."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


MetricName = Literal[
    'min', 'max', 'mean', 'rms', 'peak_to_peak', 'frequency', 'duty_cycle',
    'period', 'rise_time', 'fall_time', 'overshoot', 'settling_time', 'value_at',
    'gain_db', 'phase_deg', 'magnitude', 'bandwidth_3db', 'phase_margin',
]


class MeasurementRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    id: str | None = Field(default=None, min_length=1)
    metric: MetricName
    signal: str = Field(min_length=1)
    start: float | None = None
    stop: float | None = None
    threshold: float | None = None
    reference: str | None = None
    frequency_hz: float | None = Field(default=None, gt=0)
    at: float | None = None
    tolerance: float | None = Field(default=None, gt=0, lt=1, description='Settling band as a fraction of step size. Defaults to 0.02.')
    final_value: float | None = Field(default=None, description='Expected steady value for settling_time. Defaults to the last sample.')
    plot_index: int = Field(default=0, ge=0)

    @field_validator('plot_index', mode='before')
    @classmethod
    def reject_bool_plot_index(cls, value):
        if isinstance(value, bool):
            raise ValueError('plot_index must be an integer')
        return value

    @field_validator('start', 'stop', 'threshold', 'frequency_hz', 'at', 'tolerance', 'final_value', mode='before')
    @classmethod
    def reject_bool_numbers(cls, value):
        if isinstance(value, bool):
            raise ValueError('Numeric measurement fields must not be boolean')
        return value

    @model_validator(mode='after')
    def ac_fields(self):
        if isinstance(self.signal, str) and not self.signal.strip():
            raise ValueError('signal must be nonempty')
        if isinstance(self.reference, str) and not self.reference.strip():
            raise ValueError('reference must be nonempty')
        if self.start is not None and self.stop is not None and self.start > self.stop:
            raise ValueError('Measurement start exceeds stop')
        if self.metric in ('gain_db', 'phase_deg') and (not self.reference or self.frequency_hz is None):
            raise ValueError('AC measurements require reference and frequency_hz')
        if self.metric == 'magnitude' and self.frequency_hz is None:
            raise ValueError('magnitude measurement requires frequency_hz')
        if self.metric in ('bandwidth_3db', 'phase_margin') and not self.reference:
            raise ValueError(f'{self.metric} measurement requires reference')
        if self.metric == 'bandwidth_3db' and self.threshold is not None and self.threshold <= 0:
            raise ValueError('bandwidth_3db threshold drop in dB must be positive')
        if self.metric == 'value_at' and self.at is None:
            raise ValueError('value_at measurement requires at')
        return self


class PinSignal(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    component_ref: str = Field(min_length=1)
    pin: str = Field(min_length=1)


class CircuitMeasurementRequest(MeasurementRequest):
    signal: str | PinSignal
    reference: str | PinSignal | None = None


class AcceptanceCriterion(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    id: str = Field(min_length=1, description='ID of the measurement to check; legacy measurement is also accepted.')
    min: float | None = None
    max: float | None = None
    target: float | None = None
    absolute_tolerance: float | None = Field(default=None, ge=0)
    relative_tolerance: float | None = Field(default=None, ge=0)

    @model_validator(mode='before')
    @classmethod
    def legacy_key(cls, value):
        if isinstance(value, dict) and 'measurement' in value:
            value = dict(value)
            legacy = value.pop('measurement')
            if 'id' in value and value['id'] != legacy:
                raise ValueError('id and measurement must refer to the same measurement')
            value['id'] = legacy
        return value

    @model_validator(mode='after')
    def bounds(self):
        if self.min is None and self.max is None and self.target is None:
            raise ValueError('Criterion needs min, max or target')
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError('Criterion min must not exceed max')
        return self


def normalize_requests(values, model, field, allow_empty=False):
    if not isinstance(values, list) or (not values and not allow_empty):
        raise ValueError(f'{field}: provide {"0" if allow_empty else "1"} or more entries')
    result = []
    measurement = issubclass(model, MeasurementRequest)
    for index, item in enumerate(values):
        try:
            if isinstance(item, BaseModel) and not isinstance(item, model):
                item = item.model_dump()
            parsed = item if isinstance(item, model) else model.model_validate(item)
        except ValidationError as error:
            messages = []
            for issue in error.errors(include_url=False):
                location = '.'.join(str(p) for p in issue['loc'])
                messages.append(f'{field}[{index}]' + ('.' + location if location else '') + ': ' + issue['msg'])
            raise ValueError('; '.join(messages)) from error
        entry = parsed.model_dump(exclude_none=True)
        if measurement:
            entry.setdefault('id', str(index))
            if entry.get('plot_index') == 0:
                entry.pop('plot_index', None)
        else:
            entry['measurement'] = entry['id']
        result.append(entry)
    if measurement and len({m['id'] for m in result}) != len(result):
        raise ValueError('measurements: IDs must be unique')
    return result


def normalize_measurements(values):
    return normalize_requests(values, MeasurementRequest, 'measurements')


def normalize_criteria(values, ids=None, allow_empty=False):
    result = normalize_requests(values, AcceptanceCriterion, 'criteria', allow_empty)
    if ids is not None:
        for index, criterion in enumerate(result):
            if criterion['id'] not in ids:
                raise ValueError(f'criteria[{index}].id: unknown measurement {criterion["id"]!r}; expected one of {sorted(ids)}')
    return result
