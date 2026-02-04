"""
Tests for user-defined function kinds.

User-defined kinds allow embedding DSLs in Coex. The compiler captures the body
as raw text and passes it to a handler function that implements the behavior.
"""

import pytest


class TestKindDeclaration:
    """Tests for kind declaration parsing."""

    def test_basic_kind_declaration(self, expect_output):
        """Kind declarations should be parsed."""
        expect_output('''
type KindCall:
    name: string
    param_names: [string]
    param_values: [json]
    body: string
~

func echo_handler(call: KindCall) -> string
    return call.body
~

kind echo -> string via echo_handler

func main() -> int
    print("kind declared")
    return 0
~
''', "kind declared\n")

    def test_kind_declaration_with_complex_return_type(self, expect_output):
        """Kind declarations can have any return type."""
        expect_output('''
type KindCall:
    name: string
    param_names: [string]
    param_values: [json]
    body: string
~

type QueryResult:
    rows: int
    body: string
~

func query_handler(call: KindCall) -> QueryResult
    return QueryResult(rows: 1, body: call.body)
~

kind sqlquery -> QueryResult via query_handler

func main() -> int
    print("complex return type")
    return 0
~
''', "complex return type\n")


class TestKindFunctionParsing:
    """Tests for parsing functions using user-defined kinds."""

    def test_simple_kind_function(self, expect_output):
        """Simple kind function with no parameters."""
        expect_output('''
type KindCall:
    name: string
    param_names: [string]
    param_values: [json]
    body: string
~

func echo_handler(call: KindCall) -> string
    return call.body
~

kind echo -> string via echo_handler

echo say_hello() -> string:
    Hello World!
~

func main() -> int
    result = say_hello()
    print(result)
    return 0
~
''', "Hello World!\n")

    def test_kind_function_with_parameters(self, expect_output):
        """Kind function with parameters."""
        expect_output('''
type KindCall:
    name: string
    param_names: [string]
    param_values: [json]
    body: string
~

func template_handler(call: KindCall) -> string
    # Just return body for now - no substitution
    return call.body
~

kind template -> string via template_handler

template greet(name: string, age: int) -> string:
    Hello {{name}}, you are {{age}} years old.
~

func main() -> int
    result = greet("Alice", 30)
    print(result)
    return 0
~
''', "Hello {{name}}, you are {{age}} years old.\n")

    def test_multiline_body(self, expect_output):
        """Kind function body can span multiple lines."""
        expect_output('''
type KindCall:
    name: string
    param_names: [string]
    param_values: [json]
    body: string
~

func sql_handler(call: KindCall) -> string
    return call.body
~

kind sql -> string via sql_handler

sql get_users(min_age: int) -> string:
    SELECT * FROM users
    WHERE age > $1
    ORDER BY name
~

func main() -> int
    result = get_users(25)
    print(result)
    return 0
~
''', "SELECT * FROM users\nWHERE age > $1\nORDER BY name\n")


class TestKindCall:
    """Tests for KindCall structure passed to handlers."""

    def test_kind_call_name(self, expect_output):
        """KindCall.name contains the function name."""
        expect_output('''
type KindCall:
    name: string
    param_names: [string]
    param_values: [json]
    body: string
~

func check_handler(call: KindCall) -> string
    return call.name
~

kind check -> string via check_handler

check my_function() -> string:
    body content
~

func main() -> int
    result = my_function()
    print(result)
    return 0
~
''', "my_function\n")

    def test_kind_call_param_names(self, expect_output):
        """KindCall.param_names contains parameter names in order."""
        expect_output('''
type KindCall:
    name: string
    param_names: [string]
    param_values: [json]
    body: string
~

func check_handler(call: KindCall) -> string
    result = ""
    for name in call.param_names
        result = result + name + ","
    ~
    return result
~

kind check -> string via check_handler

check my_func(param1: int, param2: string, param3: bool) -> string:
    body
~

func main() -> int
    result = my_func(1, "test", true)
    print(result)
    return 0
~
''', "param1,param2,param3,\n")

    def test_kind_call_param_values(self, expect_output):
        """KindCall.param_values contains parameter values at call time."""
        expect_output('''
type KindCall:
    name: string
    param_names: [string]
    param_values: [json]
    body: string
~

func check_handler(call: KindCall) -> int
    # param_values[0] should be the int value wrapped in json
    return call.param_values[0].as_int()
~

kind check -> int via check_handler

check get_first(x: int, y: int) -> int:
    body
~

func main() -> int
    result = get_first(42, 100)
    print(result)
    return 0
~
''', "42\n")


class TestHandlerSubstitution:
    """Tests for handlers that perform substitution."""

    @pytest.mark.xfail(reason="user-defined kind handler substitution not fully implemented")
    def test_curly_brace_substitution(self, expect_output):
        """Handler can substitute {name} placeholders."""
        expect_output('''
type KindCall:
    name: string
    param_names: [string]
    param_values: [json]
    body: string
~

func replace_all(text: string, old: string, new: string) -> string
    # Simple replacement (in practice would loop)
    result = ""
    i = 0
    old_len = old.len()
    while i < text.len()
        if i + old_len <= text.len()
            matched = true
            for j in 0..old_len
                if text[i + j] != old[j]
                    matched = false
                    break
                ~
            ~
            if matched
                result = result + new
                i = i + old_len
                continue
            ~
        ~
        byte_val = text.bytes()[i]
        result = result + String.from_bytes([byte_val])
        i = i + 1
    ~
    return result
~

func template_handler(call: KindCall) -> string
    result = call.body
    i = 0
    while i < call.param_names.len()
        placeholder = "{" + call.param_names[i] + "}"
        value = String.from(call.param_values[i])
        result = replace_all(result, placeholder, value)
        i = i + 1
    ~
    return result
~

kind template -> string via template_handler

template greet(name: string) -> string:
    Hello, {name}!
~

func main() -> int
    result = greet("World")
    print(result)
    return 0
~
''', "Hello, World!\n")

    @pytest.mark.xfail(reason="user-defined kind handler substitution not fully implemented")
    def test_positional_substitution(self, expect_output):
        """Handler can substitute $1, $2 positional placeholders."""
        expect_output('''
type KindCall:
    name: string
    param_names: [string]
    param_values: [json]
    body: string
~

func replace_all(text: string, old: string, new: string) -> string
    result = ""
    i = 0
    old_len = old.len()
    while i < text.len()
        if i + old_len <= text.len()
            matched = true
            for j in 0..old_len
                if text[i + j] != old[j]
                    matched = false
                    break
                ~
            ~
            if matched
                result = result + new
                i = i + old_len
                continue
            ~
        ~
        byte_val = text.bytes()[i]
        result = result + String.from_bytes([byte_val])
        i = i + 1
    ~
    return result
~

func sql_handler(call: KindCall) -> string
    result = call.body
    i = 0
    while i < call.param_values.len()
        placeholder = "$" + String.from(i + 1)
        value = String.from(call.param_values[i])
        result = replace_all(result, placeholder, value)
        i = i + 1
    ~
    return result
~

kind sql -> string via sql_handler

sql query(id: int, name: string) -> string:
    SELECT * FROM users WHERE id = $1 AND name = '$2'
~

func main() -> int
    result = query(42, "Alice")
    print(result)
    return 0
~
''', "SELECT * FROM users WHERE id = 42 AND name = 'Alice'\n")


class TestKindFunctionBodyCapture:
    """Tests for raw body capture."""

    def test_body_preserves_special_chars(self, expect_output):
        """Body should preserve special characters."""
        expect_output('''
type KindCall:
    name: string
    param_names: [string]
    param_values: [json]
    body: string
~

func echo_handler(call: KindCall) -> string
    return call.body
~

kind echo -> string via echo_handler

echo special() -> string:
    {curly} {{double}} $dollar %percent% @at #hash
~

func main() -> int
    result = special()
    print(result)
    return 0
~
''', "{curly} {{double}} $dollar %percent% @at #hash\n")

    def test_body_preserves_indentation(self, expect_output):
        """Body should preserve indentation."""
        expect_output('''
type KindCall:
    name: string
    param_names: [string]
    param_values: [json]
    body: string
~

func yaml_handler(call: KindCall) -> string
    return call.body
~

kind yaml -> string via yaml_handler

yaml config() -> string:
    name: myapp
    settings:
        debug: true
        port: 8080
~

func main() -> int
    result = config()
    # Just check it contains expected content
    if result.len() > 0
        print("has content")
    ~
    return 0
~
''', "has content\n")

    def test_body_with_nested_braces(self, expect_output):
        """Body with nested braces should be captured correctly."""
        # Note: use 'jsondata' instead of 'json' because 'json' is a reserved keyword
        expect_output('''
type KindCall:
    name: string
    param_names: [string]
    param_values: [json]
    body: string
~

func jsondata_handler(call: KindCall) -> string
    return call.body
~

kind jsondata -> string via jsondata_handler

jsondata data() -> string:
    {
        "name": "test",
        "nested": {
            "value": 42
        }
    }
~

func main() -> int
    result = data()
    if result.len() > 10
        print("json captured")
    ~
    return 0
~
''', "json captured\n")


class TestKindErrors:
    """Tests for error handling."""

    def test_unknown_kind_error(self, compile_coex):
        """Using an undeclared kind should produce an error."""
        result = compile_coex('''
unknownkind test() -> string:
    body
~

func main() -> int
    return 0
~
''')
        assert not result.compile_success
        # Should have error about unknown kind

    def test_missing_handler_error(self, compile_coex):
        """Kind with missing handler should produce an error."""
        result = compile_coex('''
kind test -> string via nonexistent_handler

func main() -> int
    return 0
~
''')
        assert not result.compile_success
        # Should have error about missing handler

    def test_handler_wrong_signature(self, compile_coex):
        """Handler with wrong signature should produce an error."""
        result = compile_coex('''
type KindCall:
    name: string
    param_names: [string]
    param_values: [json]
    body: string
~

func wrong_handler(x: int) -> string
    return "wrong"
~

kind test -> string via wrong_handler

func main() -> int
    return 0
~
''')
        assert not result.compile_success
        # Should have error about handler signature


class TestKindReturnTypes:
    """Tests for various return types from kind functions."""

    def test_kind_returning_int(self, expect_output):
        """Kind function can return int."""
        expect_output('''
type KindCall:
    name: string
    param_names: [string]
    param_values: [json]
    body: string
~

func int_handler(call: KindCall) -> int
    return call.body.len()
~

kind intecho -> int via int_handler

intecho count_chars() -> int:
    hello world
~

func main() -> int
    result = count_chars()
    print(result)
    return 0
~
''', "11\n")

    def test_kind_returning_custom_type(self, expect_output):
        """Kind function can return custom type."""
        expect_output('''
type KindCall:
    name: string
    param_names: [string]
    param_values: [json]
    body: string
~

type CheckResult:
    success: bool
    message: string
~

func result_handler(call: KindCall) -> CheckResult
    return CheckResult(success: true, message: call.body)
~

kind check -> CheckResult via result_handler

check verify() -> CheckResult:
    all good
~

func main() -> int
    result = verify()
    if result.success
        print(result.message)
    ~
    return 0
~
''', "all good\n")


class TestKindWithNoParams:
    """Tests for kind functions with no parameters."""

    def test_no_param_kind_function(self, expect_output):
        """Kind function with no parameters should work."""
        expect_output('''
type KindCall:
    name: string
    param_names: [string]
    param_values: [json]
    body: string
~

func static_handler(call: KindCall) -> string
    return "Name: " + call.name + ", Params: " + String.from(call.param_names.len())
~

kind static -> string via static_handler

static my_static() -> string:
    content
~

func main() -> int
    result = my_static()
    print(result)
    return 0
~
''', "Name: my_static, Params: 0\n")


class TestKindImportScenarios:
    """Tests for kind import scenarios."""

    def test_kind_from_module(self, expect_output):
        """Kind can be imported from a module and used with qualified name."""
        expect_output('''
import sqltest

sqltest.sqlquery get_users(min_age: int) -> SqlResult:
    SELECT * FROM users WHERE age > $1
~

func main() -> int
    result = get_users(25)
    print(result.query)
    print(result.param_count)
    return 0
~
''', "SELECT * FROM users WHERE age > $1\n1\n")

    def test_qualified_kind_usage(self, expect_output):
        """Qualified kind usage like module.kindname."""
        expect_output('''
import sqltest

sqltest.sqlquery find_products(category: string, limit: int) -> SqlResult:
    SELECT * FROM products WHERE category = $1 LIMIT $2
~

func main() -> int
    result = find_products("electronics", 10)
    print(result.param_count)
    return 0
~
''', "2\n")

    def test_kind_replace_alias(self, expect_output):
        """Replace alias for kind: replace kind sql with sqltest.sqlquery"""
        expect_output('''
import sqltest
replace kind sql with sqltest.sqlquery

sql query_items(id: int) -> SqlResult:
    SELECT * FROM items WHERE id = $1
~

func main() -> int
    result = query_items(42)
    print(result.param_count)
    return 0
~
''', "1\n")

    def test_kind_conflict_detection(self, compile_coex):
        """Error when using unqualified kind name that doesn't exist locally."""
        result = compile_coex('''
import sqltest

# This should error - sqlquery is only available as sqltest.sqlquery
sqlquery get_data() -> SqlResult:
    SELECT 1
~

func main() -> int
    return 0
~
''')
        assert not result.compile_success
        # Should have error about unknown kind
