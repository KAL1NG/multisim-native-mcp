"""Native geometry checks and orthogonal obstacle routing."""
import heapq
import itertools


def intersects(a,b,r):
    if a['x']==b['x']:
        return r['left']<a['x']<r['right'] and max(min(a['y'],b['y']),r['top'])<min(max(a['y'],b['y']),r['bottom'])
    if a['y']==b['y']:
        return r['top']<a['y']<r['bottom'] and max(min(a['x'],b['x']),r['left'])<min(max(a['x'],b['x']),r['right'])
    # Slab intersection for diagonal routes.
    lo,hi=0.,1.
    for axis,l,h in [('x','left','right'),('y','top','bottom')]:
        delta=b[axis]-a[axis]
        if not delta:
            if not r[l]<a[axis]<r[h]:return False
        else:
            p,q=sorted(((r[l]-a[axis])/delta,(r[h]-a[axis])/delta));lo=max(lo,p);hi=min(hi,q)
    return lo<hi


def check_layout(components,wires):
    pins={p['id']:p for c in components for p in c['pins']};issues=[]
    def overlaps(x,y):
        return max(x['left'],y['left'])<min(x['right'],y['right']) and max(x['top'],y['top'])<min(x['bottom'],y['bottom'])
    def body(c):return c.get('body_bounds') or c['bounds']
    def labels(c):return [l for l in c.get('labels',[]) if l.get('text') and l.get('bounds')]
    for a,b in itertools.combinations(components,2):
        if overlaps(body(a),body(b)):
            issues.append({'kind':'component_overlap','severity':'warning','components':[a['ref'],b['ref']],'collision_target':'body'})
        for owner,other in ((a,b),(b,a)):
            for label in labels(owner):
                if overlaps(label['bounds'],body(other)):
                    issues.append({'kind':'label_overlap','severity':'warning','component':owner['ref'],'other_component':other['ref'],
                                   'collision_target':'label','label_kind':label['kind'],'label_id':label.get('id'),'suggestion':'move_component_label'})
        for la,lb in itertools.product(labels(a),labels(b)):
            if overlaps(la['bounds'],lb['bounds']):
                issues.append({'kind':'label_overlap','severity':'warning','components':[a['ref'],b['ref']],
                               'collision_target':'label','label_kinds':[la['kind'],lb['kind']],
                               'label_ids':[la.get('id'),lb.get('id')],'suggestion':'move_component_label'})
    for wire in wires:
        points=wire['points']
        if len(points)<2:
            issues.append({'kind':'missing_route','severity':'error','wire':wire['id']});continue
        for end,index in [('source',0),('target',-1)]:
            endpoint=pins.get(wire[end]['id'],wire[end])
            if all(k in endpoint for k in ('x','y')) and any(endpoint[k]!=points[index][k] for k in ('x','y')):
                issues.append({'kind':'detached_endpoint','severity':'error','wire':wire['id'],'end':end})
            graphic=endpoint.get('graphic_position')
            if graphic and any(abs(graphic[k]-points[index][k])>.5 for k in ('x','y')):
                issues.append({'kind':'graphic_endpoint_mismatch','severity':'error','wire':wire['id'],'end':end,
                               'graphic_position':graphic,'wire_position':points[index]})
        if wire.get('has_pen') is False:issues.append({'kind':'invisible_wire','severity':'error','wire':wire['id']})
        for n,(a,b) in enumerate(zip(points,points[1:])):
            if a['x']!=b['x'] and a['y']!=b['y']:
                issues.append({'kind':'diagonal_segment','severity':'warning','wire':wire['id'],'segment':n})
            for c in components:
                attached=any(e.get('component_id')==c.get('id') if e.get('component_id') else e.get('ref')==c['ref'] for e in (wire['source'],wire['target']))
                if not attached and intersects(a,b,body(c)):
                    issues.append({'kind':'wire_crosses_component','severity':'warning','wire':wire['id'],'segment':n,'component':c['ref'],'collision_target':'body'})
                for label in labels(c):
                    if intersects(a,b,label['bounds']):
                        issues.append({'kind':'wire_overlaps_label','severity':'warning','wire':wire['id'],'segment':n,'component':c['ref'],
                                       'collision_target':'label','label_kind':label['kind'],'label_id':label.get('id'),'suggestion':'move_component_label'})
    errors=sum(i['severity']=='error' for i in issues)
    return {'passed':not issues,'errors':errors,'warnings':len(issues)-errors,'issues':issues,
            'component_count':len(components),'wire_count':len(wires)}


def orthogonal_path(start,end,obstacles,turn_cost=9):
    xs=sorted({start['x'],end['x'],*(r[k] for r in obstacles for k in ('left','right'))})
    ys=sorted({start['y'],end['y'],*(r[k] for r in obstacles for k in ('top','bottom'))})
    def point(x,y):return {'x':xs[x],'y':ys[y]}
    def inside(p):return any(r['left']<p['x']<r['right'] and r['top']<p['y']<r['bottom'] for r in obstacles)
    if inside(start) or inside(end):raise ValueError('Route endpoint lies inside an obstacle')
    source=(xs.index(start['x']),ys.index(start['y']),-1);target=(xs.index(end['x']),ys.index(end['y']))
    distance={source:0};parent={};queue=[(0,0,source)];visited=0
    while queue:
        _,cost,current=heapq.heappop(queue)
        if cost!=distance[current]:continue
        visited+=1
        x,y,direction=current
        if (x,y)==target:
            route=[]
            while True:
                route.append(point(current[0],current[1]))
                if current==source:break
                current=parent[current]
            return simplify(list(reversed(route)))
        a=point(x,y)
        for nx,ny,nd in [(x-1,y,0),(x+1,y,0),(x,y-1,1),(x,y+1,1)]:
            if not (0<=nx<len(xs) and 0<=ny<len(ys)):continue
            b=point(nx,ny)
            if inside(b) or any(intersects(a,b,r) for r in obstacles):continue
            new=(nx,ny,nd);value=cost+abs(a['x']-b['x'])+abs(a['y']-b['y'])+(turn_cost if direction not in (-1,nd) else 0)
            if value<distance.get(new,float('inf')):
                distance[new]=value;parent[new]=current
                heuristic=abs(b['x']-end['x'])+abs(b['y']-end['y'])
                heapq.heappush(queue,(value+heuristic,value,new))
    raise ValueError('No obstacle-free orthogonal path')


def simplify(points):
    result=[]
    for p in points:
        if result and p==result[-1]:continue
        if len(result)>1 and ((result[-2]['x']==result[-1]['x']==p['x']) or (result[-2]['y']==result[-1]['y']==p['y'])):result.pop()
        result.append(p)
    return result


def plan_wire(components,wire,clearance=9):
    if isinstance(clearance,bool) or not isinstance(clearance,int) or clearance<0:raise ValueError('Clearance must be nonnegative')
    obstacles=[{k:v+(-clearance if k in ('left','top') else clearance) for k,v in (c.get('body_bounds') or c['bounds']).items()} for c in components]
    by_id={c['id']:i for i,c in enumerate(components) if c.get('id')}
    by_pin={p['id']:i for i,c in enumerate(components) for p in c.get('pins',[]) if p.get('id')}
    by_ref={c['ref']:i for i,c in enumerate(components)}
    def in_rect(pt,r):return r['left']<pt['x']<r['right'] and r['top']<pt['y']<r['bottom']
    leads=[]
    for end,index in [('source',0),('target',-1)]:
        p=dict(wire['points'][index]);ep=wire[end]
        cid=ep.get('component_id');pid=ep.get('id')
        owner=by_id[cid] if cid and cid in by_id else by_pin[pid] if pid and pid in by_pin else by_ref.get(ep.get('ref'))
        if owner is None:leads.append((p,p));continue
        r=obstacles[owner]
        if not in_rect(p,r):
            if any(in_rect(p,o) for i,o in enumerate(obstacles) if i!=owner):
                raise ValueError('Pin escape is blocked by another component')
            leads.append((p,p));continue
        candidates=sorted([{'x':r['left'],'y':p['y']},{'x':r['right'],'y':p['y']},
                           {'x':p['x'],'y':r['top']},{'x':p['x'],'y':r['bottom']}],
                          key=lambda q:abs(q['x']-p['x'])+abs(q['y']-p['y']))
        escape=next((q for q in candidates if not any(in_rect(q,o) or intersects(p,q,o) for i,o in enumerate(obstacles) if i!=owner)),None)
        if escape is None:raise ValueError('Pin escape is blocked by another component')
        leads.append((p,escape))
    middle=orthogonal_path(leads[0][1],leads[1][1],obstacles)
    points=simplify([leads[0][0],*middle,leads[1][0]])
    return {'wire_id':wire['id'],'points':points,'clearance':clearance,
            'length':sum(abs(a['x']-b['x'])+abs(a['y']-b['y']) for a,b in zip(points,points[1:]))}
