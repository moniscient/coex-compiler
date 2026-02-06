# JSON Type Implementation: First-Class Tagged Union

## Overview

Implement the Coex JSON type as a **first-class tagged union** with its own runtime type handling. JSON is NOT composed of Coex `List` or `Map` types—it is an independent type system with dedicated heap representations for each JSON value kind.

This design:
- Eliminates bugs where handle references appear in JSON output
- Preserves Coex's pure value semantics and concurrency safety
- Works within Coex's existing uniform handle architecture
- Uses handles exclusively for all heap references (never raw pointers)
- Provides runtime type dispatch for heterogeneous JSON values
- Handles non-JSON-compatible types gracefully via annotations at serialization time

## Why Not Use List and Map?

Coex's `List` and `Map` are **homogeneously typed** collections. A `List<int>` can only hold integers; a `Map<string, int>` can only hold integer values. There is no `List<any>` or `Map<string, any>`.

JSON requires **heterogeneous** storage: a JSON array can contain integers, strings, booleans, nested objects, and nested arrays all mixed together. A JSON object's values can similarly be any JSON type.

Therefore, JSON must be implemented as its own type system with runtime type discrimination.

## Tagged Union Architecture

### What is a Tagged Union?

A tagged union (also called a sum type or discriminated union) is a value that can be **one of several different types**, with a **tag** that identifies which type it currently holds.

For JSON, a value can be:
- null
- a boolean
- an integer
- a float
- a string
- an array of JSON values
- an object (string-keyed map of JSON values)

The "tag" is the type discriminator. In Coex, this is the `type_id` field in the heap object header.

### How This Maps to Coex's Architecture

Coex already has the infrastructure for tagged unions:

1. **Uniform handles**: All heap-allocated values are accessed via i64 handles (indices into the handle table). The handle size is uniform regardless of what it points to.

2. **Type tags in heap headers**: Every heap object has a 32-byte header containing `type_id`. This is the "tag" that discriminates between types.

3. **Runtime type dispatch**: Given a handle, you can dereference it, read the `type_id` from the header, and switch on it to determine what kind of value you have.

For JSON, we define distinct `type_id` values for each JSON variant:
- `JSON_NULL_TYPE_ID`
- `JSON_BOOL_TYPE_ID`
- `JSON_INT_TYPE_ID`
- `JSON_FLOAT_TYPE_ID`
- `JSON_STRING_TYPE_ID`
- `JSON_ARRAY_TYPE_ID`
- `JSON_OBJECT_TYPE_ID`

A `json` variable holds an i64 handle. To determine what kind of JSON value it is, dereference the handle and read the `type_id`.

## Type Definitions

### Critical: Handles Only

**All references to heap-allocated values in JSON structures MUST be i64 handles, never raw pointers.**

This means:
- JsonArray stores an array of i64 handles to json values
- JsonObject's HAMT stores i64 handles for both keys (strings) and values (json)
- JsonString stores an i64 handle to the underlying Coex string
- Access requires calling `gc_handle_deref(handle)` to get the pointer
- This ensures GC can properly track and relocate all referenced objects

**Why handles, not pointers?**
- Handles are stable across GC compaction (the handle table is updated, not the stored handle values)
- GC tracing uses `gc_mark(handle)` which works on handles
- Raw pointers become invalid if GC relocates objects
- The existing Map implementation uses raw pointers and requires `gc_ptr_to_handle()` recovery—JSON must NOT follow this pattern

### JsonValue Variants

Each JSON value kind has its own heap representation:

```
JsonNull:
  header: { size, type_id=JSON_NULL_TYPE_ID, flags, forward }
  payload: (none - null has no data)

JsonBool:
  header: { size, type_id=JSON_BOOL_TYPE_ID, flags, forward }
  payload: { i8 value }  // 0 = false, 1 = true

JsonInt:
  header: { size, type_id=JSON_INT_TYPE_ID, flags, forward }
  payload: { i64 value }

JsonFloat:
  header: { size, type_id=JSON_FLOAT_TYPE_ID, flags, forward }
  payload: { f64 value }

JsonString:
  header: { size, type_id=JSON_STRING_TYPE_ID, flags, forward }
  payload: { i64 string_handle }  // HANDLE to Coex string, not pointer

JsonArray:
  header: { size, type_id=JSON_ARRAY_TYPE_ID, flags, forward }
  payload: { i64 length, i64 capacity, i64[] element_handles }  // array of HANDLES

JsonObject:
  header: { size, type_id=JSON_OBJECT_TYPE_ID, flags, forward }
  payload: HAMT structure with { i64 key_handle, i64 value_handle } pairs  // all HANDLES
```

### Accessing Values Through Handles

To access a value stored as a handle:

```llvm
; Load the handle from storage
%element_handle = load i64, i64* %element_slot

; Dereference handle to get pointer (REQUIRED)
%element_ptr = call i8* @gc_handle_deref(i64 %element_handle)

; Now cast and use the pointer
%json_ptr = bitcast i8* %element_ptr to %JsonValue*
```

**Never store raw pointers. Never skip gc_handle_deref.**

### The `json` Type in Coex

From the programmer's perspective, `json` is a single type:

```coex
x: json = 42
y: json = "hello"
z: json = [1, "two", true]
w: json = {"name": "Alice", "age": 30}
```

All of these are `json` typed. The runtime representation varies based on the value, but the type system treats them uniformly.

## Runtime Type Dispatch

### Accessing JSON Values

When you access a JSON value, the runtime must dispatch based on the actual type:

```coex
func process(val: json) -> string
    match val
        case null => return "null"
        case bool b => return "bool: " + String.from(b)
        case int n => return "int: " + String.from(n)
        case float f => return "float: " + String.from(f)
        case string s => return "string: " + s
        case array items => return "array with " + String.from(items.length) + " items"
        case object fields => return "object with " + String.from(fields.length) + " fields"
    ~
~
```

### Implementation of `match`

The `match` statement compiles to:
1. Dereference the json handle to get the heap object pointer
2. Read the `type_id` from the header
3. Switch on `type_id` to jump to the appropriate case
4. In each case, cast the payload pointer to the appropriate type and extract the value

```llvm
; Pseudocode for match dispatch
%obj_ptr = call i8* @gc_handle_deref(i64 %json_handle)
%header_ptr = bitcast i8* %obj_ptr to %Header*
%type_id = load i64, %Header* %header_ptr, field 1

switch i64 %type_id, label %default [
  i64 JSON_NULL_TYPE_ID, label %case_null
  i64 JSON_BOOL_TYPE_ID, label %case_bool
  i64 JSON_INT_TYPE_ID, label %case_int
  i64 JSON_FLOAT_TYPE_ID, label %case_float
  i64 JSON_STRING_TYPE_ID, label %case_string
  i64 JSON_ARRAY_TYPE_ID, label %case_array
  i64 JSON_OBJECT_TYPE_ID, label %case_object
]
```

### Array and Object Access

For `JsonArray`, element access requires:
1. Verify index is in bounds
2. Load the handle at that index
3. Return the handle (which is itself a `json` value)

For `JsonObject`, key access requires:
1. Hash the key string
2. Look up in the HAMT
3. Return the handle if found, or error/none if not

## Value Semantics via Immutability

JSON follows Coex's standard immutable value semantics:

1. **All mutation operations return new structures.** `arr.set(0, val)` returns a new JsonArray; the original is unchanged.

2. **Structural sharing is safe.** Two json variables may reference the same heap object. This is safe because no mutation occurs in place.

3. **Independence emerges on mutation.** When you "modify" a json value, you get a new structure. Other references to the original are unaffected.

### Example

```coex
a: json = [1, 2, 3]
b = a  // b and a may share the same JsonArray

b = b.set(0, 100)  // b now points to NEW JsonArray [100, 2, 3]

assert a[0] == 1   // a still points to original [1, 2, 3]
assert b[0] == 100
```

## Garbage Collection

JSON values are heap-allocated and must be traced by the GC. **All tracing uses handles, never raw pointers.**

### Tracing Logic

```
func gc_trace_json(handle):
    obj_ptr = gc_handle_deref(handle)
    type_id = obj_ptr.header.type_id
    
    switch type_id:
        case JSON_NULL_TYPE_ID, JSON_BOOL_TYPE_ID, JSON_INT_TYPE_ID, JSON_FLOAT_TYPE_ID:
            // No internal references to trace
            pass
            
        case JSON_STRING_TYPE_ID:
            // Trace the string handle
            string_handle = obj_ptr.payload.string_handle
            gc_mark(string_handle)
            
        case JSON_ARRAY_TYPE_ID:
            // Trace each element handle
            for i in 0..obj_ptr.payload.length:
                element_handle = obj_ptr.payload.element_handles[i]
                gc_mark(element_handle)
                
        case JSON_OBJECT_TYPE_ID:
            // Trace all key and value handles in the HAMT
            for each (key_handle, value_handle) in obj_ptr.payload.hamt:
                gc_mark(key_handle)    // string handle
                gc_mark(value_handle)  // json handle
```

### Why Handles Matter for GC

1. **gc_mark() expects handles.** The GC marking function takes handles, not pointers.

2. **Handles survive compaction.** When GC relocates objects, the handle table is updated. Code holding handles continues to work. Code holding raw pointers would have dangling references.

3. **Consistent with List behavior.** Lists store reference types as handles (see `expressions.py:912-919`). JSON must follow the same pattern.

4. **Avoid Map's complexity.** Maps store raw pointers and require `gc_ptr_to_handle()` recovery during tracing. This is error-prone. JSON uses handles directly to avoid this complexity.

## Critical Constraints

1. **Do NOT use Coex's `List` or `Map` types for JSON internals.** JSON has its own array and object representations.

2. **Do NOT use Coex's `array` type.** That's for fixed-size stack arrays, unrelated to JSON.

3. **Use HANDLES for all heap references, NEVER raw pointers.** This is critical for GC correctness. JsonArray elements, JsonObject values, and JsonString references must all be i64 handles that go through `gc_handle_deref()` for access. Raw pointer storage (as used in some Map internals) is prohibited for JSON.

4. **All mutation operations must return new structures.** Never modify a JSON heap object in place.

5. **No pointers or handles in serialized output.** `stringify()` outputs valid JSON text only.

6. **Type dispatch is required for all JSON operations.** You cannot assume a json value is a particular variant without checking `type_id`.

## Phase 1: Core Type Infrastructure

### Register JSON Type IDs

Add type ID constants for each JSON variant:

```python
# In type system initialization
JSON_NULL_TYPE_ID = next_type_id()
JSON_BOOL_TYPE_ID = next_type_id()
JSON_INT_TYPE_ID = next_type_id()
JSON_FLOAT_TYPE_ID = next_type_id()
JSON_STRING_TYPE_ID = next_type_id()
JSON_ARRAY_TYPE_ID = next_type_id()
JSON_OBJECT_TYPE_ID = next_type_id()
```

### Heap Allocation Functions

Create allocation functions for each variant:

```
gc_alloc_json_null() -> handle
gc_alloc_json_bool(value: i8) -> handle
gc_alloc_json_int(value: i64) -> handle
gc_alloc_json_float(value: f64) -> handle
gc_alloc_json_string(str_handle: handle) -> handle  // wraps existing string
gc_alloc_json_array(capacity: i64) -> handle
gc_alloc_json_object() -> handle
```

### GC Tracing

Add tracing logic for JSON types:

```
func gc_trace_json(handle):
    obj = deref(handle)
    type_id = obj.header.type_id
    
    switch type_id:
        case JSON_NULL_TYPE_ID, JSON_BOOL_TYPE_ID, JSON_INT_TYPE_ID, JSON_FLOAT_TYPE_ID:
            // No internal references
            pass
        case JSON_STRING_TYPE_ID:
            // String is already traced via normal string handling
            pass
        case JSON_ARRAY_TYPE_ID:
            for each element_handle in obj.elements:
                gc_mark(element_handle)
        case JSON_OBJECT_TYPE_ID:
            for each (key_handle, value_handle) in obj.hamt:
                gc_mark(key_handle)
                gc_mark(value_handle)
```

## Phase 2: JSON Literal Parsing

### Literal Syntax

JSON literals use standard JSON syntax:

```coex
null_val: json = null
bool_val: json = true
int_val: json = 42
float_val: json = 3.14
string_val: json = "hello"
array_val: json = [1, "two", true, null]
object_val: json = {"name": "Alice", "scores": [10, 20, 30]}
```

### Compilation

The compiler recognizes JSON literals and generates appropriate allocation calls:

- `null` → `gc_alloc_json_null()`
- `true`/`false` → `gc_alloc_json_bool(1)` / `gc_alloc_json_bool(0)`
- integer literal → `gc_alloc_json_int(value)`
- float literal → `gc_alloc_json_float(value)`
- string literal → `gc_alloc_json_string(str_handle)`
- array literal → allocate JsonArray, populate with element handles
- object literal → allocate JsonObject, insert key-value pairs

### Type Inference in JSON Context

When a literal appears in a json context, it becomes a JSON value:

```coex
x: json = 42      // JsonInt, not Coex int
y: json = [1, 2]  // JsonArray of JsonInt, not List<int>
```

The `: json` type annotation triggers JSON literal interpretation.

## Phase 3: Operations on JSON Values

### Array Operations

```coex
arr: json = [1, 2, 3]

// Access (requires runtime bounds check)
val = arr[0]  // returns json

// Length
len = arr.length  // returns int

// Mutation (returns new array)
arr2 = arr.set(0, 100)
arr3 = arr.append(4)
arr4 = arr.remove(1)
```

Implementation notes:
- `arr[i]` checks that `arr` is JsonArray (by type_id), then accesses element
- Returns a json handle
- `.set()`, `.append()`, `.remove()` create new JsonArray with structural sharing where possible

### Object Operations

```coex
obj: json = {"name": "Alice", "age": 30}

// Access (requires runtime key lookup)
val = obj["name"]  // returns json
val = obj.name     // alternative syntax, same semantics

// Check key existence
has_key = obj.has("name")  // returns bool

// Keys
keys = obj.keys()  // returns json array of strings

// Mutation (returns new object)
obj2 = obj.set("age", 31)
obj3 = obj.remove("age")
```

Implementation notes:
- `obj[key]` checks that `obj` is JsonObject, then looks up in HAMT
- `.set()` and `.remove()` create new JsonObject with HAMT structural sharing

### Type Checking

```coex
val: json = get_some_json()

if val.is_null() => ...
if val.is_bool() => ...
if val.is_int() => ...
if val.is_float() => ...
if val.is_string() => ...
if val.is_array() => ...
if val.is_object() => ...
```

These compile to `type_id` comparisons.

### Type Extraction

```coex
val: json = 42

// Safe extraction (returns optional or errors)
n: int = val.as_int()      // extracts int, errors if not JsonInt
s: string = val.as_string() // extracts string, errors if not JsonString

// Or with match for safe dispatch
match val
    case int n => use(n)
    case string s => use(s)
    case _ => handle_other()
~
```

## Phase 4: Value Semantics Tests

These tests verify JSON follows immutable value semantics.

### Basic Independence

```coex
test "json_array_independence" {
    a: json = [1, 2, 3]
    b = a
    
    b = b.set(0, 100)
    
    assert a[0].as_int() == 1
    assert b[0].as_int() == 100
}

test "json_object_independence" {
    a: json = {"x": 1, "y": 2}
    b = a
    
    b = b.set("x", 100)
    
    assert a["x"].as_int() == 1
    assert b["x"].as_int() == 100
}

test "json_nested_independence" {
    inner: json = [1, 2, 3]
    outer: json = {"a": inner, "b": inner}
    
    outer = outer.set("a", outer["a"].set(0, 999))
    
    assert outer["a"][0].as_int() == 999
    assert outer["b"][0].as_int() == 1  // independent
}
```

### Deep Nesting

```coex
test "json_deep_nesting_independence" {
    data: json = {
        "level1": {
            "level2": {
                "level3": [1, 2, 3]
            }
        }
    }
    
    copy = data
    
    // Modify deeply
    copy = copy.set("level1", 
        copy["level1"].set("level2",
            copy["level1"]["level2"].set("level3",
                copy["level1"]["level2"]["level3"].set(0, 999))))
    
    assert copy["level1"]["level2"]["level3"][0].as_int() == 999
    assert data["level1"]["level2"]["level3"][0].as_int() == 1
}
```

### Concurrency Safety

```coex
test "json_concurrent_independence" {
    shared: json = {"counter": 0, "data": [1, 2, 3]}
    
    task1_data = shared
    task2_data = shared
    
    task1_data = task1_data.set("counter", 100)
    task2_data = task2_data.set("counter", 200)
    
    assert shared["counter"].as_int() == 0
    assert task1_data["counter"].as_int() == 100
    assert task2_data["counter"].as_int() == 200
}
```

## Phase 5: Serialization

### stringify()

```coex
j: json = {"name": "Alice", "scores": [10, 20, 30], "active": true}
text = j.stringify()
// text == '{"name":"Alice","scores":[10,20,30],"active":true}'
```

Implementation:
1. Check type_id of root value
2. Dispatch to type-specific serialization
3. Recursively serialize nested values
4. Output valid JSON text

### parse()

```coex
text = '{"name": "Bob", "age": 25}'
j: json = json.parse(text)

assert j["name"].as_string() == "Bob"
assert j["age"].as_int() == 25
```

Implementation:
1. Tokenize JSON text
2. Parse according to JSON grammar
3. Allocate appropriate JSON heap objects
4. Return root handle

### Serialization Tests

```coex
test "json_serialize_primitives" {
    assert (null: json).stringify() == "null"
    assert (true: json).stringify() == "true"
    assert (false: json).stringify() == "false"
    assert (42: json).stringify() == "42"
    assert (3.14: json).stringify() == "3.14"
    assert ("hello": json).stringify() == "\"hello\""
}

test "json_serialize_array" {
    j: json = [1, "two", true, null]
    text = j.stringify()
    assert text == "[1,\"two\",true,null]"
}

test "json_serialize_object" {
    j: json = {"a": 1, "b": "two"}
    // Note: object key order may vary
    parsed = json.parse(j.stringify())
    assert parsed["a"].as_int() == 1
    assert parsed["b"].as_string() == "two"
}

test "json_roundtrip" {
    original: json = {
        "users": [
            {"name": "Alice", "active": true},
            {"name": "Bob", "active": false}
        ],
        "count": 2
    }
    
    text = original.stringify()
    restored = json.parse(text)
    
    assert restored["users"][0]["name"].as_string() == "Alice"
    assert restored["count"].as_int() == 2
}
```

## Phase 6: Non-JSON Type Annotations

When assigning non-JSON Coex values to json, emit compile-time warning and serialize as annotations.

### Supported Annotations

```coex
test "json_function_annotation" {
    f = func() -> int
        return 42
    ~
    
    j: json = {"callback": f}  // #@ warn: non-JSON type
    
    text = j.stringify()
    assert "@coex:func" in text
}

test "json_set_annotation" {
    s = {1, 2, 3}  // Coex Set
    
    j: json = {"items": s}  // #@ warn: non-JSON type
    
    text = j.stringify()
    assert "@coex:set" in text
}

test "json_task_annotation" {
    t = task() -> string
        return "result"
    ~
    
    j: json = {"pending": t}  // #@ warn: non-JSON type
    
    text = j.stringify()
    assert "@coex:task" in text
}
```

### Annotation Format

```json
{"@coex:func": "function_name"}
{"@coex:set": [1, 2, 3]}
{"@coex:task": "task_identifier"}
{"@coex:type": "typename", "@coex:id": "identifier"}
```

Annotations are valid JSON. On deserialization, they become regular JSON objects (no magic reconstitution).

## Phase 7: No Handles in Output

Critical tests ensuring internal handles never appear in serialized output.

```coex
test "json_no_handles_simple" {
    j: json = [1, "two", true, null, 3.14]
    text = j.stringify()
    
    assert "0x" not in text
    assert "handle" not in text.lower()
    assert "ptr" not in text.lower()
}

test "json_no_handles_nested" {
    j: json = {
        "array": [[1, 2], [3, 4]],
        "object": {"a": {"b": {"c": 1}}}
    }
    text = j.stringify()
    
    assert "0x" not in text
}

test "json_no_handles_after_gc" {
    j: json = {"items": [1, 2, 3, {"nested": [4, 5]}]}
    
    gc()  // Force garbage collection
    
    text = j.stringify()
    
    assert "0x" not in text
    parsed = json.parse(text)
    assert parsed["items"][3]["nested"][1].as_int() == 5
}

test "json_no_handles_large_structure" {
    items: json = []
    for i in 0..100
        items = items.append({"index": i, "data": [i, i+1, i+2]})
    ~
    
    j: json = {"items": items}
    text = j.stringify()
    
    assert "0x" not in text
    
    parsed = json.parse(text)
    assert parsed["items"][50]["index"].as_int() == 50
}
```

## Phase 8: Match Statement Implementation

### Syntax

```coex
match json_value
    case null => handle_null()
    case bool b => handle_bool(b)
    case int n => handle_int(n)
    case float f => handle_float(f)
    case string s => handle_string(s)
    case array items => handle_array(items)
    case object fields => handle_object(fields)
~
```

### Compilation

1. Emit code to dereference handle and read type_id
2. Emit switch statement on type_id
3. For each case:
   - Jump to case label
   - Extract payload into bound variable (b, n, f, s, items, fields)
   - Execute case body
   - Jump to end of match

### Match Tests

```coex
test "json_match_primitives" {
    func describe(val: json) -> string
        match val
            case null => return "null"
            case bool b => return "bool:" + String.from(b)
            case int n => return "int:" + String.from(n)
            case float f => return "float:" + String.from(f)
            case string s => return "string:" + s
            case array _ => return "array"
            case object _ => return "object"
        ~
    ~
    
    assert describe(null) == "null"
    assert describe(true) == "bool:true"
    assert describe(42) == "int:42"
    assert describe(3.14) == "float:3.14"
    assert describe("hi") == "string:hi"
    assert describe([1,2]) == "array"
    assert describe({"a":1}) == "object"
}

test "json_match_nested_extraction" {
    j: json = {"data": [1, 2, 3]}
    
    match j
        case object fields =>
            match fields["data"]
                case array items =>
                    assert items.length == 3
                case _ => fail("expected array")
            ~
        case _ => fail("expected object")
    ~
}
```

## Implementation Notes

1. **JSON is a first-class type.** It has its own type_id values, heap representations, and runtime dispatch logic. It does not depend on List or Map.

2. **HANDLES ONLY, NEVER RAW POINTERS.** This is the most critical implementation requirement. Every reference to a heap object in JSON structures must be an i64 handle. Access requires `gc_handle_deref()`. Tracing uses `gc_mark(handle)`. This differs from Map's implementation which uses raw pointers—do NOT copy that pattern.

3. **JsonArray uses a simple dynamic array of handles.** Store i64 handles, not pointers. When accessing an element, load the handle then call `gc_handle_deref()` to get the usable pointer.

4. **JsonObject uses HAMT with handle storage.** Each HAMT leaf stores `{ i64 hash, i64 key_handle, i64 value_handle }`. Both key_handle and value_handle are handles that require dereferencing.

5. **All mutation returns new structures.** This is non-negotiable for value semantics.

6. **Type dispatch is everywhere.** Every operation on a json value must check type_id because the actual type is only known at runtime.

7. **String sharing via handles.** JsonString stores a handle to a Coex string, not a copy. The handle is traced during GC so the string stays alive.

8. **Null is a singleton.** Only one JsonNull object needs to exist. All null json values can share the same handle.

9. **Bool can be two singletons.** JsonBool(true) and JsonBool(false) can be pre-allocated singletons.

## Success Criteria

1. JSON type IDs registered and recognized by GC
2. Allocation functions for all JSON variants working
3. **All heap references stored as handles, verified by code review** (no raw pointers in JsonArray elements, JsonObject entries, or JsonString payload)
4. JSON literals compile to appropriate allocations
5. Array access, object access, mutation operations working
6. **All element/value access goes through gc_handle_deref()**
7. Match statement compiles with correct type dispatch
8. All value semantics tests pass (independence via immutability)
9. All serialization tests pass (stringify and parse)
10. Compile-time warnings for non-JSON type assignments
11. Annotations serialize correctly for non-JSON types
12. No handles ever appear in stringify output
13. GC correctly traces all JSON variants using gc_mark(handle)
14. All tests pass after GC cycles (proves handles survive compaction)
