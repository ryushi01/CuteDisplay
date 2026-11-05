#!/usr/bin/env python3
"""Run source-safe gateway and SD/index audit tests in the existing V6 CI suite.

The project offline-test discovery intentionally matches test_kitty_*v6.py.
Import the two prior diagnostic TestCase classes to exercise them without
enabling any deployment or making real memory API calls.
"""
from test_kitty_v6_gateway_memory_path_probe import TestMemoryPathProbe
from test_kitty_v6_memory_readiness_probe import ReadinessProbeTests

__all__ = ["TestMemoryPathProbe", "ReadinessProbeTests"]
