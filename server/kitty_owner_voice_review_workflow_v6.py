#!/usr/bin/env python3
"""Opt-in coordinator: exact-audio owner review -> post-call candidate learning.

SOURCE-ONLY. Not a web route, not running in Open WebUI, not an independent
voice liveness verifier. The gateway alone supplies trusted captured samples;
the owner UI must play that specific sample and explicitly confirm it.

Neither source/client speakers, BLE pairing, owner session grant alone, nor
probable voice matches can create a training receipt. The signed learning-only
receipt is not valid for private semantic recall. No model inference during a
call. At most one sample is retained in RAM for background post-call update.
"""
from kitty_owner_voice_postcall_v6 import PostCallOwnerVoiceLearner
from kitty_owner_voice_review_issuer_v6 import OwnerVoiceLearningApproval


class ReviewedOwnerVoiceLearning:
    def __init__(self, *, issuer, learner, capture_lookup):
        if (not isinstance(issuer,OwnerVoiceLearningApproval)
                or not isinstance(learner,PostCallOwnerVoiceLearner)
                or not callable(capture_lookup)):
            raise TypeError("trusted issuer, learner and capture required")
        self._issuer=issuer
        self._learner=learner
        self._capture=capture_lookup
        self._session=None

    def begin_call(self, gateway_session_id):
        self.cancel()
        if self._learner.begin_call(gateway_session_id):
            self._session=gateway_session_id
            return True
        return False

    def request_sample_review(self, item_id):
        if not self._session:
            return None
        return self._issuer.request_review(self._session,item_id)

    def confirm_sample_review(self, item_id, nonce, signature, *,
                              owner_session_grant):
        if not self._session:
            return False
        session=self._session
        receipt=self._issuer.approve_review(
            session_id=session,item_id=item_id,
            nonce=nonce,signature=signature)
        if not receipt:
            return False
        # Do NOT trust a copied WAV/transcript from an iPhone or S3 request;
        # retrieve the exact source already recorded by the gateway.
        try:
            sample=self._capture(session,item_id)
        except (OSError,ValueError,KeyError,TypeError,RuntimeError):
            return False
        if not isinstance(sample,dict):
            return False
        if (sample.get("session_id")!=session
                or sample.get("item_id")!=item_id
                or sample.get("source")!="gateway_observed_s3_microphone"
                or sample.get("final_transcript") is not True
                or sample.get("overlap") is not False
                or sample.get("playback_active") is not False):
            return False
        return self._learner.offer_verified_owner_turn(
            session_id=session,item_id=item_id,
            transcript=sample.get("transcript"),
            microphone_wav=sample.get("wav"),
            attestation=receipt,owner_grant=owner_session_grant)

    def cancel(self):
        self._issuer.clear()
        self._learner.cancel()
        self._session=None

    def finish_call(self, *, background=True):
        self._issuer.clear()
        self._session=None
        return self._learner.finish_call(background=background)

    @property
    def outcome(self):
        return self._learner.outcome
