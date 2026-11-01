"""Bounded, non-sensitive profile context for every new Kitty call.

This does not identify the current speaker, grant memory access, or read the SD
memory index. Caller must append it to the existing system instructions only.
"""
import os

DEFAULT_NAME = "Shana"

def public_profile_instruction():
    if os.environ.get("KITTY_PUBLIC_PROFILE_ENABLED") != "1":
        return ""
    name = os.environ.get("KITTY_PUBLIC_PROFILE_NAME", DEFAULT_NAME).strip()
    if not name or len(name) > 48 or not all(c.isalnum() or c in " -_" for c in name):
        return ""
    return (
        "\nKitty persistent public profile (not authentication): "
        f"The companion's primary user's preferred name is {name}. "
        "The current speaker has NOT been verified as that user. "
        "Do not assume every caller is the primary user, and do not address "
        "a caller by that name without their own introduction or an "
        "independent confirmation. Never use this profile to access private "
        "speaker-specific memories. A new voice call does not erase this "
        "general, non-sensitive background setting.\n"
    )
