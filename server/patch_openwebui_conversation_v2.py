#!/usr/bin/env python3
"""Version guarded changes to realtime Kitty emotion tool continuation.

Does not modify authentication, prompt config, or unrelated realtime clients.
"""
import argparse
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument("--source-root",default="/app")
parser.add_argument("--check",action="store_true")
parser.add_argument("--apply",action="store_true")
args=parser.parse_args()
path=Path(args.source_root)/"backend/open_webui/routers/audio/realtime.py"
source=path.read_text()
marker="# CuteDisplay emotion continuation v2"
if marker in source:
    print("CONVERSATION_V2_ALREADY_INSTALLED")
    raise SystemExit(0)
if "KITTY_EXPRESSION_TOOL" not in source or "kitty_expressions" not in source:
    raise SystemExit("Missing validated Kitty expression integration")
old="tools = [] if 'call_id' in metadata else [CHAT_TOOL]"
new="""# CuteDisplay emotion continuation v2
            tools = [] if 'call_id' in metadata else [CHAT_TOOL]
            if self.kitty_expressions and 'call_id' not in metadata:
                tools = [*tools, KITTY_EXPRESSION_TOOL]"""
if source.count(old)!=1:
    raise SystemExit("Unexpected continuation source; no changes made")
# Other branches remain unchanged, as the model might not support tool
# calling inside an already streaming PCM segment.
source=source.replace(old,new,1)
# Permit sequential emotions when desired; avoid mandatory changes.
source=source.replace(
    "continue the spoken conversation normally. Prefer at most one change "
    "'per spoken answer, only when the emotional tone changes.'",
    "continue the spoken conversation normally. Change expression only "
    "'when the emotional tone genuinely changes.'")
source=source.replace(
    '"call set_expression with one supported emotion before speaking. "',
    '"call set_expression with a supported emotion when appropriate; update it again if the emotional tone shifts. "')
compile(source,str(path),"exec")
if args.apply:
    path.write_text(source)
print("CONVERSATION_V2_" + ("APPLIED" if args.apply else "VALID"))
