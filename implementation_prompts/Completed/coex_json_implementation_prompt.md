# Task: Implement JSON as a First-Class Type in Coex

## Overview

Add `json` as a built-in primitive type in Coex, alongside `int`, `float`, `string`, `bool`, and collections. JSON values are pure data—all expressions evaluate at construction time. The type supports implicit bidirectional conversion with typed Coex values, with automatic type tagging for round-trip fidelity.

JSON is implemented as a persistent data structure with structural sharing, following the same immutability model as Coex lists, maps, and sets.

## Design Decisions Summary

| Decision | Choice |
|----------|--------|
| Key syntax | Both bare identifiers and quoted strings allowed |
| Type tag field | `_type` (underscore prefix) |
| Enum variant field | `_variant` |
| Conversion failure | `as T` panics, `as T?` returns nil |
| Field access | Dot syntax for identifiers, bracket syntax for dynamic/special keys |
| Null keyword | `null` in json, `nil` in Coex, convert at boundaries |
| Number handling | Infer int/float from decimal presence |
| Type tagging | Always included, with strip option for external interop |
| Map interop | `Map<string, T>` and json objects convert freely |

---

## JSON Literal Syntax

Curly braces `{}` denote json object literals. Keys can be bare identifiers or quoted strings. Use bare identifiers for simple keys, quotes for special characters (hyphens, spaces, etc.).

```coex
j: json = { name: "Alice", age: 30 }
j: json = { "hyphen-key": 42, normal_key: "value" }
j: json = { "spaces in key": true, regularKey: false }
```

---

## The json Type

JSON values can hold: `null`, `bool`, `int`, `float`, `string`, arrays of json, or objects (string-keyed maps of json).

```coex
j: json = null
j: json = true
j: json = 42
j: json = 3.14
j: json = "hello"
j: json = [1, 2, 3]
j: json = { name: "Alice", scores: [95, 87, 92] }
```

---

## Null vs Nil

- `null` is the JSON keyword for json null values
- `nil` is the Coex keyword for optional type absence
- They convert to each other at type boundaries

```coex
j: json = null            # json null
j: json = { value: null } # nested null
x: string? = nil          # Coex optional

# Conversion: Coex nil -> json null
opt: string? = nil
j: json = opt             # becomes null in json

# Conversion: json null -> Coex nil
j: json = null
opt: string? = j as string?  # becomes nil
```

---

## Number Handling

- JSON numbers without decimals deserialize as `int`
- JSON numbers with decimals deserialize as `float`
- Serialization preserves the distinction

```coex
j: json = { count: 42, price: 19.99 }

count: int = j.count as int       # works, 42 is int
price: float = j.price as float   # works, 19.99 is float
wrong: int = j.price as int       # fails, 19.99 is not int
```

---

## Field Access

- Dot syntax for identifier keys, returns json (null if missing)
- Bracket syntax for dynamic or special-character keys

```coex
j: json = { user: { name: "Alice", "e-mail": "alice@example.com" } }

name: json = j.user.name           # dot access
email: json = j.user["e-mail"]     # bracket access
dynamic: json = j[key_variable]    # dynamic access

missing: json = j.user.nonexistent # returns null, not error
```

---

## Type Conversion: Typed to JSON

Any typed Coex value converts implicitly to json. All expressions evaluate at conversion time—json holds only data, never references or thunks.

```coex
person: Person = Person { name: "Alice", age: 30 }
j: json = person  # implicit conversion
```

### Type Tagging

All typed-to-json conversions include a `_type` field for round-trip fidelity:

```coex
type Person:
    name: string
    age: int
~

person: Person = Person { name: "Alice", age: 30 }
j: json = person
# Result: { "_type": "Person", "name": "Alice", "age": 30 }
```

For nested types:

```coex
type Company:
    name: string
    ceo: Person
~

company: Company = Company { name: "Acme", ceo: Person { name: "Bob", age: 45 } }
j: json = company
# Result: {
#   "_type": "Company",
#   "name": "Acme", 
#   "ceo": { "_type": "Person", "name": "Bob", "age": 45 }
# }
```

### Enum Serialization

```coex
enum Status:
    Pending
    Active(since: int)
    Error(code: int, message: string)
~

j: json = Status.Pending
# { "_type": "Status", "_variant": "Pending" }

j: json = Status.Active(since: 1703001600)
# { "_type": "Status", "_variant": "Active", "since": 1703001600 }

j: json = Status.Error(code: 500, message: "failed")
# { "_type": "Status", "_variant": "Error", "code": 500, "message": "failed" }
```

---

## Type Conversion: JSON to Typed

Uses `as` syntax. Non-nullable panics on failure, nullable returns nil:

```coex
j: json = { "_type": "Person", "name": "Alice", "age": 30 }

# Panics if conversion fails (type mismatch, missing fields, wrong _type)
person: Person = j as Person

# Returns nil if conversion fails
person: Person? = j as Person?
```

Conversion validates:
- `_type` field matches target type name (if present)
- All required fields exist
- All field types are compatible

If json lacks `_type`, structural matching is used (all fields must match by name and type).

---

## Collection Conversions

Lists convert to json arrays:

```coex
items: [int] = [1, 2, 3]
j: json = items  # [1, 2, 3]

back: [int] = j as [int]  # works
```

Maps with string keys convert to json objects:

```coex
m: Map<string, int> = Map { "a": 1, "b": 2 }
j: json = m  # { "a": 1, "b": 2 }

back: Map<string, int> = j as Map<string, int>  # works
```

---

## JSON to String (Serialization)

```coex
j: json = { name: "Alice", age: 30 }

# Compact serialization
text: string = j as string
# {"_type":"...","name":"Alice","age":30}

# Pretty printing via method
text: string = j.pretty(indent: 2)
# {
#   "name": "Alice",
#   "age": 30
# }
```

---

## String to JSON (Parsing)

```coex
text: string = "{ \"name\": \"Alice\" }"

# Parse with potential failure
j: json? = text as json?       # nil if parse fails
j: json = text as json         # panics if parse fails

# Or explicit constructor
j: json = json(text)           # panics if parse fails  
j: json? = json.parse(text)    # returns nil if parse fails
```

---

## Validation Methods

### `.validjson()` on string

Returns true if the string contains syntactically valid JSON that can be parsed.

```coex
text1: string = "{\"name\": \"Alice\"}"
text1.validjson()  # true

text2: string = "{name: broken}"
text2.validjson()  # false - invalid JSON syntax

text3: string = "just plain text"
text3.validjson()  # false - not JSON

text4: string = "42"
text4.validjson()  # true - valid JSON primitive

text5: string = "[1, 2, 3]"
text5.validjson()  # true - valid JSON array
```

### `.validcoex()` on json

Returns true if the json structure is fully typed with `_type` tags that match known Coex types, guaranteeing perfect round-trip deserialization. Checks recursively through all nested objects.

```coex
# Fully tagged with known type
j1: json = { "_type": "Person", "name": "Alice", "age": 30 }
j1.validcoex()  # true

# Nested, fully tagged
j2: json = {
    "_type": "Company",
    "name": "Acme",
    "ceo": { "_type": "Person", "name": "Bob", "age": 45 }
}
j2.validcoex()  # true

# Missing type tag - external JSON
j3: json = { "name": "Alice", "age": 30 }
j3.validcoex()  # false - no _type field

# Unknown type tag
j4: json = { "_type": "UnknownType", "foo": "bar" }
j4.validcoex()  # false - type not registered in program

# Partially tagged
j5: json = {
    "_type": "Company",
    "name": "Acme",
    "ceo": { "name": "Bob", "age": 45 }
}
j5.validcoex()  # false - nested object missing _type

# Primitives and arrays without objects
j6: json = [1, 2, 3]
j6.validcoex()  # true - no objects requiring tags

j7: json = "hello"
j7.validcoex()  # true - primitive, no tags needed

# Array with mixed tagging
j8: json = [
    { "_type": "Person", "name": "Alice", "age": 30 },
    { "name": "Bob" }  # missing tag
]
j8.validcoex()  # false - second element missing _type
```

### Lenient Parsing with String Fallback

Attempts JSON parse, falls back to wrapping raw string as json string value:

```coex
func (s: string) to_json_lenient() -> json

text1: string = "{\"name\": \"Alice\"}"
j1: json = text1.to_json_lenient()  # { "name": "Alice" }

text2: string = "not valid json"
j2: json = text2.to_json_lenient()  # "not valid json" (json string value)

text3: string = "plain text with stuff"
j3: json = text3.to_json_lenient()  # "plain text with stuff" (json string value)
```

---

## Stripping Type Tags

For serializing to external systems that don't understand `_type`:

```coex
person: Person = Person { name: "Alice", age: 30 }
j: json = person

# With tags (default)
tagged: string = j as string
# {"_type":"Person","name":"Alice","age":30}

# Without tags
untagged: string = j.untagged() as string
# {"name":"Alice","age":30}

# Or strip recursively
clean: json = j.strip_types()
```

---

## Expression Evaluation

All expressions in json literals evaluate at construction time:

```coex
count: int = 5
name: string = get_name()

j: json = {
    count: count,           # evaluates to 5
    name: name,             # evaluates to result of get_name()
    doubled: count * 2,     # evaluates to 10
    timestamp: posix.time() # evaluates to current time
}
# j now contains pure data, no references
```

---

## Persistent Data Structure Semantics

JSON values are immutable, persistent tree structures on the heap, following the same model as Coex lists, maps, and sets.

### Immutability

Every json node is immutable once created. There is no mutation—"modifications" return new json values.

```coex
j1: json = { name: "Alice" }
j2: json = j1.set("name", "Bob")

# j1 is unchanged
print(j1.name as string)  # "Alice"
print(j2.name as string)  # "Bob"
```

### Structural Sharing

When a json value is "modified," only the nodes along the path from root to the changed node are copied. All other subtrees are shared.

```coex
j1: json = {
    a: { x: 1, y: 2 },
    b: { x: 3, y: 4 }
}

j2: json = j1.set("a.x", 100)

# j2.b is the exact same heap node as j1.b (shared)
# j2.a is a new node
# j2.a.y is the exact same heap node as j1.a.y (shared)
# j2.a.x is a new node with value 100
```

Visually:

```
j1:                          j2:
{                            {
  a: ─────────┐                a: ─────────┐
  b: ───┐     │                b: ───┐     │
}       │     │              }       │     │
        │     │                      │     │
        │     ▼                      │     ▼
        │     {                      │     {
        │       x: 1   ◄── NOT shared│       x: 100  (new)
        │       y: 2   ◄─────────────│────►  y: 2   (shared)
        │     }                      │     }
        │                            │
        ▼                            ▼
      {...} ◄────────────────────► {...}  (shared entirely)
```

### Heap Representation

Each json value is a tagged union on the heap:

```
JsonValue:
  tag: u8  (null=0, bool=1, int=2, float=3, string=4, array=5, object=6)
  data: union {
    bool_val: i1
    int_val: i64
    float_val: f64
    string_val: pointer to string
    array_val: pointer to JsonArray
    object_val: pointer to JsonObject
  }

JsonArray:
  len: i64
  items: pointer to array of JsonValue pointers

JsonObject:
  len: i64
  keys: pointer to array of string pointers
  values: pointer to array of JsonValue pointers
  (or use the existing Map implementation internally)
```

Primitive values (null, bool, int, float) can be stored inline or as small nodes. Strings, arrays, and objects are heap-allocated and reference-counted or GC-managed like other Coex heap objects.

### Path-Based Modification

The `.set()` method supports dotted paths for deep updates:

```coex
j1: json = { user: { profile: { name: "Alice" } } }

# Deep update - only copies nodes along path
j2: json = j1.set("user.profile.name", "Bob")

# Equivalent to (but more efficient than):
# j2 = j1.set("user", j1.user.set("profile", j1.user.profile.set("name", "Bob")))
```

---

## Methods on json

### Field Access

```coex
j.get(key: string) -> json              # returns null if missing
j.has(key: string) -> bool              # check if key exists
```

### Type Checking

```coex
j.is_null() -> bool
j.is_bool() -> bool
j.is_int() -> bool
j.is_float() -> bool
j.is_string() -> bool
j.is_array() -> bool
j.is_object() -> bool
```

### Array Operations (when j is array)

```coex
j.len() -> int
j.get(index: int) -> json
j.append(value: json) -> json           # returns new json array
j.set(index: int, value: json) -> json  # returns new json array
```

### Object Operations (when j is object)

```coex
j.keys() -> [string]
j.values() -> [json]
j.set(key: string, value: json) -> json   # returns new json object
j.set(path: string, value: json) -> json  # deep path update, returns new json
j.remove(key: string) -> json             # returns new json object
j.merge(other: json) -> json              # shallow merge, returns new json
```

### Validation

```coex
j.validcoex() -> bool                   # true if fully tagged with known types
```

### Serialization

```coex
j.pretty(indent: int) -> string
j.untagged() -> json                    # shallow strip _type
j.strip_types() -> json                 # recursive strip _type and _variant
```

---

## Methods on string (JSON-related)

```coex
s.validjson() -> bool                   # true if valid JSON syntax
s.to_json_lenient() -> json             # parse or wrap as json string
```

---

## Implementation Requirements

### Parser Changes (CoexLexer.g4 / CoexParser.g4)

- Add `json` as a type keyword
- Add `null` as a keyword (distinct from `nil`)
- Add json literal syntax: `{ key: value, ... }` where keys are IDENTIFIER or STRING
- Add json array literal: `[expr, ...]` (may already exist for lists—ensure it works in json context)
- Bracket access syntax: `expr[expr]`

### AST Changes (ast_nodes.py)

- Add `JsonLiteral` node for object literals
- Add `JsonNull` node for null values
- Add `JsonFieldAccess` node for dot access on json
- Add `JsonIndexAccess` node for bracket access on json

### Type System (ast_builder.py)

- Add `json` as a built-in type
- Implement type checking for json literals
- Implement conversion rules between json and other types
- Validate field access on json type

### Code Generation (codegen.py)

- Runtime representation for json values (tagged union with structural sharing)
- Generate json literal construction code
- Generate type-to-json conversion functions for all user-defined types
- Generate json-to-type conversion functions with validation
- Generate serialization (json -> string)
- Generate parsing (string -> json)
- Implement json methods with proper structural sharing
- Implement path-based deep updates with minimal copying
- Maintain type registry for `.validcoex()` checks

### Runtime Support

- JSON parser (can use a C library like cJSON or yyjson, or implement in generated code)
- JSON serializer with pretty-print support
- Dynamic field access on json objects
- Type registry mapping `_type` strings to type metadata

---

## Test Cases

### Basic Literals

```coex
func test_literals() -> int
    j1: json = null
    j2: json = true
    j3: json = 42
    j4: json = 3.14
    j5: json = "hello"
    j6: json = [1, 2, 3]
    j7: json = { name: "Alice", age: 30 }
    j8: json = { "special-key": 42, normal: "value" }
    return 0
~
```

### Nested Structures

```coex
func test_nested() -> int
    j: json = {
        user: {
            name: "Alice",
            contacts: [
                { type: "email", value: "alice@example.com" },
                { type: "phone", value: "555-1234" }
            ]
        },
        active: true
    }
    return 0
~
```

### Field Access

```coex
func test_access() -> int
    j: json = { user: { name: "Alice" }, "special-key": 42 }
    
    name: json = j.user.name
    special: json = j["special-key"]
    missing: json = j.nonexistent  # should be null
    
    return 0
~
```

### Type Conversion - Typed to JSON

```coex
type Person:
    name: string
    age: int
~

func test_to_json() -> int
    p: Person = Person { name: "Bob", age: 25 }
    j: json = p
    
    # Should have _type field
    text: string = j as string
    print(text)  # {"_type":"Person","name":"Bob","age":25}
    
    return 0
~
```

### Type Conversion - JSON to Typed

```coex
func test_from_json() -> int
    j: json = { "_type": "Person", "name": "Carol", "age": 35 }
    
    p: Person = j as Person
    print(p.name)  # Carol
    
    # Safe conversion
    p2: Person? = j as Person?
    
    # Should fail - wrong type
    bad: json = { "name": 123 }  # name should be string
    p3: Person? = bad as Person?  # should be nil
    
    return 0
~
```

### Enum Conversion

```coex
enum Color:
    Red
    Green
    Blue
    Custom(r: int, g: int, b: int)
~

func test_enum() -> int
    c1: Color = Color.Red
    j1: json = c1  # { "_type": "Color", "_variant": "Red" }
    
    c2: Color = Color.Custom(r: 255, g: 128, b: 0)
    j2: json = c2  # { "_type": "Color", "_variant": "Custom", "r": 255, "g": 128, "b": 0 }
    
    # Round trip
    back: Color = j2 as Color
    
    return 0
~
```

### Serialization

```coex
func test_serialization() -> int
    j: json = { name: "Test", values: [1, 2, 3] }
    
    compact: string = j as string
    pretty: string = j.pretty(indent: 2)
    
    print(compact)
    print(pretty)
    
    return 0
~
```

### Parsing

```coex
func test_parsing() -> int
    text: string = "{\"name\": \"Parsed\", \"count\": 42}"
    
    j: json? = text as json?
    match j
        case Some(data):
            print(data.name as string)
        ~
        case None:
            print("parse failed")
        ~
    ~
    
    return 0
~
```

### Expression Evaluation

```coex
func test_expressions() -> int
    x: int = 10
    y: int = 20
    
    j: json = {
        sum: x + y,
        product: x * y,
        message: "x = {x}"
    }
    
    # j contains evaluated values, not expressions
    print(j.sum as int)  # 30
    
    return 0
~
```

### Collection Interop

```coex
func test_collections() -> int
    # List to json
    nums: [int] = [1, 2, 3, 4, 5]
    j1: json = nums
    
    # Map to json
    m: Map<string, int> = Map { "a": 1, "b": 2 }
    j2: json = m
    
    # Back to typed
    nums2: [int] = j1 as [int]
    m2: Map<string, int> = j2 as Map<string, int>
    
    return 0
~
```

### Stripping Type Tags

```coex
func test_strip_types() -> int
    p: Person = Person { name: "Dave", age: 40 }
    j: json = p
    
    tagged: string = j as string
    # {"_type":"Person","name":"Dave","age":40}
    
    untagged: string = j.strip_types() as string  
    # {"name":"Dave","age":40}
    
    return 0
~
```

### Validation - validjson

```coex
func test_validjson() -> int
    valid1: string = "{\"key\": \"value\"}"
    valid2: string = "[1, 2, 3]"
    valid3: string = "\"just a string\""
    valid4: string = "42"
    valid5: string = "true"
    valid6: string = "null"
    
    invalid1: string = "{key: value}"
    invalid2: string = "plain text"
    invalid3: string = "{\"unclosed\": "
    
    assert(valid1.validjson() == true)
    assert(valid2.validjson() == true)
    assert(valid3.validjson() == true)
    assert(valid4.validjson() == true)
    assert(valid5.validjson() == true)
    assert(valid6.validjson() == true)
    
    assert(invalid1.validjson() == false)
    assert(invalid2.validjson() == false)
    assert(invalid3.validjson() == false)
    
    return 0
~
```

### Validation - validcoex

```coex
type Widget:
    id: int
    label: string
~

type Container:
    name: string
    widget: Widget
~

func test_validcoex() -> int
    # Tagged correctly
    w: Widget = Widget { id: 1, label: "button" }
    j1: json = w
    assert(j1.validcoex() == true)
    
    # Nested, tagged correctly
    c: Container = Container { name: "panel", widget: w }
    j2: json = c
    assert(j2.validcoex() == true)
    
    # External JSON without tags
    j3: json = { "id": 1, "label": "button" }
    assert(j3.validcoex() == false)
    
    # Unknown type
    j4: json = { "_type": "Nonexistent", "foo": "bar" }
    assert(j4.validcoex() == false)
    
    # Partial tagging
    j5: json = { "_type": "Container", "name": "panel", "widget": { "id": 1, "label": "x" } }
    assert(j5.validcoex() == false)  # nested widget missing _type
    
    # Primitives - no tags needed
    j6: json = 42
    j7: json = "hello"
    j8: json = [1, 2, 3]
    assert(j6.validcoex() == true)
    assert(j7.validcoex() == true)
    assert(j8.validcoex() == true)
    
    return 0
~
```

### Lenient Parsing

```coex
func test_lenient() -> int
    valid: string = "{\"name\": \"test\"}"
    invalid: string = "just some text"
    
    j1: json = valid.to_json_lenient()
    assert(j1.is_object() == true)
    assert(j1.name as string == "test")
    
    j2: json = invalid.to_json_lenient()
    assert(j2.is_string() == true)
    assert(j2 as string == "just some text")
    
    return 0
~
```

### Structural Sharing

```coex
func test_structural_sharing() -> int
    # Create initial structure
    j1: json = {
        left: { value: 1, child: { deep: "data" } },
        right: { value: 2, child: { deep: "info" } }
    }
    
    # Modify only left branch
    j2: json = j1.set("left.value", 100)
    
    # j1 unchanged
    assert(j1.left.value as int == 1)
    
    # j2 has new value
    assert(j2.left.value as int == 100)
    
    # Right branch shared (implementation detail, but semantically equivalent)
    assert(j1.right.child.deep as string == j2.right.child.deep as string)
    
    # Deep unchanged nodes shared
    assert(j1.left.child.deep as string == j2.left.child.deep as string)
    
    return 0
~
```

### Array Persistence

```coex
func test_array_persistence() -> int
    j1: json = [1, 2, 3, 4, 5]
    j2: json = j1.set(2, 100)  # change index 2
    
    # j1 unchanged
    assert(j1[2] as int == 3)
    
    # j2 has new value
    assert(j2[2] as int == 100)
    
    # Other elements conceptually shared
    assert(j1[0] as int == j2[0] as int)
    assert(j1[4] as int == j2[4] as int)
    
    return 0
~
```

### Deep Path Update

```coex
func test_deep_path_update() -> int
    j1: json = {
        level1: {
            level2: {
                level3: {
                    value: "original"
                }
            }
        }
    }
    
    j2: json = j1.set("level1.level2.level3.value", "modified")
    
    assert(j1.level1.level2.level3.value as string == "original")
    assert(j2.level1.level2.level3.value as string == "modified")
    
    return 0
~
```

---

## Files to Modify

1. **CoexLexer.g4** - Add `JSON`, `NULL` tokens, ensure `{` `}` `[` `]` `:` are available
2. **CoexParser.g4** - Add json literal grammar rules
3. **ast_nodes.py** - Add json-related AST nodes
4. **ast_builder.py** - Build AST for json expressions, implement type checking
5. **codegen.py** - Generate LLVM IR for json operations with persistent data structure semantics

---

## Notes

- JSON is always pure data—no lazy evaluation, no references
- Type tags (`_type`, `_variant`) enable round-trip serialization
- The `null` keyword is distinct from `nil`—they convert at boundaries
- Failed conversions panic with `as T`, return nil with `as T?`
- All json methods that "modify" return new json values with structural sharing
- Only nodes along the modification path are copied; all other subtrees are shared
- Consider using an existing C JSON library (cJSON, yyjson) for parsing/serialization performance, or implement in pure generated code for simplicity
- The type registry must be available at runtime for `.validcoex()` to check `_type` values against known types
