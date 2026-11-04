#!/usr/bin/env python3
"""Source-only factories connecting post-call learning to pinned private stores.

Neither factory is called by the deployed gateway. Both default DISABLED.
The real speaker verification issuer and consent workflow must be in place
before a trusted server operator explicitly enables either factory.
"""
from kitty_owner_voice_postcall_v6 import PostCallOwnerVoiceLearner


def ecapa_owner_learner(*, speaker_signer_secret=None,
                       owner_grant_secret=None, model_id="",
                       owner_profile_id="person:shana", enabled=False):
    from kitty_owner_voice_profile_store_v6 import (
        load_consented_owner_profile, save_if_original_unchanged,
        other_enrolled_profiles)
    from kitty_speaker_cpu_v6 import _embedding
    return PostCallOwnerVoiceLearner(
        enabled=enabled,
        attestation_secret=speaker_signer_secret,
        owner_grant_secret=owner_grant_secret,
        model_id=model_id,
        owner_profile_id=owner_profile_id,
        load_profile=lambda:load_consented_owner_profile(owner_profile_id),
        save_profile=lambda old,new:save_if_original_unchanged(
            owner_profile_id,old,new),
        embedding_fn=_embedding,
        other_profiles_fn=lambda:other_enrolled_profiles(owner_profile_id))


def xvector_owner_learner(profile_path, *, speaker_signer_secret=None,
                          owner_grant_secret=None, enabled=False):
    from kitty_xvector_adaptive_store_v6 import (
        MODEL, load_owner_shadow_profile, save_shadow_if_original_unchanged)
    from kitty_xvector_shadow_worker_v6 import embed_verified_postcall
    return PostCallOwnerVoiceLearner(
        enabled=enabled,
        attestation_secret=speaker_signer_secret,
        owner_grant_secret=owner_grant_secret,
        model_id=MODEL,
        owner_profile_id="person:shana",
        load_profile=lambda:load_owner_shadow_profile(profile_path),
        save_profile=lambda old,new:save_shadow_if_original_unchanged(
            profile_path,old,new),
        embedding_fn=embed_verified_postcall,
        other_profiles_fn=lambda:())
