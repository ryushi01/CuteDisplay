#!/usr/bin/env python3
"""Kitty V6 private gateway decode-guard diagnostic. Strictly read-only.

Purpose: explain why the exact AST passive observer patch refused a live
provider receive loop. DO NOT echo gateway source, code fragments, names,
paths, transcripts, environment variables, tokens, or computed content hashes.
Only closed-vocabulary labels are emitted.

Usage:
  git show FETCH_HEAD:server/kitty_gateway_decode_preflight_v6.py |
      sudo docker exec -i open-webui python3 -
"""
import ast
from pathlib import Path

GATEWAY=Path("/app/backend/open_webui/routers/audio/realtime.py")
LABELS={
    "provider_handler":"none",
    "client_handler":"none",
    "provider_loop":"none",
    "provider_forward":"none",
    "provider_loop_body":"unknown",
    "event_decoder":"none",
    "event_decoder_position":"unknown",
    "event_decoder_input":"unknown",
    "event_decoder_assignment":"unknown",
    "one_line_decoder":"unknown",
    "source_python":"unknown",
    "exact_patch_refusal":"not_checked",
}
def count(n):
    return "none" if n==0 else "one" if n==1 else "multiple"
def own_nodes(node):
    stack=list(reversed(node.body))
    while stack:
        n=stack.pop()
        if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,
                         ast.ClassDef,ast.Lambda)):
            continue
        yield n
        stack.extend(reversed(list(ast.iter_child_nodes(n))))
def is_forward(node):
    if not isinstance(node,ast.Await) or not isinstance(node.value,ast.Call):
        return False
    c=node.value
    return (len(c.args)==1 and isinstance(c.func,ast.Attribute)
            and c.func.attr=="send_json"
            and isinstance(c.func.value,ast.Name)
            and c.func.value.id=="ws"
            and isinstance(c.args[0],ast.Name)
            and c.args[0].id=="event")
def kind(node):
    if isinstance(node,ast.Try):return "try"
    if hasattr(ast,"TryStar") and isinstance(node,ast.TryStar):return "try"
    if isinstance(node,ast.If):return "if"
    if isinstance(node,ast.Assign):return "assignment"
    if isinstance(node,ast.Expr):return "expression"
    if isinstance(node,ast.AsyncWith):return "async_with"
    if isinstance(node,ast.With):return "with"
    if isinstance(node,ast.AsyncFor):return "async_for"
    return "other"
def assignment(node):
    if isinstance(node,ast.Assign):
        if len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and node.targets[0].id=="event":
            return node.value,"direct_assignment"
    if isinstance(node,ast.AnnAssign):
        if isinstance(node.target,ast.Name) and node.target.id=="event":
            return node.value,"annotated_assignment"
    return None,None
def expr_kind(value,loop_item):
    if isinstance(value,ast.Await):
        value=value.value
    if not isinstance(value,ast.Call):
        return "not_call","not_call"
    func=value.func
    if isinstance(func,ast.Attribute):
        decoder=(
            "loads" if func.attr=="loads" else
            "load" if func.attr=="load" else
            "receive_json" if func.attr in ("receive_json","recv_json") else
            "json_method" if func.attr=="json" else
            "other_call")
    else:
        decoder="other_call"
    if len(value.args)!=1:
        return decoder,"other"
    arg=value.args[0]
    if isinstance(arg,ast.Name):
        return decoder, "upstream_loop_item" if arg.id==loop_item else "other_name"
    if (isinstance(arg,ast.Attribute) and isinstance(arg.value,ast.Name)
            and arg.value.id==loop_item):
        return decoder,"upstream_item_attribute"
    if (isinstance(arg,ast.Subscript) and isinstance(arg.value,ast.Name)
            and arg.value.id==loop_item):
        return decoder,"upstream_item_subscript"
    return decoder,"other_expression"
def target_positions(loop,dec):
    if not loop.body:
        return "empty"
    if dec is loop.body[0]:
        return "first_direct"
    for idx, stmt in enumerate(loop.body):
        if dec is stmt:
            return "later_direct"
        if isinstance(stmt,ast.Try) or (hasattr(ast,"TryStar") and isinstance(stmt,ast.TryStar)):
            if dec in stmt.body:
                return "first_try" if dec is stmt.body[0] and idx==0 else "later_try"
            if dec in stmt.handlers or dec in stmt.finalbody or dec in stmt.orelse:
                return "error_branch"
        if isinstance(stmt,ast.If):
            if dec in stmt.body or dec in stmt.orelse:
                return "if_branch"
    return "nested_control"

def analyze(source):
    result=dict(LABELS)
    if not isinstance(source,str):
        result["source_python"]="unreadable"
        return result
    try:
        tree=ast.parse(source)
    except (SyntaxError,UnicodeError,ValueError):
        result["source_python"]="invalid"
        return result
    result["source_python"]="valid"
    functions=[n for n in ast.walk(tree) if isinstance(n,ast.AsyncFunctionDef)]
    providers=[n for n in functions if n.name=="provider_events"]
    result["provider_handler"]=count(len(providers))
    result["client_handler"]=count(sum(f.name=="client_events" for f in functions))
    if len(providers)!=1 or result["client_handler"]!="one":
        result["exact_patch_refusal"]="provider_scope_unrecognized"
        return result
    p=providers[0]
    loops=[n for n in own_nodes(p) if isinstance(n,ast.AsyncFor)
           and isinstance(n.iter,ast.Name) and n.iter.id=="upstream"
           and isinstance(n.target,ast.Name)]
    result["provider_loop"]=count(len(loops))
    if len(loops)!=1:
        result["exact_patch_refusal"]="provider_loop_unrecognized"
        return result
    loop=loops[0]
    forwards=[n for n in own_nodes(p) if is_forward(n)]
    result["provider_forward"]=count(len(forwards))
    result["provider_loop_body"]=kind(loop.body[0]) if loop.body else "empty"
    if loop.orelse or loop.target.id in ("event","ws") or len(forwards)!=1:
        result["exact_patch_refusal"]="provider_forward_ambiguous"
        return result
    decoded=[]
    for node in own_nodes(p):
        value,assignment_kind=assignment(node)
        if assignment_kind:
            decoder,arg=expr_kind(value,loop.target.id)
            if decoder in ("loads","load","receive_json","json_method"):
                decoded.append((node,decoder,arg,assignment_kind))
    result["event_decoder"]=count(len(decoded))
    if len(decoded)!=1:
        result["exact_patch_refusal"]="provider_decode_unrecognized" if not decoded else "provider_decode_ambiguous"
        return result
    node,decoder,arg,assignment_kind=decoded[0]
    result["event_decoder"]=decoder
    result["event_decoder_input"]=arg
    result["event_decoder_assignment"]=assignment_kind
    result["event_decoder_position"]=target_positions(loop,node)
    result["one_line_decoder"]="yes" if node.lineno==node.end_lineno else "no"
    if (result["event_decoder_position"] not in ("first_direct","first_try")
            or assignment_kind!="direct_assignment"
            or decoder not in ("loads","load")
            or arg!="upstream_loop_item"):
        result["exact_patch_refusal"]="provider_decode_unrecognized"
    elif result["one_line_decoder"]=="no":
        result["exact_patch_refusal"]="multiline_decode_unrecognized"
    else:
        # If all obvious shape checks pass, the remaining refusal comes from
        # line-indentation or patch candidate compilation/postconditions.
        result["exact_patch_refusal"]="post_decode_layout_or_compilation"
    return result

def main():
    try:
        source=GATEWAY.read_text(encoding="utf-8")
    except (OSError,UnicodeError):
        source=None
    print("KITTY_V6_PROVIDER_DECODE_PREFLIGHT_READ_ONLY")
    for k,v in analyze(source).items():
        print(k+"="+v)
    print("No gateway, container, service, audio, firmware or memory changes.")

if __name__=="__main__":
    main()
