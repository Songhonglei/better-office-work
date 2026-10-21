"""MCP 2026-07-28 request metadata and validated schema header projection.

Only called by the fixed QQ transport; no network, credentials or log output.
"""
import base64
import re

MODERN = "2026-07-28"
CLIENT_INFO = {"name": "qq_mail_manage_direct", "version": "1.4.1"}
TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")


def metadata():
    return {"io.modelcontextprotocol/protocolVersion": MODERN,
            "io.modelcontextprotocol/clientInfo": dict(CLIENT_INFO),
            "io.modelcontextprotocol/clientCapabilities": {}}


def bounded_schema(schema):
    nodes = 0
    def visit(node, depth=0):
        nonlocal nodes
        nodes += 1
        if nodes > 10000 or depth > 32:
            raise ValueError("schema limit")
        if isinstance(node, dict):
            for reference in ("$ref", "$dynamicRef"):
                if reference in node and (not isinstance(node[reference], str) or not node[reference].startswith("#")):
                    raise ValueError("external schema reference")
            for value in node.values(): visit(value, depth+1)
        elif isinstance(node, list):
            for value in node: visit(value, depth+1)
    visit(schema)


def header_value(value):
    if not isinstance(value, str):
        raise ValueError("invalid header value")
    if value.strip() != value or any(not (32 <= ord(c) <= 126 or c == "\t") for c in value) or (value.startswith("=?base64?") and value.endswith("?=")):
        return "=?base64?" + base64.b64encode(value.encode("utf-8")).decode("ascii") + "?="
    return value


def header_specs(schema):
    """Validate every annotation; only properties-only paths may project headers."""
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise ValueError("invalid tool schema")
    specs, used, nodes = [], set(), 0

    def visit(node, path=(), reachable=True, depth=0):
        nonlocal nodes
        nodes += 1
        if nodes > 10000 or depth > 32:
            raise ValueError("schema limit")
        if isinstance(node, list):
            for item in node: visit(item, path, False, depth+1)
        elif isinstance(node, dict):
            for reference in ("$ref", "$dynamicRef"):
                if reference in node and (not isinstance(node[reference], str) or not node[reference].startswith("#")):
                    raise ValueError("external schema reference")
            if "x-mcp-header" in node:
                name, kind = node["x-mcp-header"], node.get("type")
                if not reachable or not path or "$ref" in node or not isinstance(name, str) or len(name) > 128 or not TOKEN.fullmatch(name) or name.lower() in used or kind not in ("string", "integer", "boolean"):
                    raise ValueError("invalid header annotation")
                used.add(name.lower()); specs.append((path, name, kind))
                if len(specs) > 64: raise ValueError("header count")
            for key, child in node.items():
                if key == "properties" and isinstance(child, dict):
                    for prop, sub in child.items():
                        if not isinstance(prop, str): raise ValueError("invalid schema property")
                        visit(sub, path+(prop,), reachable and "$ref" not in node, depth+1)
                elif isinstance(child, (dict, list)):
                    visit(child, path, False, depth+1)
    visit(schema)
    return specs


def schema_validator(schema):
    # All validation runs in the bounded HTTP worker. Never let a remote schema
    # trigger arbitrary URL fetching (including from $ref/$dynamicRef).
    from jsonschema.validators import validator_for, Draft202012Validator
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012
    def deny(_uri): raise ValueError("external schema retrieval forbidden")
    if not isinstance(schema, dict): raise ValueError("invalid schema")
    bounded_schema(schema)
    validator = validator_for(schema, default=None) if "$schema" in schema else Draft202012Validator
    if validator is None: raise ValueError("unsupported schema dialect")
    validator.check_schema(schema)
    resource = Resource.from_contents(schema, default_specification=DRAFT202012)
    registry = Registry(retrieve=deny).with_resource(resource.id() or "", resource)
    # Resolve every local reference now, even under an optional property. A
    # dangling output reference is knowably unusable before any mail is sent.
    def references(current, resolver):
        if isinstance(current.contents, dict):
            for key in ("$ref", "$dynamicRef"):
                if key in current.contents:
                    target = resolver.lookup(current.contents[key]).contents
                    if not isinstance(target, (dict, bool)): raise ValueError("invalid schema target")
        for child in current.subresources(): references(child, resolver.in_subresource(child))
    references(resource, registry.resolver_with_root(resource))
    return validator(schema, registry=registry)


def validated_catalog(tools):
    if not isinstance(tools, list) or len(tools) > 1000:
        raise ValueError("invalid catalog")
    names, valid = set(), []
    for tool in tools:
        if not isinstance(tool, dict) or not isinstance(tool.get("name"), str) or not 1 <= len(tool["name"]) <= 128 or tool["name"] in names:
            raise ValueError("invalid catalog")
        names.add(tool["name"])
        try:
            header_specs(tool.get("inputSchema"))
            schema_validator(tool["inputSchema"])
            if "outputSchema" in tool: schema_validator(tool["outputSchema"])
        except Exception:
            continue  # Exclude invalid definitions, never broaden their schema.
        valid.append(tool)
    return valid, [tool["name"] for tool in tools]


def parameter_headers(specs, arguments):
    headers = {}
    for path, name, kind in specs:
        value = arguments
        for key in path:
            if not isinstance(value, dict) or key not in value:
                value = None; break
            value = value[key]
        if value is None: continue
        expected = {"string": str, "integer": int, "boolean": bool}[kind]
        if type(value) is not expected or (kind == "integer" and abs(value) > 2**53-1):
            raise ValueError("invalid projected parameter")
        text = str(value).lower() if kind == "boolean" else str(value)
        headers["Mcp-Param-"+name] = header_value(text)
    return headers


def request_headers(message, protocol, extra):
    params = message.get("params", {})
    meta = params.get("_meta") if isinstance(params, dict) else None
    if protocol != MODERN or meta != metadata() or "id" not in message or message.get("method") not in ("server/discover", "tools/list", "tools/call"):
        raise ValueError("invalid modern request")
    headers = {"Mcp-Method": message["method"]}
    if message["method"] == "tools/call":
        if not isinstance(params.get("name"), str) or not params["name"]:
            raise ValueError("invalid tool name")
        headers["Mcp-Name"] = header_value(params["name"])
    elif extra:
        raise ValueError("unexpected parameter headers")
    if not isinstance(extra, dict) or len(extra) > 64:
        raise ValueError("invalid parameter headers")
    for key, value in extra.items():
        if not isinstance(key, str) or not key.startswith("Mcp-Param-") or not TOKEN.fullmatch(key) or not isinstance(value, str) or any(not (32 <= ord(c) <= 126 or c == "\t") for c in value):
            raise ValueError("invalid parameter header")
        headers[key] = value
    if sum(len(k)+len(v)+4 for k,v in headers.items()) > 65536:
        raise ValueError("header size")
    return headers
