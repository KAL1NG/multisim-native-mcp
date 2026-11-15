"""Conservative diagnostics for native SPICE power bridges and failed commands."""
import re


RAILS={'VDD','VSS','VCC','VEE','GND'}


def statements(content):
    """Unfold SPICE continuation lines, excluding comments and subcircuit bodies."""
    lines=[]
    for raw in content.splitlines():
        line=raw.strip()
        if not line or line.startswith('*'):continue
        if line.startswith('+') and lines:lines[-1]+=' '+line[1:]
        else:lines.append(line)
    depth=0
    for line in lines:
        tokens=line.split()
        head=tokens[0].lower()
        if head=='.subckt':depth+=1
        elif head=='.ends':depth=max(0,depth-1)
        elif not depth and not head.startswith('.'):yield tokens


def hidden_power_diagnostics(content,components=()):
    dependencies={};defined=set();graph={};uncertain=set()
    for tokens in statements(content):
        name=tokens[0];kind=name[0].upper()
        # Multisim's analog/digital bridges carry hidden global rail arguments.
        bridge=kind=='X' and any(re.match(r'(CMOS|TTL).*_(RCV|DRV)',t,re.I) for t in tokens[1:])
        if bridge:
            owner=name[1:].rsplit('.',1)[0]
            for token in tokens[1:]:
                if token.upper() in RAILS:dependencies.setdefault(token.upper(),set()).add(owner.upper())
            continue
        count={'R':2,'C':2,'L':2,'V':2,'I':2,'D':2,'Q':3,'M':4,'J':3,'E':4,'G':4,'F':2,'H':2}.get(kind)
        nodes=tokens[1:1+count] if count else tokens[1:-1] if kind=='X' else []
        defined.update(n.upper() for n in nodes)
        # Only claim a DC connection for simple conductive elements. Capacitors,
        # current sources and bridge pins do not establish a supply reference.
        if kind in ('R','L','V') and len(nodes)>=2:
            a,b=(n.upper() for n in nodes[:2])
            graph.setdefault(a,set()).add(b);graph.setdefault(b,set()).add(a)
        elif kind not in ('C','I'):uncertain.update(n.upper() for n in nodes)
    grounded={'0'};pending=['0']
    while pending:
        for node in graph.get(pending.pop(),()):
            if node not in grounded:grounded.add(node);pending.append(node)
    result=[]
    for rail,owners in sorted(dependencies.items()):
        if rail in grounded:continue
        island={rail};pending=[rail]
        while pending:
            for node in graph.get(pending.pop(),()):
                if node not in island:island.add(node);pending.append(node)
        # Nonlinear/subcircuit supplies cannot be proven floating by this scan.
        if rail in defined and island&uncertain:continue
        missing=rail not in defined
        parts=[]
        for owner in sorted(owners):
            part=next((c for c in components if c.get('ref','').upper()==owner),{})
            library=part.get('library',{}).get('name')
            parts.append({'ref':part.get('ref',owner),**({'name':library} if library else {})})
        description=', '.join(p['ref']+(' ('+p['name']+')' if p.get('name') else '') for p in parts)
        reason='the top-level netlist has no external connection to this rail' if missing else 'its external DC network has no path to reference node 0 (capacitors/current sources do not establish a DC reference)'
        result.append({'kind':'hidden_power_rail','severity':'warning','node':rail,'components':parts,'reason':'missing_connection' if missing else 'floating_dc_network',
                       'message':f'{description} implicitly depends on {rail}, but {reason}. Add/connect a {rail} power symbol or net label to the intended supply (VSS/GND commonly to node 0).',
                       'suggestion':'connect_hidden_power_rail'})
    return result


def explain_analysis_failure(result,diagnostics,analysis,use_initial_conditions):
    """Use actual shell commands and netlist evidence; retain undocumented codes."""
    errors=result.get('errors') or [e for t in result.get('trace',[]) for e in t.get('errors',[])]
    explained=[]
    for error in errors:
        stages=[{'stage':t.get('stage'),'command':t.get('command')} for t in result.get('trace',[]) if error in t.get('errors',[])]
        explained.append({**error,'description':f'Native simulator reported status {error.get("code", "unknown")} for command id {error.get("command", "unknown")}',
                          'contexts':stages})
    messages=[result['error_text']] if result.get('error_text') else []
    messages.extend(d['message'] for d in diagnostics)
    if not messages:
        contexts=[t for t in result.get('trace',[]) if t.get('stage')==result.get('stage')]
        command=contexts[-1].get('command') if contexts else result.get('command')
        messages.append(f'Native simulator failed during {result.get("stage","analysis")}' + (f' executing {command!r}' if command else '') + '. Inspect netlist connectivity and solver convergence.')
    if explained:messages.append('; '.join(e['description'] for e in explained))
    hints=[]
    if analysis=='tran' and not use_initial_conditions:
        hints.append('For a self-starting oscillator, consider use_initial_conditions: true (UIC) with suitable startup conditions; verify its waveform.')
    return {'error_text':'\n'.join(messages),'diagnostics':diagnostics,'error_details':explained,'hints':hints}
