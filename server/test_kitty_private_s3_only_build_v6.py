#!/usr/bin/env python3
"""Run real S3-only packaging shell in a fake toolchain; never use real credentials."""
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "tools" / "build_s3_only_v6.sh"
PLACEHOLDER = """#pragma once
namespace C5Image {
inline constexpr uint32_t version=0;
inline constexpr size_t length=0;
inline constexpr char sha256[]="";
static const uint8_t bytes[] PROGMEM={0};
}
"""


class PrivateS3OnlyBuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "checkout"
        tool = self.repo / "tools" / "build_s3_only_v6.sh"
        tool.parent.mkdir(parents=True)
        shutil.copy2(SOURCE, tool)
        self.sketch = self.repo / "firmware" / "CuteDisplayBrain"
        self.sketch.mkdir(parents=True)
        (self.sketch / "CombinedFirmwareImage.h").write_text(PLACEHOLDER)
        (self.sketch / "CuteDisplayBrain.ino").write_text("void setup(){}\nvoid loop(){}\n")
        self.home = self.root / "home"
        part = self.home / ".arduino15/packages/esp32/hardware/esp32/3.3.12/tools/partitions/default_16MB.csv"
        part.parent.mkdir(parents=True)
        part.write_text("# fake partition for mock compiler\n")
        self.cli = self.root / "arduino-cli"
        self.cli.write_text("""#!/bin/sh
set -eu
[ "$1" = "compile" ]
shift
build=""
project=""
while [ "$#" -gt 0 ]; do
 case "$1" in
   --build-path) build="$2"; shift 2;;
   --fqbn) shift 2;;
   --clean) shift;;
   *) project="$1"; shift;;
 esac
done
[ -f "$project/CombinedFirmwareImage.h" ]
grep -q 'version=0;' "$project/CombinedFirmwareImage.h"
case "$EXPECT_PRIVATE" in
  1) test -f "$project/KittySyncPrivateConfig.h" ;;
  0) test ! -e "$project/KittySyncPrivateConfig.h" ;;
esac
mkdir -p "$build"
printf '\\351S3-only-mock-image' > "$build/CuteDisplayBrain.ino.bin"
""")
        self.cli.chmod(0o700)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["git", "-C", str(self.repo),
                        "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                        "commit", "-q", "--allow-empty", "-m", "mock"], check=True)
        self.header = self.root / "credentials" / "KittySyncPrivateConfig.h"
        self.header.parent.mkdir(parents=True)
        self.secret = "TEST_NONPRODUCTION_TOKEN_" + "X" * 40
        cert = "-----BEGIN CERTIFICATE-----\nTEST_ONLY\n-----END CERTIFICATE-----\n"
        self.header.write_text("#pragma once\n" + "\n".join(
            f"#define {name} {json.dumps(value)}"
            for name, value in (
                ("KITTY_SYNC_V6_URL", "https://ragnarok-project.com/kitty-v6/sync"),
                ("KITTY_SYNC_V6_DEVICE_TOKEN", self.secret),
                ("KITTY_SYNC_V6_CA_PEM", cert),
            )) + "\n")

    def invoke(self, *, private=True, ci=False, out=None, expected=None):
        env = os.environ.copy()
        env.pop("CI", None)
        env.pop("GITHUB_ACTIONS", None)
        env.update(HOME=str(self.home), ARDUINO_CLI=str(self.cli),
                   EXPECT_PRIVATE=str(int(private if expected is None else expected)))
        if private:
            env["KITTY_SYNC_PRIVATE_HEADER"] = str(self.header)
        else:
            env.pop("KITTY_SYNC_PRIVATE_HEADER", None)
        if ci:
            env["GITHUB_ACTIONS"] = "true"
        env["KITTY_S3_ONLY_OUT"] = str(out or self.root / "output")
        return subprocess.run(["bash", str(self.repo / "tools/build_s3_only_v6.sh")],
                              env=env, text=True, capture_output=True, timeout=15)

    def test_private_build_is_s3_only_and_keeps_credentials_out_of_logs(self):
        out = self.root / "private-output"
        p = self.invoke(out=out)
        self.assertEqual(p.returncode, 0, (p.stdout[-600:], p.stderr[-600:]))
        self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((out / "S3-Brain-application.bin").stat().st_mode), 0o600)
        generated = out / "CuteDisplayBrain/KittySyncPrivateConfig.h"
        self.assertEqual(stat.S_IMODE(generated.stat().st_mode), 0o600)
        self.assertIn(self.secret, generated.read_text())
        self.assertNotIn(self.secret, p.stdout + p.stderr)
        self.assertNotIn(self.secret, (out / "README.txt").read_text())
        self.assertIn("C5 image payload: absent", (out / "README.txt").read_text())
        self.assertIn("version=0;", (out / "CuteDisplayBrain/CombinedFirmwareImage.h").read_text())
        self.assertEqual(sorted(x.name for x in out.iterdir()),
                         ["CuteDisplayBrain", "README.txt", "S3-Brain-application.bin", "SHA256SUMS.txt"])

    def test_private_build_refuses_ci_without_output(self):
        out = self.root / "would-be-public"
        p = self.invoke(ci=True, out=out)
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse(out.exists())
        self.assertNotIn(self.secret, p.stderr)

    def test_private_build_refuses_output_inside_git_checkout(self):
        out = self.repo / "unsafe-private-artifact"
        p = self.invoke(out=out)
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse(out.exists())

    def test_invalid_configuration_does_not_create_output(self):
        self.header.write_text("#define KITTY_SYNC_V6_URL \"wrong\"\n")
        out = self.root / "not-compiled"
        p = self.invoke(out=out)
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse(out.exists())
        self.assertNotIn("wrong", p.stdout + p.stderr)

    def test_public_build_excludes_untracked_credential_file(self):
        (self.sketch / "KittySyncPrivateConfig.h").write_text("CONFIDENTIAL_LOCAL_FILE")
        out = self.root / "public-artifact"
        p = self.invoke(private=False, out=out)
        self.assertEqual(p.returncode, 0, (p.stdout[-600:], p.stderr[-600:]))
        self.assertFalse((out / "CuteDisplayBrain").exists())
        self.assertNotIn("CONFIDENTIAL_LOCAL_FILE", p.stdout + p.stderr)


if __name__ == "__main__":
    unittest.main()
