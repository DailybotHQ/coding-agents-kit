"""Validate a JSON document against the subset of JSON Schema the kit's
schemas use (type, const, enum, pattern, required, properties,
additionalProperties, items). Stdlib only.

usage: python3 schema_check.py <schema.json> <document.json|->
Exit 0 and prints "valid", or exit 1 with one line per violation.
"""

import json
import re
import sys

TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def type_ok(value, wanted):
    for t in wanted if isinstance(wanted, list) else [wanted]:
        if t == "integer" and isinstance(value, int) and not isinstance(value, bool):
            return True
        if t == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
            return True
        if t in TYPES and isinstance(value, TYPES[t]):
            return True
    return False


def validate(value, schema, path, errors):
    if "const" in schema and value != schema["const"]:
        errors.append("%s: expected %r, got %r" % (path, schema["const"], value))
    if "enum" in schema and value not in schema["enum"]:
        errors.append("%s: %r not in %r" % (path, value, schema["enum"]))
    if "type" in schema and not type_ok(value, schema["type"]):
        errors.append("%s: expected type %s, got %s" % (path, schema["type"], type(value).__name__))
        return
    if isinstance(value, str) and "pattern" in schema and not re.search(schema["pattern"], value):
        errors.append("%s: %r does not match %s" % (path, value, schema["pattern"]))
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append("%s: missing required key %r" % (path, key))
        props = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for key, sub in value.items():
            if key in props:
                validate(sub, props[key], "%s.%s" % (path, key), errors)
            elif extra is False:
                errors.append("%s: unexpected key %r" % (path, key))
            elif isinstance(extra, dict):
                validate(sub, extra, "%s.%s" % (path, key), errors)
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            validate(item, schema["items"], "%s[%d]" % (path, i), errors)


def main():
    with open(sys.argv[1]) as h:
        schema = json.load(h)
    src = sys.argv[2]
    doc = json.load(sys.stdin if src == "-" else open(src))
    errors = []
    validate(doc, schema, "$", errors)
    if errors:
        print("\n".join(errors))
        return 1
    print("valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
