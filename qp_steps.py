"""Deterministic qp-steps v1 validation and playback; no generated code execution.

See tests/fixtures/qp_steps/README.md for the Python/JS wire contract.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import operator
import re
from datetime import datetime
from typing import NoReturn

_NUMBER = r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
_TOKEN = re.compile(rf"\s*(?:({_NUMBER})|([A-Za-z][A-Za-z0-9_]*)|([+*/^(),-]))")
_ID = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,23}")
_RESERVED = {"constructor", "prototype", "__proto__", "toString", "valueOf",
             "hasOwnProperty", "isPrototypeOf", "propertyIsEnumerable", "toLocaleString",
             "__defineGetter__", "__defineSetter__", "__lookupGetter__", "__lookupSetter__"}
_ARITY = {"sqrt": (1, 1), "min": (1, 200), "max": (1, 200), "abs": (1, 1),
          "round": (2, 2), "ceil": (1, 1), "floor": (1, 1), "ln": (1, 1)}
_COMPARE = {"<": operator.lt, "<=": operator.le, ">": operator.gt,
            ">=": operator.ge, "=": operator.eq}
_TEST = re.compile(rf"(<=|>=|<|>|=)(-?{_NUMBER})")
MAX_BYTES = 65536
# ponytail: exhaustive Cartesian validation; reject >4096 paths rather than sample unsafely.
MAX_SCENARIOS = 4096


class QPStepsError(ValueError):
    """Invalid block or runtime input; the prefix is a stable error category."""


def _fail(code, message) -> NoReturn:
    raise QPStepsError(f"{code}: {message}")


def _finite(value):
    if type(value) not in (int, float):
        _fail("NUMBER", "expected a finite real number (not bool or text)")
    try:
        result = float(value)
    except (OverflowError, ValueError):
        _fail("NUMBER", "number outside binary64 range")
    if not math.isfinite(result):
        _fail("NUMBER", "non-finite result")
    return result


def _identifier(name):
    if not _ID.fullmatch(name) or name in _RESERVED:
        _fail("IDENTIFIER", f"forbidden identifier {name!r}")


class _Parser:
    def __init__(self, text):
        if not isinstance(text, str) or not text.strip() or len(text) > 200:
            _fail("EXPRESSION", "expression must contain 1..200 characters")
        self.tokens = []
        pos = 0
        while pos < len(text.rstrip()):
            match = _TOKEN.match(text, pos)
            if not match:
                _fail("EXPRESSION", f"invalid token at offset {pos}")
            number, name, symbol = match.groups()
            self.tokens.append(("number", number) if number else ("name", name) if name else (symbol, symbol))
            pos = match.end()
        self.tokens.append(("end", ""))
        self.pos = 0
        self.refs = set()

    def take(self, token):
        if self.tokens[self.pos][0] == token:
            value = self.tokens[self.pos][1]
            self.pos += 1
            return value
        return None

    def parse(self):
        tree = self.add()
        if self.tokens[self.pos][0] != "end":
            _fail("EXPRESSION", "unexpected trailing token")
        return tree

    def add(self):
        node = self.multiply()
        while self.tokens[self.pos][0] in ("+", "-"):
            op = self.tokens[self.pos][0]
            self.pos += 1
            node = (op, node, self.multiply())
        return node

    def multiply(self):
        node = self.unary()
        while self.tokens[self.pos][0] in ("*", "/"):
            op = self.tokens[self.pos][0]
            self.pos += 1
            node = (op, node, self.unary())
        return node

    def unary(self):
        if self.take("+") is not None:
            return self.unary()
        if self.take("-") is not None:
            return ("neg", self.unary())
        return self.power()

    def power(self):
        node = self.primary()
        if self.take("^") is not None:
            node = ("^", node, self.unary())
        return node

    def primary(self):
        value = self.take("number")
        if value is not None:
            return ("number", _finite(float(value)))
        name = self.take("name")
        if name is not None:
            _identifier(name)
            if self.take("(") is None:
                self.refs.add(name)
                return ("name", name)
            if name not in _ARITY:
                _fail("FUNCTION", f"function {name!r} is not allowed")
            args = []
            if self.tokens[self.pos][0] != ")":
                args.append(self.add())
                while self.take(",") is not None:
                    args.append(self.add())
            if self.take(")") is None:
                _fail("EXPRESSION", "missing closing parenthesis")
            low, high = _ARITY[name]
            if not low <= len(args) <= high:
                _fail("FUNCTION", f"wrong arity for {name}")
            return ("call", name, args)
        if self.take("(") is not None:
            node = self.add()
            if self.take(")") is None:
                _fail("EXPRESSION", "missing closing parenthesis")
            return node
        _fail("EXPRESSION", "expected number, identifier, or parenthesis")


def _round(value, digits):
    if digits != math.trunc(digits) or not -308 <= digits <= 308:
        _fail("FUNCTION", "round precision must be an integer in [-308, 308]")
    scale = 10.0 ** int(digits)
    scaled = _finite(value * scale)
    lower = math.floor(scaled)
    return (lower + (scaled - lower >= 0.5)) / scale


def _value(tree, env):
    kind = tree[0]
    try:
        if kind == "number":
            return tree[1]
        if kind == "name":
            if tree[1] not in env:
                _fail("REFERENCE", f"undefined or forward reference {tree[1]}")
            return env[tree[1]]
        if kind == "neg":
            return _finite(-_value(tree[1], env))
        if kind == "call":
            args = [_value(arg, env) for arg in tree[2]]
            functions = {"sqrt": math.sqrt, "min": lambda *xs: min(xs),
                         "max": lambda *xs: max(xs), "abs": abs, "round": _round,
                         "ceil": math.ceil, "floor": math.floor, "ln": math.log}
            return _finite(functions[tree[1]](*args))
        left, right = _value(tree[1], env), _value(tree[2], env)
        return _finite({"+": operator.add, "-": operator.sub, "*": operator.mul,
                        "/": operator.truediv, "^": math.pow}[kind](left, right))
    except (ZeroDivisionError, OverflowError, ValueError) as exc:
        if isinstance(exc, QPStepsError):
            raise
        _fail("ARITHMETIC", str(exc))


def _parse(text):
    parser = _Parser(text)
    return parser.parse(), parser.refs


def _numeric_tree(value):
    if isinstance(value, dict):
        for item in value.values():
            _numeric_tree(item)
    elif isinstance(value, list):
        for item in value:
            _numeric_tree(item)
    elif type(value) in (int, float):
        _finite(value)


def _input_value(spec, value):
    value = _finite(value)
    if "min" in spec and value < spec["min"] or "max" in spec and value > spec["max"]:
        _fail("INPUT", f"{spec['label']}: value outside bounds")
    return value


def _object(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        _fail("SCHEMA", f"expected object with required {required} and optional {optional}")


def _string(value, nonempty=False):
    if not isinstance(value, str) or nonempty and not value:
        _fail("SCHEMA", "expected string" + (" (nonempty)" if nonempty else ""))


def _shape_id(value):
    _string(value)
    if not _ID.fullmatch(value) or value in _RESERVED:
        _fail("SCHEMA", f"invalid id {value!r}")


def _array(value, minimum=0, maximum=None):
    if not isinstance(value, list) or len(value) < minimum or maximum is not None and len(value) > maximum:
        _fail("SCHEMA", f"expected array of size {minimum}..{maximum}")


def _integer(value, low, high=math.inf):
    return type(value) in (int, float) and low <= value <= high and value == math.trunc(value)


def _shape_input(value, with_id=False):
    _object(value, ("id", "label", "example") if with_id else ("label", "example"), ("unit", "min", "max"))
    if with_id:
        _shape_id(value["id"])
    _string(value["label"], True)
    if "unit" in value:
        _string(value["unit"])
    for key in ("example", "min", "max"):
        if key in value:
            _finite(value[key])


def _shape(block):
    """Handwritten v1 structure checks: portable as a single stdlib-only file.

    Keep schema/qp-steps-v1.schema.json in sync; neither file loads the other.
    """
    _object(block, ("schema", "method", "kind", "view", "inputs", "steps", "provenance"), ("choices",))
    if block["schema"] != "qp-steps-v1" or block["kind"] not in ("method", "trace") or block["view"] not in ("formula", "table", "network"):
        _fail("SCHEMA", "unknown schema, kind or view")
    _string(block["method"], True)
    _array(block["inputs"], maximum=40)
    for item in block["inputs"]:
        _shape_input(item, with_id=True)
    _array(block.get("choices", []))
    for choice in block.get("choices", []):
        _object(choice, ("id", "label", "default", "options"))
        _shape_id(choice["id"])
        _shape_id(choice["default"])
        _string(choice["label"], True)
        _array(choice["options"], minimum=1)
        for option in choice["options"]:
            _object(option, ("id", "label", "why"))
            _shape_id(option["id"])
            _string(option["label"], True)
            _string(option["why"])
    _array(block["steps"], minimum=1, maximum=80)
    for step in block["steps"]:
        _object(step, ("id", "title", "explain"), ("expr", "input", "unit", "digits", "when", "verdicts", "show"))
        _shape_id(step["id"])
        _string(step["title"], True)
        _string(step["explain"])
        if "unit" in step:
            _string(step["unit"])
        if "digits" in step and not _integer(step["digits"], 0, 15):
            _fail("SCHEMA", "digits must be an integer in [0, 15]")
        if block["kind"] == "method":
            if ("expr" in step) == ("input" in step) or "show" in step:
                _fail("SCHEMA", "method needs exactly one expr/input and no show")
        elif "expr" not in step or "input" in step:
            _fail("SCHEMA", "trace needs expr (possibly empty), not input")
        if "expr" in step:
            _string(step["expr"])
            if len(step["expr"]) > 200 or block["kind"] == "method" and not step["expr"]:
                _fail("SCHEMA", "invalid expression length")
        if "input" in step:
            _shape_input(step["input"])
        if "when" in step:
            if not isinstance(step["when"], dict) or not step["when"]:
                _fail("SCHEMA", "when must be a nonempty choice map")
            for key, value in step["when"].items():
                _shape_id(key)
                _shape_id(value)
        _array(step.get("verdicts", []))
        for verdict in step.get("verdicts", []):
            _object(verdict, ("test", "text"))
            _string(verdict["test"])
            _string(verdict["text"])
            if not _TEST.fullmatch(verdict["test"]):
                _fail("SCHEMA", "invalid verdict comparison")
        if "show" in step:
            _object(step["show"], ("table",), ("highlight",))
            _array(step["show"]["table"])
            for row in step["show"]["table"]:
                _array(row)
                for cell in row:
                    if not isinstance(cell, str):
                        _finite(cell)
            _array(step["show"].get("highlight", []))
            for pair in step["show"].get("highlight", []):
                _array(pair, minimum=2, maximum=2)
                if any(not _integer(index, 0) for index in pair):
                    _fail("SCHEMA", "highlight coordinates must be nonnegative integers")
    provenance = block["provenance"]
    _object(provenance, ("generator", "source_questions", "generated_at", "basis_hash"))
    if provenance["generator"] not in ("webapp", "skill"):
        _fail("SCHEMA", "unknown generator")
    _array(provenance["source_questions"])
    for question in provenance["source_questions"]:
        _string(question)
    _string(provenance["basis_hash"])
    if not re.fullmatch(r"[a-f0-9]{64}", provenance["basis_hash"]):
        _fail("SCHEMA", "basis_hash must be lowercase SHA-256 hex")
    stamp = provenance["generated_at"]
    _string(stamp)
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:[Zz]|[+-][0-9]{2}:[0-9]{2})", stamp):
        _fail("SCHEMA", "generated_at must be an ISO-8601 timestamp with timezone")
    if stamp[-1].upper() != "Z" and (int(stamp[-5:-3]) > 23 or int(stamp[-2:]) > 59):
        _fail("SCHEMA", "invalid generated_at timezone offset")
    try:
        datetime.fromisoformat(stamp.upper().replace("Z", "+00:00"))
    except ValueError:
        _fail("SCHEMA", "invalid generated_at calendar/time")


def _prepare(block):
    try:
        encoded = json.dumps(block, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        _fail("SCHEMA", f"not finite JSON: {exc}")
    if len(encoded) > MAX_BYTES:
        _fail("SIZE", f"block exceeds {MAX_BYTES} UTF-8 bytes")
    _shape(block)
    _numeric_tree(block)
    input_ids = [item["id"] for item in block["inputs"]]
    choices = block.get("choices", [])
    choice_ids = [item["id"] for item in choices]
    if len(set(input_ids + choice_ids)) != len(input_ids + choice_ids):
        _fail("IDENTIFIER", "duplicate input/choice id")
    choice_map = {}
    scenarios = 1
    for choice in choices:
        options = [option["id"] for option in choice["options"]]
        if len(set(options)) != len(options) or choice["default"] not in options:
            _fail("CHOICE", "options must be unique and include default")
        choice_map[choice["id"]] = options
        scenarios *= len(options)
        if scenarios > MAX_SCENARIOS:
            _fail("SIZE", f"choice combinations exceed {MAX_SCENARIOS}")
    inline_ids = {step["id"] for step in block["steps"] if "input" in step}
    if len(block["inputs"]) + len(inline_ids) > 40:
        _fail("SIZE", "top-level plus inline input ids exceed 40")
    definitions = {}
    parsed = []
    for index, step in enumerate(block["steps"]):
        sid, when = step["id"], step.get("when", {})
        if sid in input_ids or sid in choice_ids:
            _fail("IDENTIFIER", f"step {sid} collides with input/choice")
        for key, option in when.items():
            if key not in choice_map or option not in choice_map[key]:
                _fail("CHOICE", f"unknown when choice/option {key}={option}")
        for previous in definitions.get(sid, []):
            if not any(key in previous and previous[key] != value for key, value in when.items()):
                _fail("WHEN", f"definitions of {sid} are not mutually exclusive")
        definitions.setdefault(sid, []).append(when)
        text = step.get("expr", "").strip()
        if "expr" in step and not text and block["kind"] == "method":
            _fail("EXPRESSION", "method steps require a numeric expression or input")
        expression = _parse(step["expr"])[0] if text else None
        table = [[_parse(cell)[0] if isinstance(cell, str) else ("number", _finite(cell))
                  for cell in row] for row in step.get("show", {}).get("table", [])]
        for row, col in step.get("show", {}).get("highlight", []):
            row, col = int(row), int(col)
            if row >= len(table) or col >= len(table[row]):
                _fail("SHOW", f"step {index}: highlight outside table")
        if table and any(len(row) != len(table[0]) for row in table):
            _fail("SHOW", "table must be rectangular")
        if expression is None and step.get("verdicts") and "input" not in step:
            _fail("VERDICT", "explanation-only step has no numeric verdict")
        for verdict in step.get("verdicts", []):
            match = _TEST.fullmatch(verdict["test"])
            _finite(float(match[2]))
        parsed.append((expression, table))
    return parsed, choice_map


def _run(block, parsed, supplied_inputs, selected):
    specs = {item["id"]: item for item in block["inputs"]}
    active = [(step, data) for step, data in zip(block["steps"], parsed)
              if all(selected[key] == value for key, value in step.get("when", {}).items())]
    specs.update({step["id"]: step["input"] for step, _ in active if "input" in step})
    if not isinstance(supplied_inputs, dict) or supplied_inputs.keys() - specs.keys():
        _fail("INPUT", "unknown or inactive input id")
    if block["kind"] == "trace" and any(
        _finite(value) != _finite(specs[key]["example"]) for key, value in supplied_inputs.items()
    ):
        _fail("TRACE", "trace inputs are immutable; regenerate for new numbers")
    env = {item["id"]: _input_value(item, supplied_inputs.get(item["id"], item["example"]))
           for item in block["inputs"]}
    results = []
    for step, (expression, table) in active:
        if "input" in step:
            value = _input_value(step["input"], supplied_inputs.get(step["id"], step["input"]["example"]))
        else:
            value = _value(expression, env) if expression is not None else None
        if value is not None:
            env[step["id"]] = value
        result = {**step, "digits": step.get("digits", 2), "value": value, "verdicts": []}
        for verdict in step.get("verdicts", []):
            op, number = _TEST.fullmatch(verdict["test"]).groups()
            if _COMPARE[op](value, float(number)):
                result["verdicts"].append(verdict["text"])
        if "show" in step:
            result["show"] = {**step["show"], "table": [[_value(cell, env) for cell in row] for row in table]}
        results.append(result)
    return results


def _validated(block):
    parsed, choice_map = _prepare(block)
    for values in itertools.product(*choice_map.values()):
        selected = dict(zip(choice_map, values))
        try:
            _run(block, parsed, {}, selected)
        except QPStepsError as exc:
            _fail(str(exc).split(":", 1)[0], f"choices={selected}: {exc}")
    return parsed, choice_map


def validate(block):
    """Return (ok, errors); errors are strings with stable CATEGORY: prefixes."""
    try:
        _validated(block)
    except (QPStepsError, RecursionError) as exc:
        return False, [str(exc) if isinstance(exc, QPStepsError) else "SIZE: nesting too deep"]
    return True, []


def evaluate(block, inputs=None, choices=None):
    """Return active step dictionaries, adding value, digits and matched verdicts.

    Missing inputs/choices use examples/defaults. Invalid data raises QPStepsError.
    Never rounds intermediate values; a trace rejects changed input values.
    """
    parsed, choice_map = _validated(block)
    if choices is None:
        choices = {}
    if not isinstance(choices, dict) or choices.keys() - choice_map.keys():
        _fail("CHOICE", "unknown choice id")
    selected = {choice["id"]: choices.get(choice["id"], choice["default"])
                for choice in block.get("choices", [])}
    for key, value in selected.items():
        if value not in choice_map[key]:
            _fail("CHOICE", f"unknown option for {key}")
    return _run(block, parsed, {} if inputs is None else inputs, selected)


def basis_hash(method, formulas_section):
    """SHA-256 of whitespace-normalized method + LF + normalized section body.

    Both arguments are plain text; caller selects any section body or Skill formula.
    No heading removal, Markdown rewriting or Unicode normalization occurs here.
    Hashing does not establish correctness or trust in the method's formulas.
    """
    # Explicit ECMAScript whitespace set: identical behavior in Python and JS.
    whitespace = r"[\t-\r \u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+"
    normalized = "\n".join(re.sub(whitespace, " ", text).strip(" ") for text in (method, formulas_section))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
