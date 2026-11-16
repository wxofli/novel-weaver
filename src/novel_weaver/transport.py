"""Lossless schema annotation trimming and opt-in MCP text summaries."""
import json

SCHEMA_MAPS = {"properties", "$defs", "definitions", "patternProperties", "dependentSchemas"}
SCHEMA_LISTS = {"allOf", "anyOf", "oneOf", "prefixItems"}
SCHEMA_CHILDREN = {"items", "additionalProperties", "unevaluatedProperties", "contains", "not", "if", "then", "else", "propertyNames"}


def compact_schema(schema):
    """Remove schema titles, never property names or literal default/enum data."""
    if not isinstance(schema, dict):
        return schema
    result = {}
    for key, value in schema.items():
        if key == "title":
            continue
        if key in SCHEMA_MAPS:
            result[key] = {name: compact_schema(child) for name, child in value.items()}
        elif key in SCHEMA_LISTS:
            result[key] = [compact_schema(child) for child in value]
        elif key in SCHEMA_CHILDREN:
            result[key] = compact_schema(value)
        else:
            result[key] = value
    return result


def tool_result(result, text_mode="full"):
    from mcp.types import CallToolResult, TextContent

    if text_mode not in {"full", "summary"}:
        raise ValueError("MCP text mode must be full or summary")
    text_result = result
    if text_mode == "summary":
        text_result = {key: value for key, value in result.items() if key != "data"}
        text_result["result_location"] = "structuredContent"
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(text_result, ensure_ascii=False))],
        structuredContent=result, isError=result.get("status") == "error")
