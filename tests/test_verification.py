import pytest
from multisim_native_mcp.verification import verify,decode_display,SEGMENTS


def test_acceptance_and_failure():
    measurements=[{'id':'v','value':6}]
    assert verify(measurements,[{'measurement':'v','target':6.01,'absolute_tolerance':.02}])['passed']
    assert not verify(measurements,[{'measurement':'v','max':5.99}])['passed']
    for criteria in [[],[{'measurement':'missing','min':0}],[{'measurement':'v'}]]:
        with pytest.raises(ValueError):verify(measurements,criteria)


def fixture(wrong=False,conflict=False):
    names=['time']+[f's{i}' for i in range(7)]+['d0','d1']
    rows=[]
    for n in range(41):
        digit=(n//10)%2;number='1' if digit==0 else ('3' if wrong else '2')
        pattern=next(k for k,v in SEGMENTS.items() if v==number)
        rows.append([n*.001]+[5*int(v) for v in pattern]+[5 if digit==0 or conflict else 0,5 if digit==1 or conflict else 0])
    data={'complex':False,'rows':rows,'variables':[{'index':i,'name':n,'native_name':n} for i,n in enumerate(names)]}
    digits=[{'segments':names[1:8],'select':f'd{i}'} for i in range(2)]
    return data,digits


def test_decode_stable_scanned_display_and_wrong_or_conflicting_selection():
    for wrong,conflict,passed in [(False,False,True),(True,False,False),(False,True,False)]:
        data,digits=fixture(wrong,conflict)
        result=decode_display(data,digits,'12',settling=.002,min_dwell=.001)
        assert result['passed']==passed


def test_decode_display_with_digital_additional_plots():
    # Digit 0 shows '4' ('0110011') from 0..0.01s, Digit 1 shows '7' ('1110000') from 0.01..0.02s
    pat0 = SEGMENTS and next(k for k, v in SEGMENTS.items() if v == '4')
    pat1 = next(k for k, v in SEGMENTS.items() if v == '7')
    additional = []
    for seg_idx in range(7):
        b0, b1 = int(pat0[seg_idx]), int(pat1[seg_idx])
        events = [[0.0, float(b0 == 1), float(b0 == 0)]]
        if b1 != b0:
            events.append([0.01, float(b1 == 1), float(b1 == 0)])
        additional.append({
            'plot': 'Digital',
            'complex': False,
            'digital': True,
            'variables': [
                {'index': 0, 'name': 'time', 'native_name': 'time', 'kind': 'time'},
                {'index': 1, 'name': f'D(seg{seg_idx})', 'native_name': f'seg{seg_idx}', 'kind': 'voltage'},
            ],
            'rows': events,
        })
    for d_idx, rows in enumerate([
        [[0.0, 1.0, 0.0], [0.01, 0.0, 1.0]],
        [[0.0, 0.0, 1.0], [0.01, 1.0, 0.0]],
    ]):
        additional.append({
            'plot': 'Digital',
            'complex': False,
            'digital': True,
            'variables': [
                {'index': 0, 'name': 'time', 'native_name': 'time', 'kind': 'time'},
                {'index': 1, 'name': f'D(sel{d_idx})', 'native_name': f'sel{d_idx}', 'kind': 'voltage'},
            ],
            'rows': rows,
        })
    data = {
        'complex': False,
        'digital': False,
        'variables': [
            {'index': 0, 'name': 'time', 'native_name': 'time', 'kind': 'time'},
            {'index': 1, 'name': 'V(vcc)', 'native_name': 'vcc', 'kind': 'voltage'},
        ],
        'rows': [[0.0, 5.0], [0.02, 5.0]],
        'additional_plots': additional,
    }
    digits = [
        {'segments': [f'D(seg{i})' for i in range(7)], 'select': 'D(sel0)'},
        {'segments': [f'D(seg{i})' for i in range(7)], 'select': 'D(sel1)'},
    ]
    decoded = decode_display(data, digits, expected='47', settling=0.0005, min_dwell=0.002)
    assert decoded['passed'] and decoded['decoded'] == '47'
