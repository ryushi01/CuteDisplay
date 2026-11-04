#!/usr/bin/env python3
"""Optional V6 owner adaptive-voice store for the existing private CPU profile.

Use only from the existing single memory-service process. The same MODEL_LOCK
guards identify(), profile reads and compare-and-swap writes. No WAVs are
stored. Original anchors and all other speakers are immutable. A separately
approved model-pinned enrollment and adaptive-learning consent MUST exist.
No automatic consent or owner enrollment is performed by this module.
"""
import copy


ALLOWED_ADAPTIVE_FIELDS = {
    "adaptive_embeddings", "adaptive_audio_hashes", "adaptive_source",
    "memory_authorization",
}


def load_consented_owner_profile(owner_profile_id):
    from kitty_speaker_cpu_v6 import MODEL_LOCK, _load, ID_PATTERN
    if (not isinstance(owner_profile_id,str)
            or not ID_PATTERN.fullmatch(owner_profile_id)
            or owner_profile_id=="person:owner"):
        return None
    with MODEL_LOCK:
        profile=_load()["speakers"].get(owner_profile_id)
        if (not isinstance(profile,dict)
                or profile.get("adaptive_learning_consent") is not True
                or not isinstance(profile.get("model_id"),str)
                or profile.get("owner_enrollment_id")!=owner_profile_id):
            return None
        return copy.deepcopy(profile)


def save_if_original_unchanged(owner_profile_id, original, candidate):
    from kitty_speaker_cpu_v6 import MODEL_LOCK, _load, _save, ID_PATTERN
    if (not isinstance(owner_profile_id,str)
            or not ID_PATTERN.fullmatch(owner_profile_id)
            or owner_profile_id=="person:owner"
            or not isinstance(original,dict)
            or not isinstance(candidate,dict)):
        return False
    def protected(obj):
        return {key:value for key,value in obj.items()
                if key not in ALLOWED_ADAPTIVE_FIELDS}
    if (protected(original)!=protected(candidate)
            or original.get("adaptive_learning_consent") is not True
            or original.get("owner_enrollment_id")!=owner_profile_id
            or candidate.get("memory_authorization") is not False
            or not isinstance(candidate.get("adaptive_embeddings"),list)
            or len(candidate["adaptive_embeddings"])>6):
        return False
    with MODEL_LOCK:
        profiles=_load()
        latest=profiles["speakers"].get(owner_profile_id)
        # CAS: no stale model, revocation or concurrent manual enrollment
        # may be silently replaced by a background adaptive update.
        if latest!=original or latest.get("adaptive_learning_consent") is not True:
            return False
        profiles["speakers"][owner_profile_id]=copy.deepcopy(candidate)
        _save(profiles)
        return True


def other_enrolled_profiles(owner_profile_id):
    from kitty_speaker_cpu_v6 import MODEL_LOCK, _load, ID_PATTERN
    with MODEL_LOCK:
        profiles=_load()["speakers"]
        return [copy.deepcopy(p) for sid,p in profiles.items()
                if sid!=owner_profile_id and ID_PATTERN.fullmatch(sid)
                and isinstance(p,dict)]
