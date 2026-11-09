"""STDIO MCP endpoint. stdout is reserved for JSON-RPC."""
from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from functools import wraps
import re
from .service import EditorService

host = EditorService()


def checked(function):
    @wraps(function)
    def execute(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as error:
            raise ToolError(str(error)) from error
    return execute
server = MCPServer('multisim-native', version='0.2.1',
                   instructions='Edit native Multisim objects in isolated copies or explicitly attached existing windows. '
                   'Read exact pin names before wiring; save results before closing. '
                   'Undo, redo and netlist refresh can invalidate memory IDs; reread objects afterward. '
                   'Coordinates are native sheet units and may snap to grid. '
                   'Native Multisim 14.3 schematic editing and analog analysis.')


@server.tool()
@checked
def native_runtime_status() -> dict:
    """Check installed DLL hashes and native backend compatibility without starting Multisim."""
    return host.runtime_status()


@server.tool()
@checked
def native_diagnostics() -> dict:
    """Read captured native netlist errors, including background Netlist Viewer updates, without a modal dialog."""
    if not host.agent: return {'netlist_errors':[]}
    return host.agent.exports_sync.diagnostics()


@server.tool()
@checked
def native_open_copy(source_path: str) -> dict:
    """Start an isolated hidden Multisim process on a copy of an existing absolute .ms14 path."""
    return host.open_copy(source_path)


@server.tool()
@checked
def native_list_components() -> dict:
    """Read native component references, transforms, named pin IDs, coordinates and connection counts."""
    return host.call('components')


@server.tool()
@checked
def native_list_wires(component_ref: str | None = None) -> dict:
    """Read actual native wire endpoints and routed vertices, optionally filtering by component reference."""
    result = host.call('wires')
    if component_ref is not None:
        result['wires'] = [wire for wire in result['wires'] if any(wire[end].get('ref') == component_ref for end in ('source', 'target'))]
    return result


@server.tool()
@checked
def native_connect_pins(source_ref: str, source_pin: str, target_ref: str, target_pin: str) -> dict:
    """Create a real native electrical wire between exact named pins through CreateWireBase. Idempotent for a direct existing wire."""
    return host.edit('wire', {'source': {'ref': source_ref, 'pin': source_pin},
                              'target': {'ref': target_ref, 'pin': target_pin}})


@server.tool()
@checked
def native_move_component(component_ref: str, dx: int, dy: int) -> dict:
    """Move a native component by relative sheet units; preserve its native pin attachments. Grid snapping applies."""
    if max(abs(dx), abs(dy)) > 10000:
        raise ValueError('Movement must be within 10000 native units per axis')
    return host.edit('move', {'ref': component_ref, 'dx': dx, 'dy': dy})


@server.tool()
@checked
def native_save_copy(output_path: str, overwrite: bool = False) -> dict:
    """Save through native SaveProjectDocument to a separate absolute .ms14 output path. Existing output requires explicit overwrite and is backed up."""
    return host.save_copy(output_path, overwrite)


@server.tool()
@checked
def native_close_copy() -> dict:
    """Close an owned hidden host, or detach from an existing user's window without closing it. Save output first; checkpoints remain on disk."""
    return host.close()


@server.tool()
@checked
def native_attach(pid: int, project_index: int = 0) -> dict:
    """Attach to a specified existing Multisim PID; back up its unsaved native project before editing. Close only detaches; never terminates the user's process."""
    return host.attach(pid, project_index)


@server.tool()
@checked
def native_create_circuit(title: str = 'Circuit') -> dict:
    """Start a blank native 14.3 schematic in an owned host. Other Multisim windows must be closed."""
    return host.create(title)


@server.tool()
@checked
def native_search_library(query: str, limit: int = 20) -> dict:
    """Search the real installed master component library; returns exact native names and library IDs."""
    if not 1 <= limit <= 100 or len(query)>128: raise ValueError('Invalid search size')
    return host.call('librarySearch', {'query':query,'limit':limit})


@server.tool()
@checked
def native_place_component(name: str, x: int, y: int, reference: str | None = None, family: str = '', group: str = '', manufacturer: str = '') -> dict:
    """Place a real library component, including its native symbol, named pins, simulation model and parameters. Use an exact search result name."""
    args={'name':name,'x':x,'y':y,'family':family,'group':group,'manufacturer':manufacturer}
    if reference is not None: args['ref']=reference
    return host.edit('place',args)


@server.tool()
@checked
def native_copy_component(component_ref: str, new_ref: str, x: int, y: int) -> dict:
    """Copy a library-backed component into a new independent native instance with copied numeric parameters and unique reference."""
    return host.edit('copy',{'ref':component_ref,'new_ref':new_ref,'x':x,'y':y})


@server.tool()
@checked
def native_delete_object(object_id: str | None = None, component_ref: str | None = None) -> dict:
    """Delete a native component, wire, text or junction by current object ID, or a component by its reference. Attached wires are removed by Multisim."""
    if (object_id is None)==(component_ref is None): raise ValueError('Provide exactly one object_id or component_ref')
    return host.edit('remove',{'id':object_id} if object_id else {'ref':component_ref})


@server.tool()
@checked
def native_get_parameters(component_ref: str) -> dict:
    """Read native indexed numeric and expression parameters plus library metadata. Read these before choosing a parameter index."""
    return host.call('parameters',{'ref':component_ref})


@server.tool()
@checked
def native_set_parameter(component_ref: str, index: int, value: float | None = None, expression: str | None = None) -> dict:
    """Set one existing native parameter by index, using either a finite numeric value or a SPICE expression."""
    if (value is None)==(expression is None): raise ValueError('Provide exactly one value or expression')
    return host.edit('setParameter',{'ref':component_ref,'index':index,**({'value':value} if value is not None else {'expression':expression})})


@server.tool()
@checked
def native_replace_component(component_ref: str, name: str, pin_map: dict[str,str] | None = None, family: str = '', group: str = '') -> dict:
    """Replace a component using another real library model; preserve its reference and reconnect matching named pins. Map old pin names to new names when needed."""
    return host.edit('replace',{'ref':component_ref,'name':name,'family':family,'group':group,'pin_map':pin_map or {}})


@server.tool()
@checked
def native_get_model(component_ref: str) -> dict:
    """Read the component's actual embedded native SPICE model and model attribute IDs."""
    return host.call('modelInfo',{'ref':component_ref})


@server.tool()
@checked
def native_set_model_text(component_ref: str, text: str) -> dict:
    """Edit the native embedded SPICE text model. This edits a shared model definition and returns affected component references across all project sheets."""
    if not re.search(r'(?im)^\s*\.(model|subckt)\b',text): raise ValueError('Provide a SPICE .model or .subckt definition')
    return host.edit('setModelText',{'ref':component_ref,'text':text})


@server.tool()
@checked
def native_transform_component(component_ref: str, angle: int | None = None, mirror_axis: str | None = None) -> dict:
    """Rotate a component by multiples of 90 degrees or mirror horizontally/vertically; keep wires attached to the same native pins."""
    if (angle is None)==(mirror_axis is None): raise ValueError('Provide angle or mirror_axis')
    return host.edit('transform',{'ref':component_ref,**({'angle':angle} if angle is not None else {'axis':mirror_axis})})


@server.tool()
@checked
def native_rename_component(component_ref: str, new_ref: str) -> dict:
    """Rename the native instance reference through Multisim's hierarchical reference manager."""
    return host.edit('rename',{'ref':component_ref,'new_ref':new_ref})


@server.tool()
@checked
def native_route_wire(wire_id: str, points: list[dict[str,int]]) -> dict:
    """Replace the vertices of a real electrical wire. First and last points must equal its actual connector coordinates."""
    return host.edit('route',{'id':wire_id,'points':points})


@server.tool()
@checked
def native_split_wire(wire_id: str, x: int, y: int) -> dict:
    """Split a wire at a point on its existing route and create a real electrical junction for a branch."""
    return host.edit('splitWire',{'id':wire_id,'x':x,'y':y})


@server.tool()
@checked
def native_connect_endpoints(source: dict, target: dict, points: list[dict[str,int]] | None = None) -> dict:
    """Connect {ref,pin} or {junction_id} endpoints. Optional route must end at actual connector coordinates."""
    return host.edit('connectEndpoint',{'source':source,'target':target,**({'points':points} if points else {})})


@server.tool()
@checked
def native_reconnect_wire(wire_id: str, source: dict | None = None, target: dict | None = None) -> dict:
    """Replace one or both wire endpoints with {ref,pin} or {junction_id}; validate and reconnect through the electrical wire factory."""
    return host.edit('reconnect',{'id':wire_id,**({'source':source} if source else {}),**({'target':target} if target else {})})


@server.tool()
@checked
def native_add_text(text: str, x: int, y: int) -> dict:
    """Insert editable native schematic text at sheet coordinates."""
    return host.edit('addText',{'text':text,'x':x,'y':y})


@server.tool()
@checked
def native_label_wire(wire_id: str, name: str) -> dict:
    """Set the actual electrical net name and native wire label."""
    return host.edit('labelWire',{'id':wire_id,'name':name})


@server.tool()
@checked
def native_list_sheets() -> dict:
    """List native schematic sheets and current selection."""
    return {'sheets':host.call('sheets')}


@server.tool()
@checked
def native_select_sheet(index: int) -> dict:
    """Select an existing native schematic sheet by its list index."""
    return host.call('selectSheet',{'index':index})


@server.tool()
@checked
def native_create_sheet(title: str, page: str = '') -> dict:
    """Create and initialize an independent native schematic sheet in the current project."""
    return {'sheets':host.edit('createSheet',{'title':title,'page':page})}


@server.tool()
@checked
def native_create_subcircuit(title: str, reference: str, x: int, y: int) -> dict:
    """Create a native embedded child schematic and its editable parent macro symbol. Add ports on the child sheet before connecting the parent pins."""
    return host.edit('createSubcircuit',{'title':title,'ref':reference,'x':x,'y':y})


@server.tool()
@checked
def native_create_hierarchical_port(name: str, x: int, y: int) -> dict:
    """Add a real hierarchical electrical connector on the selected child sheet; update its parent subcircuit symbol pins. Read the exact returned connector pin name before wiring."""
    return host.edit('createPort',{'name':name,'x':x,'y':y})


@server.tool()
@checked
def native_list_projects() -> dict:
    """List open native projects, including their indexes for native_attach."""
    return host.call('projects')


@server.tool()
@checked
def native_edit_batch(operations: list[dict]) -> dict:
    """Apply 1-100 edits as one undo unit. Each item has operation and arguments. Allowlist: wire, move, place, copy, remove, transform, route, setParameter, rename, addText, labelWire, splitWire, connectEndpoint, reconnect, replace, createSheet, sheetSize. sheetSize takes width and height in native pixels, 96-8192. Any failure restores a native checkpoint; reread volatile IDs afterward."""
    return host.batch(operations)


@server.tool()
@checked
def native_undo() -> dict:
    """Restore the previous native checkpoint. Object IDs change; reread components and wires."""
    return host.history('undo')


@server.tool()
@checked
def native_redo() -> dict:
    """Reapply an undone checkpoint using native save/reopen; reread object IDs afterward."""
    return host.history('redo')


@server.tool()
@checked
def native_check_netlist() -> dict:
    """Generate and check the real native SPICE netlist. Refresh edited connectivity through native save/reopen; object IDs may change."""
    return host.netlist()


@server.tool()
@checked
def native_run_analysis(analysis: str = 'op', step: float = 0.00001, stop: float = 0.01) -> dict:
    """Run real Multisim DC operating-point (op) or transient (tran) analysis. Return verified numeric waveforms plus ASCII RAW, CSV and native SPICE source paths. At most 100000 requested transient steps."""
    return host.run_analysis(analysis,step,stop)


@server.tool()
@checked
def native_start_analysis(analysis: str = 'tran', step: float = 0.00001, stop: float = 0.01) -> dict:
    """Start a native analysis in the background so pause/resume/stop and status tools remain available."""
    return host.start_analysis(analysis,step,stop)


@server.tool()
@checked
def native_analysis_status() -> dict:
    """Read the current analysis job state, completed numeric results or native failure, without waiting for the UI thread."""
    return host.analysis_status()


@server.tool()
@checked
def native_control_analysis(action: str) -> dict:
    """Request pause, resume or stop through the native simulator transport. A request acknowledgment is not a confirmed paused state; inspect job status and result artifacts."""
    return host.control_analysis(action)


@server.tool()
@checked
def native_read_waveform(raw_path: str, offset: int = 0, limit: int = 1000) -> dict:
    """Read a page of actual numeric samples and native vector names from an exported ASCII SPICE RAW result."""
    return host.read_waveform(raw_path,offset,limit)


@server.tool()
@checked
def native_export_image(output_path: str, overwrite: bool = False) -> dict:
    """Export the selected schematic through Multisim's native image exporter to PNG or BMP, as a PNG or BMP file."""
    return host.export_image(output_path,overwrite)


def main():
    try:
        server.run(transport='stdio')
    finally:
        host.close()
