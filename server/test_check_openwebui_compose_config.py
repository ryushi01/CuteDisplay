"""Regression tests for real Docker volume names vs Compose logical aliases."""
import importlib.util
from pathlib import Path
import unittest

p = Path(__file__).with_name("check_openwebui_compose_config.py")
spec = importlib.util.spec_from_file_location("check_webui_compose", p)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def cfg(logical="webui_data", actual="open-webui", image="ghcr.io/open-webui/open-webui:main"):
    return {
        "services": {
            "open-webui": {
                "image": image,
                "ports": [{"target": 8080, "published": "8080", "protocol": "tcp"}],
                "volumes": [{
                    "type": "volume",
                    "source": logical,
                    "target": "/app/backend/data",
                }],
            }
        },
        "volumes": {logical: {"name": actual}},
    }


class ComposeValidationTests(unittest.TestCase):
    def test_existing_compose_alias_maps_to_real_docker_volume(self):
        self.assertTrue(mod.check_compose(cfg(), "ghcr.io/open-webui/open-webui:main"))

    def test_candidate_override_with_same_effective_volume(self):
        image = "cutedisplay/openwebui:realtime-apikey-candidate"
        self.assertTrue(mod.check_compose(cfg(image=image), image))

    def test_logical_name_may_equal_real_name(self):
        self.assertTrue(mod.check_compose(
            cfg(logical="open-webui"), "ghcr.io/open-webui/open-webui:main"
        ))

    def test_reject_different_effective_volume(self):
        with self.assertRaisesRegex(ValueError, "not the verified"):
            mod.check_compose(cfg(actual="ryushi_other_volume"), "ghcr.io/open-webui/open-webui:main")

    def test_reject_different_target_image(self):
        with self.assertRaisesRegex(ValueError, "image differs"):
            mod.check_compose(cfg(), "cutedisplay/openwebui:realtime-apikey-candidate")

    def test_reject_missing_or_mapped_port(self):
        data = cfg()
        data["services"]["open-webui"]["ports"][0]["published"] = "8181"
        with self.assertRaisesRegex(ValueError, "8080"):
            mod.check_compose(data, "ghcr.io/open-webui/open-webui:main")

    def test_reject_anonymous_volume(self):
        data = cfg()
        data["services"]["open-webui"]["volumes"][0]["source"] = ""
        with self.assertRaisesRegex(ValueError, "missing Compose volume source"):
            mod.check_compose(data, "ghcr.io/open-webui/open-webui:main")

    def test_reject_bind_mount(self):
        data = cfg()
        data["services"]["open-webui"]["volumes"][0]["type"] = "bind"
        with self.assertRaisesRegex(ValueError, "persistent"):
            mod.check_compose(data, "ghcr.io/open-webui/open-webui:main")


if __name__ == "__main__":
    unittest.main()
