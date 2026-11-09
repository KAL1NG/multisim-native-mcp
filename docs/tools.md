# Tool reference / 工具参考

| Tool | Parameters |
| --- | --- |
| `native_runtime_status` | — |
| `native_diagnostics` | — |
| `native_open_copy` | source_path |
| `native_list_components` | — |
| `native_list_wires` | component_ref |
| `native_connect_pins` | source_ref, source_pin, target_ref, target_pin |
| `native_move_component` | component_ref, dx, dy |
| `native_save_copy` | output_path, overwrite |
| `native_close_copy` | — |
| `native_attach` | pid, project_index |
| `native_create_circuit` | title |
| `native_search_library` | query, limit |
| `native_place_component` | name, x, y, reference, family, group, manufacturer |
| `native_copy_component` | component_ref, new_ref, x, y |
| `native_delete_object` | object_id, component_ref |
| `native_get_parameters` | component_ref |
| `native_set_parameter` | component_ref, index, value, expression |
| `native_replace_component` | component_ref, name, pin_map, family, group |
| `native_get_model` | component_ref |
| `native_set_model_text` | component_ref, text |
| `native_transform_component` | component_ref, angle, mirror_axis |
| `native_rename_component` | component_ref, new_ref |
| `native_route_wire` | wire_id, points |
| `native_split_wire` | wire_id, x, y |
| `native_connect_endpoints` | source, target, points |
| `native_reconnect_wire` | wire_id, source, target |
| `native_add_text` | text, x, y |
| `native_label_wire` | wire_id, name |
| `native_list_sheets` | — |
| `native_select_sheet` | index |
| `native_create_sheet` | title, page |
| `native_create_subcircuit` | title, reference, x, y |
| `native_create_hierarchical_port` | name, x, y |
| `native_list_projects` | — |
| `native_edit_batch` | operations |
| `native_undo` | — |
| `native_redo` | — |
| `native_check_netlist` | — |
| `native_run_analysis` | analysis, step, stop |
| `native_start_analysis` | analysis, step, stop |
| `native_analysis_status` | — |
| `native_control_analysis` | action |
| `native_read_waveform` | raw_path, offset, limit |
| `native_export_image` | output_path, overwrite |

Use the schemas returned by MCP `tools/list` for parameter types and defaults.
参数类型和默认值以 MCP `tools/list` 返回的 schema 为准。
