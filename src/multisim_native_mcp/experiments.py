"""Native parameter experiments with checkpoint restoration."""
import itertools
from pathlib import Path
from .measurements import finite,measure
from .verification import verify
from .waveforms import parse_raw
from .contracts import normalize_measurements,normalize_criteria


def _normalize_parameter(raw):
    if not isinstance(raw,dict):raise ValueError('Sweep parameter must be an object')
    p=dict(raw)
    if set(p)-{'ref','component_ref','index','name','role','values'}:raise ValueError('Invalid sweep parameter fields')
    if 'component_ref' in p:
        alias=p.pop('component_ref')
        if alias is not None:
            if p.get('ref') is not None and p['ref']!=alias:
                raise ValueError('Conflicting component_ref and ref; provide one value for this selector')
            p['ref']=alias
    for k in ('index','name','role'):
        if k in p and p[k] is None:p.pop(k)
    if not isinstance(p.get('ref'),str) or not p['ref'].strip() or '\0' in p['ref']:
        raise ValueError('Sweep parameter requires a non-empty component ref')
    if 'index' in p:
        if isinstance(p['index'],bool) or not isinstance(p['index'],int) or not 0<=p['index']<=2147483647:
            raise ValueError('Invalid parameter index')
        if 'name' in p or 'role' in p:
            raise ValueError('Provide parameter index or name/role, not both')
    else:
        if 'name' in p and (not isinstance(p['name'],str) or not p['name'].strip() or '\0' in p['name']):
            raise ValueError('Invalid parameter name')
        if 'role' in p and (not isinstance(p['role'],str) or not p['role'].strip() or '\0' in p['role']):
            raise ValueError('Invalid parameter role')
    if not isinstance(p.get('values'),list) or not p['values']:raise ValueError('Provide nonempty sweep values')
    for value in p['values']:
        if isinstance(value,bool):raise ValueError('Sweep values must be finite numbers')
        finite(value)
    return p


def _normalize_objective(objective,ids=None):
    if not objective:return None
    if not isinstance(objective,dict) or set(objective)-{'id','measurement','goal','target'}:
        raise ValueError('Invalid objective')
    obj=dict(objective)
    if 'id' in obj and 'measurement' in obj and obj['id']!=obj['measurement']:
        raise ValueError('id and measurement must refer to the same measurement')
    target_id=obj.get('measurement') if obj.get('measurement') is not None else obj.get('id')
    if not isinstance(target_id,str) or not target_id or obj.get('goal') not in ('min','max','target'):
        raise ValueError('Invalid objective')
    if ids is not None and target_id not in ids:raise ValueError('Invalid objective')
    if obj['goal']=='target':
        if 'target' not in obj or isinstance(obj['target'],bool):raise ValueError('Invalid objective')
        finite(obj['target'])
    obj['measurement']=obj['id']=target_id
    return obj


def validate_spec(parameters,analysis,measurements,criteria,objective):
    if not isinstance(parameters,list) or not parameters:raise ValueError('Provide nonempty sweep parameters')
    seen=set();total=1
    for raw in parameters:
        p=_normalize_parameter(raw)
        selector=('index',p['index']) if 'index' in p else ('selector',p.get('name'),p.get('role',None if 'name' in p else 'value'))
        key=(p['ref'],selector)
        if key in seen:raise ValueError('Duplicate sweep parameter')
        seen.add(key)
        total*=len(p['values'])
    allowed={'analysis','step','stop','use_initial_conditions','ac_sweep','ac_points','ac_start','ac_stop',
             'dc_source','dc_start','dc_stop','dc_step'}
    if not isinstance(analysis,dict) or set(analysis)-allowed:raise ValueError('Invalid analysis options')
    if 'analysis' in analysis and analysis['analysis'] not in ('op','tran','ac','dc'):
        raise ValueError('Invalid analysis options')
    if analysis.get('analysis')=='dc':
        source=analysis.get('dc_source')
        if not isinstance(source,str) or not source.strip() or '\0' in source:
            raise ValueError('DC sweep requires a non-empty dc_source')
        for k in ('dc_start','dc_stop','dc_step'):
            if k not in analysis or analysis[k] is None or isinstance(analysis[k],bool):
                raise ValueError('DC sweep requires finite dc_start, dc_stop, and dc_step')
            finite(analysis[k])
        if analysis['dc_step']==0 or (analysis['dc_stop']-analysis['dc_start'])*analysis['dc_step']<=0:
            raise ValueError('DC sweep requires non-zero dc_step moving from dc_start toward dc_stop')
    measurements=normalize_measurements(measurements)
    ids=[m.get('id',str(i)) for i,m in enumerate(measurements)]
    if len(set(ids))!=len(ids):raise ValueError('Duplicate measurement IDs')
    normalize_criteria(criteria,set(ids),allow_empty=True)
    _normalize_objective(objective,ids)
    return total


def _check_interactive_idle(host):
    sim_info=None
    if hasattr(host,'interactive_status') and not hasattr(host,'call'):
        sim_info=host.interactive_status()
    elif hasattr(host,'call'):
        try:sim_info=host.call('simulationInfo',{})
        except TypeError:
            try:sim_info=host.call('simulationInfo')
            except (KeyError,AssertionError,NotImplementedError):sim_info=None
        except (KeyError,AssertionError,NotImplementedError):sim_info=None
        if sim_info is None and hasattr(host,'interactive_status'):
            try:sim_info=host.interactive_status()
            except (KeyError,AssertionError,NotImplementedError):sim_info=None
    if isinstance(sim_info,dict) and (sim_info.get('state') in (1,2) or sim_info.get('state_name') in ('running','paused')):
        raise RuntimeError('Stop interactive simulation before running a parameter sweep')


def run_sweep(host,parameters,analysis,measurements,criteria=None,objective=None,cancel=None,progress=None):
    criteria=criteria or [];total=validate_spec(parameters,analysis,measurements,criteria,objective)
    normalized_params=[_normalize_parameter(p) for p in parameters]
    objective=_normalize_objective(objective)
    trials=[];result={'status':'running','total':total,'trials':trials,'best':None,'restored':False}
    with host.lock:
        _check_interactive_idle(host)
        originals=[];resolved_params=[];resolved_seen=set()
        for parameter in normalized_params:
            info=host.call('parameters',{'ref':parameter['ref']})
            available=info['parameters']
            if 'index' in parameter:
                matches=[p for p in available if p['index']==parameter['index']]
                if not matches:raise ValueError('Parameter index not found')
                slot=matches[0]
            else:
                role=parameter.get('role',None if 'name' in parameter else 'value')
                matches=[p for p in available if ('name' not in parameter or p.get('name')==parameter['name'])
                         and (role is None or p.get('role')==role)]
                if len(matches)!=1:raise ValueError('Parameter selector must match one slot')
                slot=matches[0]
            rkey=(info.get('ci') or parameter['ref'],slot['index'])
            if rkey in resolved_seen:raise ValueError('Duplicate sweep parameter')
            resolved_seen.add(rkey)
            resolved_params.append({'ref':parameter['ref'],'index':slot['index'],'values':parameter['values']})
            originals.append({'ref':parameter['ref'],**slot})
        checkpoint=host.checkpoint();result['checkpoint']=checkpoint['path']
        try:
            for n,values in enumerate(itertools.product(*(p['values'] for p in resolved_params))):
                if cancel and cancel.is_set():result['status']='cancelled';break
                trial={'index':n,'parameters':[{'ref':p['ref'],'index':p['index'],'value':v} for p,v in zip(resolved_params,values)]}
                trials.append(trial)
                try:
                    for parameter in trial['parameters']:
                        host.validate('setParameter',parameter);host.call('setParameter',parameter)
                    native=host.run_analysis(**analysis)
                    if isinstance(native,dict) and native.get('id_map'):
                        id_map=native['id_map']
                        for p in resolved_params:
                            if p['ref'] in id_map:p['ref']=id_map[p['ref']]
                        for orig in originals:
                            if orig['ref'] in id_map:orig['ref']=id_map[orig['ref']]
                    trial['analysis']=native
                    trial['measurements']=measure(parse_raw(Path(native['raw_path'])),measurements)
                    trial['acceptance']=verify(trial['measurements'],criteria) if criteria else {'passed':True,'criteria':[]}
                    trial['status']='complete';trial['feasible']=trial['acceptance']['passed']
                    if objective:
                        value=next(m['value'] for m in trial['measurements'] if m['id']==objective['measurement'])
                        trial['score']=-value if objective['goal']=='max' else abs(value-objective['target']) if objective['goal']=='target' else value
                except Exception as error:
                    trial.update(status='cancelled' if cancel and cancel.is_set() else 'failed',error=str(error),feasible=False)
                if progress:progress(result)
            if cancel and cancel.is_set():result['status']='cancelled'
            if result['status']=='running':result['status']='complete' if all(t['status']=='complete' for t in trials) else 'failed'
            feasible=[t for t in trials if t.get('feasible')]
            if feasible:result['best']=(min(feasible,key=lambda t:t['score']) if objective else feasible[0])['index']
        finally:
            try:
                for p in originals:
                    if p.get('value') is not None:host.call('setParameter',{'ref':p['ref'],'index':p['index'],'value':p['value']})
                    expr=p.get('expression')
                    if isinstance(expr,str) and expr.strip():
                        host.call('setParameter',{'ref':p['ref'],'index':p['index'],'expression':expr})
                result['restored']=True
            except Exception:
                host.restore(checkpoint);result['restored']=True
            if progress:progress(result)
    return result
