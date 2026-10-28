"""Contract tests on patched upstream WebUI realtime CallProtocol (no live key)."""
import ast
import json
import os
from pathlib import Path
import unittest

class JSONCodec:
    @staticmethod
    def loads(value):
        return json.loads(value)
    @staticmethod
    def dumps(value):
        return json.dumps(value)

def avatar_animation_tools(gestures):
    return []

def load_protocol():
    target = os.getenv("CUTEDISPLAY_PATCHED_REALTIME")
    if not target:
        raise unittest.SkipTest("Patched upstream contract file not selected")
    tree = ast.parse(Path(target).read_text())
    selected = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "CallProtocol":
            selected.append(node)
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in {
                "KITTY_EXPRESSIONS", "KITTY_EXPRESSION_TOOL", "CHAT_TOOL",
                "CALL_STATUSES"
            } for t in node.targets
        ):
            selected.append(node)
    module = ast.Module(body=selected, type_ignores=[])
    namespace = {
        "JSONCodec": JSONCodec,
        "avatar_animation_tools": avatar_animation_tools,
    }
    exec(compile(ast.fix_missing_locations(module), target, "exec"), namespace)
    return namespace

class ExpressionToolContract(unittest.TestCase):
    def setUp(self):
        self.env = load_protocol()
        self.CallProtocol = self.env["CallProtocol"]
        self.allowed = self.env["KITTY_EXPRESSIONS"]

    def event(self, mood, call_id="call-A", response_id="resp-A"):
        return {
            "type": "response.output_item.done",
            "response_id": response_id,
            "item": {
                "type": "function_call",
                "name": "set_expression",
                "status": "completed",
                "call_id": call_id,
                "arguments": json.dumps({"emotion": mood}),
            },
        }

    def test_allowlist_and_device_opt_in(self):
        self.assertEqual(tuple(self.allowed),
                         ("neutral","happy","sad","angry","hungry","sleepy","excited","shy"))
        protocol = self.CallProtocol(kitty_expressions=True)
        for i, mood in enumerate(self.allowed):
            item = self.event(mood, call_id=f"id-{i}", response_id=f"resp-{i}")
            protocol.observe({"type":"response.created",
                              "response":{"id":f"resp-{i}","metadata":{}}})
            protocol.observe(item)
            self.assertTrue(item["animation_valid"])
            self.assertIn(f"id-{i}", protocol.animation_calls)

    def test_bad_emotions_are_not_accepted(self):
        for mood in ("destroy_all", "joy", "scared", "HAPPY", "", 1):
            protocol = self.CallProtocol(kitty_expressions=True)
            event = self.event(mood)
            protocol.observe(event)
            self.assertFalse(event["animation_valid"])
            created = protocol.command({
                "type":"bridge.animation.result",
                "call_id":"call-A",
                "status":"started",
            })
            self.assertIn("unavailable", created["item"]["output"])

    def test_no_tool_exposure_without_capability(self):
        protocol = self.CallProtocol(kitty_expressions=False)
        self.assertFalse(protocol.kitty_expressions)
        event = self.event("happy")
        with self.assertRaises(ValueError):
            protocol.observe(event)

    def test_function_result_and_safe_continuation(self):
        protocol = self.CallProtocol(kitty_expressions=True)
        protocol.observe({"type":"response.created",
                          "response":{"id":"resp-A","metadata":{"input_item_id":"mic-1"}}})
        event = self.event("sad")
        protocol.observe(event)
        self.assertTrue(event["animation_valid"])
        result = protocol.command({
            "type":"bridge.animation.result",
            "call_id":"call-A",
            "status":"started",
        })
        self.assertEqual(result["item"]["type"],"function_call_output")
        self.assertIn("started", result["item"]["output"])
        protocol.observe({"type":"response.done","response":{"id":"resp-A"}})
        next_step = protocol.command({
            "type":"bridge.animation.respond",
            "response_id":"resp-A",
        })
        self.assertEqual(next_step["type"],"response.create")
        self.assertEqual(next_step["response"]["metadata"],{"input_item_id":"mic-1"})
        self.assertEqual(next_step["response"]["tools"], [self.env["CHAT_TOOL"]])

    def test_unknown_call_id_rejected(self):
        protocol=self.CallProtocol(kitty_expressions=True)
        with self.assertRaises(ValueError):
            protocol.command({"type":"bridge.animation.result",
                              "call_id":"forged", "status":"started"})

if __name__ == "__main__":
    unittest.main()
