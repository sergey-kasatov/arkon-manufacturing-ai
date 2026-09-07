"""Minimal Langflow flow-construction helpers.

Langflow stores a flow as a ReactFlow graph whose edge handles are JSON strings
with every double quote replaced by U+0153 (the frontend's scapedJSONStringfy).
Getting that wrong makes an edge that looks present in the file but does not
render or execute, so the encoding lives in one place here.

Component templates come from the running instance (/api/v1/all), which is the
same source the frontend instantiates nodes from.
"""

import copy
import json

QUOTE = "œ"  # the character Langflow substitutes for " inside handle ids


def escaped(obj):
    """Serialise a handle object the way the Langflow frontend does."""
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).replace('"', QUOTE)


def node_from_spec(spec, node_id, position, values=None, outputs=None,
                   selected_output=None, tool_mode=False, display_name=None,
                   type_name=None):
    """Build a node envelope from a component spec fetched from the catalog.

    ``type_name`` overrides the type derived from the node id. Bundle components
    need it: Langflow's own export gives the Qdrant node the id prefix
    ``ext:qdrant:QdrantVectorStoreComponent@official`` but the plain class name as
    its type, and the two are not interchangeable.
    """
    node = copy.deepcopy(spec)
    for field, value in (values or {}).items():
        if field not in node["template"]:
            raise KeyError("%s has no template field %r" % (node_id, field))
        node["template"][field]["value"] = value
    if display_name:
        node["display_name"] = display_name
    if outputs is not None:
        node["outputs"] = outputs
    if tool_mode:
        node["tool_mode"] = True
    data = {
        "id": node_id,
        "node": node,
        "showNode": True,
        "type": type_name or node_id.rsplit("-", 1)[0],
    }
    if selected_output:
        data["selected_output"] = selected_output
    return {
        "data": data,
        "dragging": False,
        "id": node_id,
        "measured": {"width": 320, "height": 300},
        "position": {"x": position[0], "y": position[1]},
        "selected": False,
        "type": "genericNode",
    }


def clone_node(source_node, node_id, position, values=None, display_name=None):
    """Copy an existing node, give it a new id, and override field values."""
    node = copy.deepcopy(source_node)
    node["id"] = node_id
    node["data"]["id"] = node_id
    node["position"] = {"x": position[0], "y": position[1]}
    for field, value in (values or {}).items():
        if field not in node["data"]["node"]["template"]:
            raise KeyError("%s has no template field %r" % (node_id, field))
        node["data"]["node"]["template"][field]["value"] = value
    if display_name:
        node["data"]["node"]["display_name"] = display_name
    return node


def output_spec(node, name):
    """Find an output definition on a node envelope."""
    for output in node["data"]["node"].get("outputs", []):
        if output["name"] == name:
            return output
    raise KeyError("%s has no output %r" % (node["id"], name))


def edge(source, source_output, target, target_field):
    """Wire one output to one input, computing both handles from the nodes."""
    out = output_spec(source, source_output)
    field = target["data"]["node"]["template"][target_field]
    source_handle = {
        "dataType": source["data"]["type"],
        "id": source["id"],
        "name": source_output,
        "output_types": out["types"],
    }
    target_handle = {
        "fieldName": target_field,
        "id": target["id"],
        "inputTypes": field.get("input_types") or [],
        "type": field["type"],
    }
    source_text = escaped(source_handle)
    target_text = escaped(target_handle)
    return {
        "animated": False,
        "className": "",
        "data": {"sourceHandle": source_handle, "targetHandle": target_handle},
        "id": "reactflow__edge-%s%s-%s%s" % (source["id"], source_text, target["id"], target_text),
        "selected": False,
        "source": source["id"],
        "sourceHandle": source_text,
        "target": target["id"],
        "targetHandle": target_text,
    }


def router_outputs(routes, enable_else):
    """Reproduce the dynamic outputs SmartRouter.update_outputs would create."""
    outputs = []
    for index, route in enumerate(routes, start=1):
        outputs.append({
            "allows_loop": False,
            "cache": True,
            "display_name": route["route_category"],
            "group_outputs": True,
            "method": "process_case",
            "name": "category_%d_result" % index,
            "selected": "Message",
            "types": ["Message"],
            "value": "__UNDEFINED__",
        })
    if enable_else:
        outputs.append({
            "allows_loop": False,
            "cache": True,
            "display_name": "Else",
            "group_outputs": True,
            "method": "default_response",
            "name": "default_result",
            "selected": "Message",
            "types": ["Message"],
            "value": "__UNDEFINED__",
        })
    return outputs


def loop_back_edge(source, source_output, loop_node):
    """Wire the last vertex of a loop body back into the Loop node's item input.

    This edge is not shaped like the others and guessing it is how a loop ends up
    drawn on the canvas and never iterating. Its TARGET handle carries the source
    handle's fields (`dataType`, `id`, `name`, `output_types`) rather than
    `fieldName` / `inputTypes` / `type`, because `item` is an output name that the
    Loop component also reads as an incoming parameter
    (`get_incoming_edge_by_target_param("item")`), not a template field. The shape
    is copied from Langflow's own "Research Translation Loop" starter project,
    read out of the running image on 2026-09-07.

    `output_types` is the item output's `types` plus its `loop_types`, which is
    what the frontend writes when it draws the feedback connection.
    """
    out = output_spec(source, source_output)
    item = output_spec(loop_node, "item")
    source_handle = {
        "dataType": source["data"]["type"],
        "id": source["id"],
        "name": source_output,
        "output_types": out["types"],
    }
    target_handle = {
        "dataType": loop_node["data"]["type"],
        "id": loop_node["id"],
        "name": "item",
        "output_types": list(item["types"][:1]) + list(item.get("loop_types") or []),
    }
    source_text = escaped(source_handle)
    target_text = escaped(target_handle)
    return {
        "animated": False,
        "className": "",
        "data": {"sourceHandle": source_handle, "targetHandle": target_handle},
        "id": "reactflow__edge-%s%s-%s%s" % (source["id"], source_text, loop_node["id"], target_text),
        "selected": False,
        "source": source["id"],
        "sourceHandle": source_text,
        "target": loop_node["id"],
        "targetHandle": target_text,
    }
