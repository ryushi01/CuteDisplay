#!/usr/bin/env python3
"""No live systemd/network calls: V6 voice patch is exact and rollback-safe."""
import ast
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from kitty_v6_voice_stage_deploy import (
    OLD_BRANCH, StageError, speaker_patch, state_save, restore,
    atomic_write, digest,
)


SOURCE=Path(__file__).resolve().with_name("kitty_speaker_cpu_v6.py").read_text(
    encoding="utf-8"
)


def old_source():
    tree=ast.parse(SOURCE)
    identify=next(n for n in tree.body if isinstance(n,ast.FunctionDef)
                  and n.name=="identify")
    branch=next(n for n in ast.walk(identify) if isinstance(n,ast.If)
                and "KITTY_XVECTOR_EXPERIMENTAL_IDENTITY" in
                ast.get_source_segment(SOURCE,n.test))
    lines=SOURCE.splitlines(keepends=True)
    return "".join(lines[:branch.lineno-2])+OLD_BRANCH+"".join(
        lines[branch.end_lineno:])


class SafetyStageTests(unittest.TestCase):
    def test_specific_old_branch_can_be_upgraded_without_touching_other_code(self):
        old=old_source()
        self.assertEqual(old.count("return recognize_candidate(raw)"),1)
        patched,status=speaker_patch(old,SOURCE)
        self.assertEqual(status,"patched")
        self.assertIn("candidate_only",patched)
        self.assertNotIn("return recognize_candidate(raw)",patched)
        ast.parse(patched)
        self.assertEqual(patched.count("KITTY_XVECTOR_EXPERIMENTAL_IDENTITY"),1)
        self.assertIn("def enroll(",patched)

    def test_custom_or_invalid_old_sources_refused_without_patch(self):
        old=old_source()
        for mutated in (
            old.replace("return recognize_candidate(raw)",
                        "return {'speaker_id':'person:owner'}"),
            old.replace("KITTY_XVECTOR_EXPERIMENTAL_IDENTITY",
                        "KITTY_XVECTOR_GUEST_ID"),
            old+"# KITTY_XVECTOR_EXPERIMENTAL_IDENTITY",
            "invalid syntax !"):
            with self.assertRaises((StageError,SyntaxError)):
                speaker_patch(mutated,SOURCE)

    def test_new_source_is_safe_and_idempotent(self):
        new,status=speaker_patch(SOURCE,SOURCE)
        self.assertEqual(new,SOURCE)
        self.assertEqual(status,"already_safe")

    def test_file_restore_respects_hash_and_removes_only_our_helpers(self):
        import kitty_v6_voice_stage_deploy as deploy
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder)
            local=directory/"live"
            local.mkdir()
            service=local/"kitty_speaker_cpu_v6.py"
            original=b"before"
            patched=b"after"
            helper=local/"kitty_voice_familiarity_hints_v6.py"
            helper.write_bytes(b"new helper")
            service.write_bytes(patched)
            backup=directory/"backup.py"
            backup.write_bytes(original)
            with patch.object(deploy,"STATE",directory/"state"),patch.object(
                    deploy,"STATE_FILE",directory/"state"/"transaction.json"):
                state={"speaker_path":str(service),"backup":str(backup),
                       "old_sha":digest(original),"new_sha":digest(patched),
                       "source_mode":0o644,"created":[helper.name],
                       "module_shas":{helper.name:digest(helper.read_bytes())},
                       "status":"installed"}
                restore(state,strict=True)
                self.assertEqual(service.read_bytes(),original)
                self.assertFalse(helper.exists())
                self.assertEqual(state["status"],"rolled_back")

    def test_rollback_refuses_intervening_change(self):
        import kitty_v6_voice_stage_deploy as deploy
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder)
            local=directory/"speaker.py"
            local.write_bytes(b"unrelated edit")
            backup=directory/"backup"
            backup.write_bytes(b"before")
            state={"speaker_path":str(local),"backup":str(backup),
                   "old_sha":digest(b"before"),"new_sha":digest(b"after"),
                   "source_mode":0o644,"created":[],"module_shas":{},
                   "status":"installed"}
            with self.assertRaises(StageError):
                restore(state,strict=True)
            self.assertEqual(local.read_bytes(),b"unrelated edit")


if __name__=="__main__":
    unittest.main()
