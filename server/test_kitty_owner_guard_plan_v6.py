#!/usr/bin/env python3
"""Offline tests: live owner-guard plan is a read-only, scoped compatibility check."""
import ast
from pathlib import Path
import unittest
from unittest import mock

from kitty_owner_guard_plan_v6 import MODULES, _topology, candidate, summarize, main

SOURCE=Path(__file__).resolve().with_name("kitty_memory_service.py").read_text(
    encoding="utf-8"
)
LEGACY = '''            if self.path=="/semantic/context":
                index=os.environ.get("KITTY_SEMANTIC_DB","")
                if not index or not os.path.isfile(index):
                    return self._reply(503,{"error":"semantic_index_unavailable"})
                sid=data.get("speaker_id")
                if not isinstance(sid,str) or not re.fullmatch(r"person:[A-Za-z0-9_-]{1,48}",sid):
                    return self._reply(400,{"error":"speaker_identity_required"})
                from kitty_memory_context_v6 import recall_context
                return self._reply(200,{"context":recall_context(
                    index,str(data.get("query",""))[:300],sid)})
            if self.path=="/semantic":
                index=os.environ.get("KITTY_SEMANTIC_DB","")
                if not index or not os.path.isfile(index):
                    return self._reply(503,{"error":"semantic_index_unavailable"})
                from kitty_sd_semantic_index import search
                speaker_id=data.get("speaker_id")
                if (not isinstance(speaker_id,str)
                    or not re.fullmatch(r"person:[A-Za-z0-9_-]{1,48}",speaker_id)):
                    return self._reply(400,{"error":"invalid_speaker_id"})
                return self._reply(200,{"results":search(
                    index,str(data.get("query",""))[:300],
                    speaker_id=speaker_id)})
'''


def live_old():
    first='            if self.path in ("/semantic/context","/semantic"):'
    lines=SOURCE.splitlines(keepends=True)
    tree=ast.parse(SOURCE)
    from kitty_owner_guard_plan_v6 import _route
    branch=next(n for n in ast.walk(tree) if _route(n)=="combined")
    assert lines[branch.lineno-1].startswith(first)
    return "".join(lines[:branch.lineno-1])+LEGACY+"".join(lines[branch.end_lineno:])


class GuardPlanTests(unittest.TestCase):
    def test_real_main_has_exact_combined_guard(self):
        _,topology=_topology(SOURCE)
        self.assertEqual(topology,"combined")
        self.assertIn("authorized_semantic_speaker(", SOURCE)
        self.assertIn("TRUSTED_TURN_SECRET",SOURCE)

    def test_only_old_split_semantic_handlers_qualify_for_candidate(self):
        old=live_old()
        ast.parse(old)
        self.assertEqual(_topology(old)[1],"split")
        # Obsolete two-route patch cannot safely deploy a new independent
        # trusted-turn verifier. Full source rollout is a separate stage.
        self.assertEqual(candidate(old,SOURCE),"no")
        self.assertEqual(candidate(SOURCE,SOURCE),"no")

    def test_unexpected_customizations_fail_closed(self):
        old=live_old()
        self.assertEqual(candidate(old.replace('data.get("speaker_id")','data.get("identity")'),SOURCE),"no")
        self.assertEqual(candidate(old.replace('if self.path=="/semantic":','if self.path=="/semantic-other":'),SOURCE),"no")
        self.assertEqual(candidate(old+"\\n# authorized_semantic_speaker\\n",SOURCE),"no")
        self.assertEqual(candidate("invalid python !",SOURCE),"no")
        self.assertEqual(candidate(old,"invalid python !"),"no")

    def test_summary_never_claims_ready_to_restart(self):
        result=summarize(live_old(),SOURCE,set(MODULES))
        self.assertEqual(result["candidate_compiles"],"no")
        self.assertEqual(result["live_semantic_handlers"],"split")
        self.assertEqual(result["github_guard_handlers"],"combined")
        self.assertEqual(result["patch_applied"],"no")
        self.assertEqual(result["ready_for_live_restart"],"no")
        self.assertFalse(any("/home/" in str(x) for x in result.values()))

    def test_main_exposes_only_status_not_source(self):
        import io
        from contextlib import redirect_stdout
        from kitty_owner_guard_plan_v6 import live_service_source
        with mock.patch("kitty_owner_guard_plan_v6.live_service_source",return_value=None),mock.patch(
            "kitty_owner_guard_plan_v6._run",return_value=SOURCE
        ):
            sink=io.StringIO()
            with redirect_stdout(sink):
                main()
        report=sink.getvalue()
        self.assertIn("KITTY_V6_OWNER_GUARD_READ_ONLY_PLAN",report)
        self.assertIn("patch_applied=no",report)
        self.assertNotIn("MEMORY_DB",report)
        self.assertNotIn("source_path",report)
        self.assertNotIn("from kitty_semantic",report)


if __name__=="__main__":
    unittest.main()
