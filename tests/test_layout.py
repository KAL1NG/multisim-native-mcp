import pytest
from multisim_native_mcp.layout import orthogonal_path,intersects,check_layout,plan_wire


def test_route_around_blocked_direct_path():
    obstacle={'left':20,'right':40,'top':-10,'bottom':10}
    route=orthogonal_path({'x':0,'y':0},{'x':60,'y':0},[obstacle])
    assert route[0]=={'x':0,'y':0} and route[-1]=={'x':60,'y':0}
    assert all(a['x']==b['x'] or a['y']==b['y'] for a,b in zip(route,route[1:]))
    assert not any(intersects(a,b,obstacle) for a,b in zip(route,route[1:]))


def test_detect_electrical_endpoint_mismatch_and_hidden_wire():
    components=[{'ref':'R1','bounds':{'left':10,'top':10,'right':30,'bottom':30},
                 'pins':[{'id':'p','x':10,'y':20}]}]
    wires=[{'id':'w','source':{'id':'p','ref':'R1'},'target':{'id':'j','x':50,'y':20},
            'points':[{'x':9,'y':20},{'x':50,'y':20}],'has_pen':False}]
    result=check_layout(components,wires)
    assert result['errors']==2
    assert {i['kind'] for i in result['issues']}=={'detached_endpoint','invisible_wire'}


def test_detect_graphic_gap_even_when_electrical_endpoint_matches():
    wires=[{'id':'w','source':{'id':'p','x':270,'y':423,'graphic_position':{'x':269,'y':420}},
            'target':{'id':'j','x':315,'y':423,'graphic_position':{'x':315,'y':423}},
            'points':[{'x':270,'y':423},{'x':315,'y':423}]}]
    result=check_layout([],wires)
    assert result['errors']==1
    assert result['issues'][0]['kind']=='graphic_endpoint_mismatch'
    assert result['issues'][0]['end']=='source'


def test_plan_wire_shared_power_id_body_bounds_multi_edge_escape_and_bool_guard():
    for bad_clearance in (True, False, -1, 1.5):
        with pytest.raises(ValueError):
            plan_wire([], {'id': 'w', 'source': {}, 'target': {}, 'points': [{'x': 0, 'y': 0}, {'x': 9, 'y': 0}]}, bad_clearance)

    # Two shared VCC symbols with distinct IDs + moved label bloating `bounds` but not `body_bounds`,
    # plus an adjacent blocker blocking the nearest (top) escape of c1 so plan_wire must pick another escape edge!
    components = [
        {
            'id': 'vcc_left',
            'ref': 'VCC',
            'body_bounds': {'left': 90, 'top': 90, 'right': 110, 'bottom': 120},
            'bounds': {'left': 0, 'top': 0, 'right': 500, 'bottom': 500},  # bloated by moved label
            'pins': [{'id': 'p_left', 'name': 'VCC', 'x': 100, 'y': 92}],
        },
        {
            'id': 'vcc_right',
            'ref': 'VCC',
            'body_bounds': {'left': 290, 'top': 90, 'right': 310, 'bottom': 120},
            'bounds': {'left': 290, 'top': 90, 'right': 310, 'bottom': 120},
            'pins': [{'id': 'p_right', 'name': 'VCC', 'x': 300, 'y': 118}],
        },
        {
            # Blocks the top escape (y = 81) of vcc_left (inflated bottom = 87 < 92), forcing escape via left/right/bottom
            'id': 'blocker_top',
            'ref': 'R_TOP',
            'body_bounds': {'left': 85, 'top': 50, 'right': 115, 'bottom': 78},
            'bounds': {'left': 85, 'top': 50, 'right': 115, 'bottom': 78},
            'pins': [],
        },
    ]
    wire = {
        'id': 'w_vcc',
        'source': {'id': 'p_left', 'ref': 'VCC', 'component_id': 'vcc_left', 'pin': 'VCC'},
        'target': {'id': 'p_right', 'ref': 'VCC', 'component_id': 'vcc_right', 'pin': 'VCC'},
        'points': [{'x': 100, 'y': 92}, {'x': 300, 'y': 118}],
    }
    planned = plan_wire(components, wire, clearance=9)
    assert planned['points'][0] == {'x': 100, 'y': 92}
    assert planned['points'][-1] == {'x': 300, 'y': 118}
    assert all(a['x'] == b['x'] or a['y'] == b['y'] for a, b in zip(planned['points'], planned['points'][1:]))
    assert not any(intersects(a, b, components[2]['body_bounds']) for a, b in zip(planned['points'], planned['points'][1:]))

    # Blocking all 4 escape edges raises ValueError
    surrounded = [
        components[0],
        components[1],
        {'id': 'b_top', 'ref': 'B1', 'body_bounds': {'left': 70, 'top': 60, 'right': 130, 'bottom': 85}, 'bounds': {}, 'pins': []},
        {'id': 'b_bot', 'ref': 'B2', 'body_bounds': {'left': 70, 'top': 125, 'right': 130, 'bottom': 150}, 'bounds': {}, 'pins': []},
        {'id': 'b_lft', 'ref': 'B3', 'body_bounds': {'left': 50, 'top': 70, 'right': 85, 'bottom': 130}, 'bounds': {}, 'pins': []},
        {'id': 'b_rgt', 'ref': 'B4', 'body_bounds': {'left': 115, 'top': 70, 'right': 150, 'bottom': 130}, 'bounds': {}, 'pins': []},
    ]
    with pytest.raises(ValueError, match='Pin escape is blocked'):
        plan_wire(surrounded, wire, clearance=9)
