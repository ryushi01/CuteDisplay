#!/usr/bin/env python3
"""One-shot, source-preserving live patch for Kitty V6 snapshot disconnects.

Run through: git show FETCH_HEAD:server/kitty_v6_sync_disconnect_quickfix.py | python3 -
Requires the user's local working checkout with fetched main. Never copies
private tokens, dumps service settings, or creates backup files.
Only exact reviewed handler regions are modified; other owner patches remain.
"""
import os
import stat
import subprocess
import tempfile
from pathlib import Path

PRE_FIX = "f9900cc3f0a96a11026764397fb59c7ee4bf76a2"
SERVICES = (
    ("kitty-memory-v6.service", "kitty_memory_service.py"),
    ("kitty-sync-gateway-v6.service", "kitty_sync_gateway_v6.py"),
)


def command(*args):
    return subprocess.check_output(args, text=True, timeout=20)


def repo_source(ref, name):
    return command("git", "show", ref + ":server/" + name)


def source_path(service, name):
    pid = int(command("systemctl", "--user", "show", service,
                      "-p", "MainPID", "--value").strip())
    if pid < 2:
        raise RuntimeError(service + " is not running")
    parts = (Path("/proc") / str(pid) / "cmdline").read_bytes().split(b"\0")
    for value in parts:
        if not value:
            continue
        arg = os.fsdecode(value)
        if Path(arg).name != name:
            continue
        path = Path(arg)
        if not path.is_absolute():
            path = (Path("/proc") / str(pid) / "cwd").resolve() / path
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("Unsafe live source for " + service)
        info = path.stat()
        if info.st_uid != os.geteuid() or not stat.S_ISREG(info.st_mode):
            raise RuntimeError("Live source is not a user-owned regular file: " + service)
        return path, info
    raise RuntimeError("Cannot identify active Python source for " + service)


def region(data, start, end):
    at = data.index(start)
    until = data.index(end, at + len(start))
    return data[at:until]


def replace_exact(current, old, new, service):
    if current.count(old) == 1:
        return current.replace(old, new), True
    if new in current:
        return current, False
    raise RuntimeError("Live source differs from reviewed patch: " + service)


def update_source(name, live):
    old = repo_source(PRE_FIX, name)
    new = repo_source("FETCH_HEAD", name)
    changed = False
    if name == "kitty_memory_service.py":
        spans = (
            ('    def _reply(self,status,obj):', '    def do_GET(self):'),
        )
    else:
        spans = (
            ('    def reply(self, status, payload):', '    def do_GET(self):'),
            ('            self.send_response(response.status)', '        finally:\n'),
        )
        live, applied = replace_exact(
            live, "UPSTREAM_TIMEOUT_SECONDS = 8\n",
            "UPSTREAM_TIMEOUT_SECONDS = 9\n", name)
        changed |= applied

    for start, end in spans:
        live, applied = replace_exact(
            live, region(old, start, end), region(new, start, end), name)
        changed |= applied

    compile(live, name, "exec")
    return live, changed


def main():
    print("KITTY_V6_SYNC_DISCONNECT_QUICKFIX")
    pending = []
    for service, name in SERVICES:
        path, st = source_path(service, name)
        original = path.read_text(encoding="utf-8")
        patched, changed = update_source(name, original)
        pending.append((service, path, st, patched, changed))
        print(service + " preflight=" + ("PATCH_READY" if changed else "ALREADY_UPDATED"))

    # Preflight both services before touching either. No backup files.
    staged = []
    try:
        for service, path, st, patched, changed in pending:
            if not changed:
                continue
            fd, tmp = tempfile.mkstemp(prefix=".kitty-quickfix-", dir=str(path.parent))
            staged.append((tmp, path))
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                os.fchmod(f.fileno(), stat.S_IMODE(st.st_mode))
                if st.st_gid != os.fstat(f.fileno()).st_gid:
                    os.fchown(f.fileno(), st.st_uid, st.st_gid)
                f.write(patched)
                f.flush()
                os.fsync(f.fileno())
            if path.stat().st_ino != st.st_ino:
                raise RuntimeError("Live source changed during preflight: " + service)

        for tmp, path in staged:
            os.replace(tmp, path)
        staged.clear()

    finally:
        for tmp, _ in staged:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass

    if any(item[-1] for item in pending):
        subprocess.run(["systemctl", "--user", "restart",
                        *(item[0] for item in pending if item[-1])], check=True)
        print("changed_services_restarted=yes")
    else:
        print("changed_services_restarted=no")

    for service, _, _, _, _ in pending:
        print(service + " active=" +
              command("systemctl", "--user", "is-active", service).strip())
        print(service + " enabled=" +
              command("systemctl", "--user", "is-enabled", service).strip())
    try:
        print(command("loginctl", "show-user", os.environ["USER"], "-p", "Linger").strip())
    except (subprocess.SubprocessError, KeyError):
        print("Linger=unavailable")
    print("changes=reviewed_source_only;no_data_deleted;no_firmware_flash")


if __name__ == "__main__":
    main()
