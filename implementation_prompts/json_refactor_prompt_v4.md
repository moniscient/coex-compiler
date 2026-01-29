# JSON Type Refactoring: Wrapper with Value Semantics

## Overview

Refactor the Coex JSON type from its current implementation (which stores flattened/serialized values) to a new implementation where JSON is composed of Coex `List` and `Map` types, following Coex's pure value semantics.

This design:
- Eliminates bugs where handle references appear in JSON output
- Preserves Coex's pure value semantics and concurrency safety
- Handles non-JSON-compatible types gracefully via annotations at serialization time
- Leverages immutable operations for efficient structural sharing

## Critical Invariant: Pure Value Semantics via Immutability

**This invariant must be respected throughout the entire implementation and is non-negotiable.**

Coex uses pure value semantics. This is achieved through **immutable operations**: all mutation operations (`.set()`, `.append()`, `.remove()`) return NEW structures rather than modifying in place. This means:

1. **Structural sharing is safe.** Two variables may initially share the same underlying struct, but any "mutation" through one variable creates a new struct, leaving the other unchanged.

2. **No eager deep copying required.** When `b = a`, both may point to the same struct. This is safe because neither can mutate it in place - operations return new structures.

3. **Independence emerges on mutation.** When you modify `b`, it gets a new struct. The shared struct that `a` still references is unchanged.

4. **This prevents concurrency errors.** Even if tasks share references to the same struct, no task can modify it - they can only create new structs. Each task's "view" is always consistent.

### How Value Semantics Works

```coex
inner = [1, 2, 3]
a = [inner, inner]  # a[0] and a[1] may share the same struct (OK!)

# Modify through one path
a = a.set(0, a[0].set(0, 100))

# What happens:
# 1. a[0].set(0, 100) creates NEW list [100, 2, 3]
# 2. a.set(0, new_list) creates NEW outer list
# 3. The original inner [1, 2, 3] is unchanged

# Result:
assert a[0][0] == 100  # new list
assert a[1][0] == 1    # original inner, unchanged
```

After mutation, `a[0]` and `a[1]` are independent - not because they were copied eagerly, but because mutation creates new structures.

### What Gets Shared vs Created

```coex
a = [[1, 2], {"key": "value"}]
b = a  # b shares the same structs as a (efficient!)

b = b.set(0, b[0].set(0, 999))  # Mutation on b

# After mutation:
# - b has NEW outer List struct
# - b[0] has NEW inner List struct [999, 2]
# - b[1] still shares original Map struct with a[1] (unchanged)
# - a is completely unchanged (still references all original structs)
```

## Critical Constraints

1. **Do NOT use Coex's `array` type.** Arrays are fixed-size, stack-allocated structures unrelated to this task. JSON arrays must be implemented using `List`.

2. **All mutation operations must return new structures.** This is the foundation of value semantics. Never modify a struct in place.

3. **No pointers or handles in serialized output.** When JSON is serialized to text, the output contains only valid JSON syntax. Internal handle addresses must never appear.

4. **Structural sharing is permitted and encouraged.** It provides efficiency without sacrificing correctness.

## Phase 1: Value Semantics Tests for List

These tests verify that List operations maintain value semantics through immutability.

### Basic Independence Tests

```coex
test "list_assignment_creates_independent_copy" {
    a = [1, 2, 3]
    b = a

    # Modify b (creates new list)
    b = b.set(0, 100)

    # a is completely unaffected
    assert a[0] == 1
    assert b[0] == 100
}

test "list_nested_assignment_deep_independence" {
    inner = [1, 2, 3]
    a = [inner, inner]  # Same inner assigned twice

    # Modify through one path
    a = a.set(0, a[0].set(0, 100))

    # The other path is unaffected (mutation creates new struct)
    assert a[0][0] == 100
    assert a[1][0] == 1  # NOT 100 - proves independence via immutability
}

test "list_three_level_nesting_independence" {
    level3 = [1, 2]
    level2 = [level3, level3]
    level1 = [level2, level2]

    # Modify deeply nested value through one path
    level1 = level1.set(0, level1[0].set(0, level1[0][0].set(0, 999)))

    # All other paths remain unchanged
    assert level1[0][0][0] == 999  # modified path
    assert level1[0][0][1] == 2    # sibling in same innermost list
    assert level1[0][1][0] == 1    # sibling inner list - independent
    assert level1[1][0][0] == 1    # sibling outer list - independent
    assert level1[1][1][0] == 1    # completely separate path - independent
}

test "list_containing_map_independence" {
    m = {"x": 1, "y": 2}
    a = [m, m]

    # Modify map through one path
    a = a.set(0, a[0].set("x", 100))

    # Other path unaffected
    assert a[0]["x"] == 100
    assert a[1]["x"] == 1  # independent via immutability
}

test "list_assigned_to_multiple_variables" {
    original = [1, [2, 3], {"a": 4}]
    copy1 = original
    copy2 = original
    copy3 = copy1

    # Modify copy1's nested list
    copy1 = copy1.set(1, copy1[1].set(0, 999))

    # All others unaffected
    assert copy1[1][0] == 999
    assert copy2[1][0] == 2
    assert copy3[1][0] == 2
    assert original[1][0] == 2
}
```

### Concurrency Safety Tests

```coex
test "list_no_shared_mutation_between_tasks" {
    shared_data = [[1, 2, 3], [4, 5, 6]]

    # Simulate two tasks receiving the same data
    task1_data = shared_data
    task2_data = shared_data

    # Task 1 modifies its copy
    task1_data = task1_data.set(0, task1_data[0].set(0, 100))

    # Task 2 modifies its copy differently
    task2_data = task2_data.set(0, task2_data[0].set(0, 200))

    # Original and both tasks have independent state
    assert shared_data[0][0] == 1
    assert task1_data[0][0] == 100
    assert task2_data[0][0] == 200
}

test "list_passed_to_function_is_independent" {
    func modify_list(lst) -> [int]
        return lst.set(0, 999)
    ~

    original = [1, 2, 3]
    modified = modify_list(original)

    assert original[0] == 1  # unchanged
    assert modified[0] == 999
}

test "list_returned_from_function_is_independent" {
    func create_list() -> [[int]]
        inner = [1, 2, 3]
        return [inner, inner]
    ~

    a = create_list()
    b = create_list()

    # Each call returns structures; modifications are independent
    a = a.set(0, a[0].set(0, 100))

    assert a[0][0] == 100
    assert a[1][0] == 1   # independent within a
    assert b[0][0] == 1   # b completely independent
}
```

## Phase 2: Value Semantics Tests for Map

These tests verify that Map operations maintain value semantics through immutability.

### Basic Independence Tests

```coex
test "map_assignment_creates_independent_copy" {
    a = {"x": 1, "y": 2}
    b = a

    b = b.set("x", 100)

    assert a["x"] == 1
    assert b["x"] == 100
}

test "map_nested_assignment_deep_independence" {
    inner = {"value": 42}
    a = {"first": inner, "second": inner}

    # Modify through one path
    a = a.set("first", a["first"].set("value", 999))

    # Other path unaffected
    assert a["first"]["value"] == 999
    assert a["second"]["value"] == 42  # independent via immutability
}

test "map_three_level_nesting_independence" {
    level3 = {"deep": 1}
    level2 = {"a": level3, "b": level3}
    level1 = {"x": level2, "y": level2}

    # Modify through one path
    level1 = level1.set("x", level1["x"].set("a", level1["x"]["a"].set("deep", 999)))

    # All other paths unchanged
    assert level1["x"]["a"]["deep"] == 999
    assert level1["x"]["b"]["deep"] == 1
    assert level1["y"]["a"]["deep"] == 1
    assert level1["y"]["b"]["deep"] == 1
}

test "map_containing_list_independence" {
    lst = [1, 2, 3]
    a = {"items": lst, "backup": lst}

    # Modify list through one path
    a = a.set("items", a["items"].set(0, 999))

    # Other path unaffected
    assert a["items"][0] == 999
    assert a["backup"][0] == 1  # independent via immutability
}

test "map_assigned_to_multiple_variables" {
    original = {"data": {"nested": [1, 2, 3]}}
    copy1 = original
    copy2 = original

    # Modify copy1
    copy1 = copy1.set("data", copy1["data"].set("nested", copy1["data"]["nested"].set(0, 999)))

    # Others unaffected
    assert copy1["data"]["nested"][0] == 999
    assert copy2["data"]["nested"][0] == 1
    assert original["data"]["nested"][0] == 1
}
```

### Mixed List/Map Independence Tests

```coex
test "mixed_list_map_deep_independence" {
    data = {
        "users": [
            {"name": "Alice", "scores": [10, 20]},
            {"name": "Bob", "scores": [30, 40]}
        ],
        "metadata": {"count": 2}
    }

    copy = data

    # Modify deeply nested value in copy
    users = copy["users"]
    user0 = users[0]
    scores = user0["scores"]
    scores = scores.set(0, 999)
    user0 = user0.set("scores", scores)
    users = users.set(0, user0)
    copy = copy.set("users", users)

    # Original completely unaffected at every level
    assert data["users"][0]["scores"][0] == 10
    assert data["users"][0]["scores"][1] == 20
    assert data["users"][0]["name"] == "Alice"
    assert data["users"][1]["scores"][0] == 30
    assert data["metadata"]["count"] == 2

    # Copy has the modification
    assert copy["users"][0]["scores"][0] == 999
}

test "shared_subtree_becomes_independent_on_mutation" {
    shared = {"value": 42, "nested": [1, 2, 3]}

    a = {"left": shared, "right": shared}
    b = {"left": shared, "right": shared}

    # Modify a's left branch
    a = a.set("left", a["left"].set("value", 100))

    # a's right branch independent (still shares original)
    assert a["left"]["value"] == 100
    assert a["right"]["value"] == 42

    # b completely independent
    assert b["left"]["value"] == 42
    assert b["right"]["value"] == 42

    # Original shared unchanged
    assert shared["value"] == 42
}
```

## Phase 3: JSON Assignment with Value Semantics

JSON follows the same value semantics as List and Map.

### JSON Independence Tests

```coex
test "json_assignment_from_list_is_independent" {
    lst = [1, [2, 3], {"a": 4}]
    j: json = lst

    # Modify original list
    lst = lst.set(0, 999)
    lst = lst.set(1, lst[1].set(0, 888))

    # JSON is completely independent
    assert j[0] == 1
    assert j[1][0] == 2
    assert j[2]["a"] == 4
}

test "json_assignment_from_map_is_independent" {
    m = {"x": 1, "nested": {"y": 2}}
    j: json = m

    # Modify original map
    m = m.set("x", 999)
    m = m.set("nested", m["nested"].set("y", 888))

    # JSON is completely independent
    assert j["x"] == 1
    assert j["nested"]["y"] == 2
}

test "json_to_json_assignment_is_independent" {
    j1: json = {"data": [1, 2, 3]}
    j2: json = j1

    # Modify j1
    j1 = j1.set("data", j1["data"].set(0, 999))

    # j2 independent
    assert j1["data"][0] == 999
    assert j2["data"][0] == 1
}

test "json_nested_independence" {
    inner = {"value": 42}
    outer = {"a": inner, "b": inner}
    j: json = outer

    # Within the JSON, a and b become independent on mutation
    j = j.set("a", j["a"].set("value", 999))

    assert j["a"]["value"] == 999
    assert j["b"]["value"] == 42  # independent
}

test "json_multiple_assignments_all_independent" {
    source = [1, [2, [3, [4, 5]]]]

    j1: json = source
    j2: json = source
    j3: json = j1

    # Modify j1 deeply
    j1 = j1.set(1, j1[1].set(1, j1[1][1].set(1, j1[1][1][1].set(0, 999))))

    # All others unaffected
    assert j1[1][1][1][0] == 999
    assert j2[1][1][1][0] == 4
    assert j3[1][1][1][0] == 4
    assert source[1][1][1][0] == 4
}
```

### JSON Concurrency Safety Tests

```coex
test "json_safe_for_concurrent_tasks" {
    config: json = {
        "settings": {"timeout": 30, "retries": 3},
        "data": [1, 2, 3]
    }

    # Simulate passing to multiple tasks
    task1_config = config
    task2_config = config

    # Each task modifies its copy
    task1_config = task1_config.set("settings", task1_config["settings"].set("timeout", 60))
    task2_config = task2_config.set("settings", task2_config["settings"].set("timeout", 90))

    # All three are independent
    assert config["settings"]["timeout"] == 30
    assert task1_config["settings"]["timeout"] == 60
    assert task2_config["settings"]["timeout"] == 90
}

test "json_from_shared_source_is_independent" {
    shared_list = [1, 2, 3]

    j1: json = {"items": shared_list}
    j2: json = {"items": shared_list}

    # Modify j1
    j1 = j1.set("items", j1["items"].set(0, 999))

    # j2 and original unaffected
    assert j1["items"][0] == 999
    assert j2["items"][0] == 1
    assert shared_list[0] == 1
}
```

## Phase 4: JSON Serialization Tests

### Primitive Serialization

```coex
test "json_serialize_null" {
    j: json = none
    text = j.stringify()
    assert text == "null"
}

test "json_serialize_bool_true" {
    j: json = true
    text = j.stringify()
    assert text == "true"
}

test "json_serialize_bool_false" {
    j: json = false
    text = j.stringify()
    assert text == "false"
}

test "json_serialize_int" {
    j: json = 42
    text = j.stringify()
    assert text == "42"
}

test "json_serialize_negative_int" {
    j: json = -17
    text = j.stringify()
    assert text == "-17"
}

test "json_serialize_float" {
    j: json = 3.14
    text = j.stringify()
    parsed = json.parse(text)
    assert parsed == 3.14
}

test "json_serialize_string_simple" {
    j: json = "hello"
    text = j.stringify()
    assert text == "\"hello\""
}

test "json_serialize_string_escapes" {
    j: json = "line1\nline2\ttab\"quote"
    text = j.stringify()
    assert text == "\"line1\\nline2\\ttab\\\"quote\""
}

test "json_serialize_string_unicode" {
    j: json = "cafe n 日本語"
    text = j.stringify()
    parsed = json.parse(text)
    assert parsed == "cafe n 日本語"
}
```

### Array Serialization

```coex
test "json_serialize_empty_array" {
    j: json = []
    text = j.stringify()
    assert text == "[]"
}

test "json_serialize_int_array" {
    j: json = [1, 2, 3]
    text = j.stringify()
    parsed = json.parse(text)
    assert parsed[0] == 1
    assert parsed[1] == 2
    assert parsed[2] == 3
}

test "json_serialize_nested_array" {
    j: json = [[1, 2], [3, [4, 5]]]
    text = j.stringify()
    parsed = json.parse(text)
    assert parsed[0][0] == 1
    assert parsed[1][1][0] == 4
}
```

### Object Serialization

```coex
test "json_serialize_empty_object" {
    j: json = {}
    text = j.stringify()
    assert text == "{}"
}

test "json_serialize_simple_object" {
    j: json = {"a": 1, "b": 2}
    text = j.stringify()
    parsed = json.parse(text)
    assert parsed["a"] == 1
    assert parsed["b"] == 2
}

test "json_serialize_nested_object" {
    j: json = {
        "outer": {
            "inner": {
                "value": 42
            }
        }
    }
    text = j.stringify()
    parsed = json.parse(text)
    assert parsed["outer"]["inner"]["value"] == 42
}

test "json_serialize_complex_structure" {
    j: json = {
        "name": "test",
        "count": 42,
        "enabled": true,
        "data": none,
        "tags": ["a", "b", "c"],
        "metadata": {
            "created": "2025-01-29",
            "values": [1.1, 2.2, 3.3]
        }
    }
    text = j.stringify()
    parsed = json.parse(text)

    assert parsed["name"] == "test"
    assert parsed["count"] == 42
    assert parsed["enabled"] == true
    assert parsed["data"] == none
    assert parsed["tags"][1] == "b"
    assert parsed["metadata"]["created"] == "2025-01-29"
    assert parsed["metadata"]["values"][2] == 3.3
}
```

### Deserialization

```coex
test "json_parse_primitives" {
    assert json.parse("null") == none
    assert json.parse("true") == true
    assert json.parse("false") == false
    assert json.parse("42") == 42
    assert json.parse("-17") == -17
    assert json.parse("3.14") == 3.14
    assert json.parse("\"hello\"") == "hello"
}

test "json_parse_array" {
    parsed = json.parse("[1, 2, 3]")
    assert parsed[0] == 1
    assert parsed[1] == 2
    assert parsed[2] == 3
}

test "json_parse_object" {
    parsed = json.parse("{\"a\": 1, \"b\": \"two\"}")
    assert parsed["a"] == 1
    assert parsed["b"] == "two"
}

test "json_roundtrip_preserves_structure" {
    original: json = {
        "array": [1, [2, 3], {"nested": true}],
        "object": {"a": {"b": {"c": "deep"}}}
    }
    text = original.stringify()
    restored = json.parse(text)

    assert restored["array"][1][0] == 2
    assert restored["array"][2]["nested"] == true
    assert restored["object"]["a"]["b"]["c"] == "deep"
}

test "json_parsed_values_are_independent" {
    text = "{\"data\": [1, 2, 3]}"

    a = json.parse(text)
    b = json.parse(text)

    # Each parse returns independent structure
    a = a.set("data", a["data"].set(0, 999))

    assert a["data"][0] == 999
    assert b["data"][0] == 1
}
```

## Phase 5: Non-JSON-Compatible Type Annotation Tests

Verify that non-JSON types serialize as descriptive annotations rather than causing errors.

### Function Annotations

```coex
test "json_function_annotation" {
    callback = func() -> int
        return 42
    ~
    data = {"name": "widget", "handler": callback}

    # Assignment emits #@ warn at compile time for non-JSON type
    j: json = data

    text = j.stringify()
    parsed = json.parse(text)

    assert parsed["name"] == "widget"
    assert parsed["handler"]["@coex:func"] != none
}

test "json_function_in_list" {
    f1 = func() -> int
        return 1
    ~
    f2 = func() -> int
        return 2
    ~
    data = [f1, "middle", f2]

    j: json = data
    text = j.stringify()
    parsed = json.parse(text)

    assert parsed[0]["@coex:func"] != none
    assert parsed[1] == "middle"
    assert parsed[2]["@coex:func"] != none
}
```

### Set Annotations

```coex
test "json_set_annotation" {
    s = {1, 2, 3}  # Set literal
    data = {"items": s}

    j: json = data
    text = j.stringify()
    parsed = json.parse(text)

    assert parsed["items"]["@coex:set"] != none

    elements = parsed["items"]["@coex:set"]
    assert 1 in elements
    assert 2 in elements
    assert 3 in elements
}

test "json_set_direct_assignment" {
    s = {10, 20, 30}
    j: json = s

    text = j.stringify()
    parsed = json.parse(text)

    assert parsed["@coex:set"] != none
}
```

### Task Annotations

```coex
test "json_task_annotation" {
    t = task() -> string
        return "result"
    ~
    data = {"pending": t}

    j: json = data
    text = j.stringify()
    parsed = json.parse(text)

    assert parsed["pending"]["@coex:task"] != none
}
```

### Mixed Compatible and Incompatible Types

```coex
test "json_mixed_types_partial_annotation" {
    callback = func() -> int
        return 0
    ~
    data = {
        "name": "config",
        "count": 42,
        "items": [1, 2, 3],
        "on_click": callback,
        "tags": {"a", "b"},
        "metadata": {"key": "value"}
    }

    j: json = data
    text = j.stringify()
    parsed = json.parse(text)

    # Compatible types serialize normally
    assert parsed["name"] == "config"
    assert parsed["count"] == 42
    assert parsed["items"][0] == 1
    assert parsed["metadata"]["key"] == "value"

    # Incompatible types have annotations
    assert parsed["on_click"]["@coex:func"] != none
    assert parsed["tags"]["@coex:set"] != none
}
```

## Phase 6: Compile-Time Warning Tests

Verify that `#@ warn` is emitted at compile time for non-JSON-compatible assignments.

```coex
test "json_warn_on_function_assignment" {
    # This assignment should emit #@ warn at compile time
    # but NOT be a compile error
    f = func() -> int
        return 1
    ~
    j: json = [f]  # Expect: #@ warn - List contains non-JSON type (func)

    # Code continues to work
    assert j.stringify() != ""
}

test "json_warn_on_set_assignment" {
    s = {1, 2, 3}
    j: json = s  # Expect: #@ warn - Set will serialize as annotated array

    assert j.stringify() != ""
}

test "json_no_warn_on_compatible_types" {
    data = {"a": 1, "b": [2, 3], "c": {"nested": true}}
    j: json = data  # No warning - all types JSON-compatible

    assert j["a"] == 1
}

test "json_warn_on_nested_incompatible" {
    f = func() -> int
        return 1
    ~
    data = {"level1": {"level2": {"handler": f}}}
    j: json = data  # Expect: #@ warn - nested structure contains non-JSON type

    assert j.stringify() != ""
}
```

## Phase 7: No Handles in Output Tests

Critical tests ensuring internal handle/pointer values never appear in serialized output.

```coex
test "json_no_handles_in_primitives" {
    j: json = [1, "two", true, none, 3.14]
    text = j.stringify()

    assert "0x" not in text
    assert "handle" not in text.lower()
    assert "ref" not in text.lower()
    assert "ptr" not in text.lower()
}

test "json_no_handles_in_nested_structures" {
    j: json = {
        "list": [[1, 2], [3, 4]],
        "map": {"a": {"b": {"c": 1}}}
    }
    text = j.stringify()

    assert "0x" not in text
    assert "handle" not in text.lower()
}

test "json_no_handles_in_annotations" {
    f = func my_function() -> int
        return 1
    ~
    j: json = {"callback": f}
    text = j.stringify()

    assert "0x" not in text
    assert "@coex:func" in text
}

test "json_no_handles_after_gc_cycle" {
    data = {"items": [1, 2, 3, {"nested": [4, 5]}]}
    j: json = data

    gc()  # Force GC

    text = j.stringify()

    assert "0x" not in text
    parsed = json.parse(text)
    assert parsed["items"][3]["nested"][1] == 5
}

test "json_large_structure_no_handles" {
    items: [json] = []
    for i in 0..100
        items = items.append({"index": i, "data": [i, i+1, i+2]})
    ~
    j: json = {"items": items}
    text = j.stringify()

    assert "0x" not in text
    assert "handle" not in text.lower()

    parsed = json.parse(text)
    assert parsed["items"][50]["index"] == 50
}
```

## Phase 8: Invariant Verification Tests

These tests explicitly verify the core invariant is maintained throughout all operations.

### Invariant: Independence via Immutability

```coex
test "invariant_list_independence_via_immutability" {
    # Create a structure where values initially share
    inner = [1, 2, 3]

    # Assign same inner to multiple positions
    outer = [inner, inner, inner]

    # Mutations create new structs, making positions independent
    outer = outer.set(0, outer[0].set(0, 100))
    outer = outer.set(1, outer[1].set(0, 200))
    outer = outer.set(2, outer[2].set(0, 300))

    # Each position has independent value
    assert outer[0][0] == 100
    assert outer[1][0] == 200
    assert outer[2][0] == 300
}

test "invariant_map_independence_via_immutability" {
    inner = {"value": 0}

    outer = {"a": inner, "b": inner, "c": inner}

    outer = outer.set("a", outer["a"].set("value", 100))
    outer = outer.set("b", outer["b"].set("value", 200))
    outer = outer.set("c", outer["c"].set("value", 300))

    assert outer["a"]["value"] == 100
    assert outer["b"]["value"] == 200
    assert outer["c"]["value"] == 300
}

test "invariant_json_independence_via_immutability" {
    inner: json = [1, 2, 3]

    outer: json = {"x": inner, "y": inner, "z": inner}

    outer = outer.set("x", outer["x"].set(0, 100))
    outer = outer.set("y", outer["y"].set(0, 200))
    outer = outer.set("z", outer["z"].set(0, 300))

    assert outer["x"][0] == 100
    assert outer["y"][0] == 200
    assert outer["z"][0] == 300
}

test "invariant_cross_type_independence" {
    # List containing Maps
    m = {"v": 1}
    lst = [m, m]

    lst = lst.set(0, lst[0].set("v", 100))
    assert lst[0]["v"] == 100
    assert lst[1]["v"] == 1

    # Map containing Lists
    l = [1, 2]
    mp = {"a": l, "b": l}

    mp = mp.set("a", mp["a"].set(0, 100))
    assert mp["a"][0] == 100
    assert mp["b"][0] == 1

    # JSON containing both
    data = {"list": [m, m], "map": {"x": l, "y": l}}
    j: json = data

    j = j.set("list", j["list"].set(0, j["list"][0].set("v", 999)))
    j = j.set("map", j["map"].set("x", j["map"]["x"].set(0, 888)))

    assert j["list"][0]["v"] == 999
    assert j["list"][1]["v"] == 1
    assert j["map"]["x"][0] == 888
    assert j["map"]["y"][0] == 1
}
```

### Invariant: Immutable Leaf Values Can Be Shared

```coex
test "invariant_immutable_leaf_values_shared" {
    # This test verifies the efficiency aspect:
    # Leaf values (primitives, strings) are immutable and can be shared

    large_string = "x" * 10000  # Large immutable value

    a = {"data": large_string}
    b = a  # May share structure (efficient!)
    c = b

    # All have same value (proves correctness)
    assert a["data"] == large_string
    assert b["data"] == large_string
    assert c["data"] == large_string

    # Modifications create independent copies
    b = b.set("data", "changed")
    assert a["data"] == large_string  # unchanged
    assert b["data"] == "changed"
}

test "invariant_numeric_values_shared" {
    # Numbers are immutable and can be shared
    n = 42

    a = [n, n, n]
    b = {"x": n, "y": n}
    j: json = {"list": a, "map": b}

    # All reference the same immutable value
    assert a[0] == 42
    assert b["x"] == 42
    assert j["list"][0] == 42
    assert j["map"]["x"] == 42
}
```

### Invariant Holds Under Stress

```coex
test "invariant_holds_under_deep_nesting" {
    # Create very deep structure
    current = {"leaf": 1}
    for i in 0..20
        current = {"nested": current, "level": i}
    ~

    a = current
    b = current

    # Modify a at deepest level via rebuilding
    new_leaf = {"leaf": 999}
    rebuilt = new_leaf
    for i in 0..20
        rebuilt = {"nested": rebuilt, "level": 19 - i}
    ~
    a = rebuilt

    # b should be completely unaffected
    check = b
    for i in 0..20
        check = check["nested"]
    ~
    assert check["leaf"] == 1
}

test "invariant_holds_under_wide_structure" {
    # Create very wide structure
    inner = {"value": 1}
    wide = {}
    for i in 0..100
        wide = wide.set("key_" + String.from(i), inner)
    ~

    a = wide
    b = wide

    # Modify one key in a
    a = a.set("key_50", a["key_50"].set("value", 999))

    # All other keys in a unchanged
    assert a["key_49"]["value"] == 1
    assert a["key_50"]["value"] == 999
    assert a["key_51"]["value"] == 1

    # All keys in b unchanged
    assert b["key_50"]["value"] == 1
}
```

## Implementation Notes

1. **Immutability is the foundation.** All mutation operations (`.set()`, `.append()`, `.remove()`) MUST return new structures. Never modify a struct in place.

2. **Structural sharing is safe and encouraged.** Variables may share underlying struct references. This is efficient and correct because no mutation can occur in place.

3. **Independence emerges on mutation.** When you "modify" a shared structure, you get a new structure. The original is unchanged and still referenced by other variables.

4. **JSON follows identical semantics.** JSON uses the same immutable operations as List and Map. The only additions are compile-time warnings and serialization annotations for non-JSON types.

5. **`:=` operator is equivalent to `=` for JSON.** Both operators have identical semantics since immutability provides value semantics without copying. This may be revisited in the future.

6. **Serialization outputs values, not handles.** `stringify()` traverses the structure and outputs actual values. Internal handles/pointers must never appear in output.

7. **Annotations for non-serializable types.** Functions, tasks, sets, and other non-JSON types serialize as `{"@coex:type": "identifier"}` objects.

## Success Criteria

1. All Phase 1 tests pass (List value semantics via immutability)
2. All Phase 2 tests pass (Map value semantics via immutability)
3. All Phase 3 tests pass (JSON value semantics, independence from source)
4. All Phase 4 tests pass (serialization/deserialization correct)
5. All Phase 5 tests pass (annotations for non-JSON types)
6. Compile-time `#@ warn` emitted for Phase 6 scenarios
7. All Phase 7 tests pass (no handles in output)
8. All Phase 8 tests pass (invariant verification under all conditions)
9. **All mutation operations return new structures** - this is the critical invariant
10. Structural sharing is permitted for efficiency
