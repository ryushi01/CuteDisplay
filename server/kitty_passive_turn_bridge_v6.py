#!/usr/bin/env python3
"""Fail-closed, opt-in, passive live event bridge for Kitty V6.

Source component for the private Open WebUI gateway; NOT activated until
the exact live event forwarding scope is validated. This bridge never
rewrites or forwards upstream audio, never grants memory on voice probability,
and never adds a system message merely because a transcript exists.

The only verified context channel requires an *independently provided*
session+item+transcript attestation and separate owner grant. The signer
must not be inferred from iPhone pairing, S3 JSON or a probable voice score.
"""
import asyncio
import re
import secrets

from kitty_gateway_turn_adapter_v6 import GatewayTurnAdapter
from kitty_attested_live_call_v6 import AttestedLiveCall
from kitty_voice_familiarity_hints_v6 import CandidateFamiliarity


class KittyPassiveTurnBridge:
    """Lightweight event observation; all I/O and AI responses stay in gateway."""

    def __init__(self, *, issuer_secret=None, owner_grant_secret=None,
                 enable_familiarity=False, wall_clock=None):
        # The clock can be injected by offline tests; it is never an inbound
        # client, S3 or model supplied timestamp.
        clock_args={"wall_clock":wall_clock} if callable(wall_clock) else {}
        self._turns=GatewayTurnAdapter(attested_call=AttestedLiveCall(
            attestation_secret=issuer_secret,
            owner_grant_secret=owner_grant_secret, **clock_args))
        self._familiarity=CandidateFamiliarity() if enable_familiarity is True else None
        if self._familiarity is not None:
            self._familiarity.begin_call()
        self._closed=False

    @property
    def session_id(self):
        return self._turns.session_id

    def from_client(self, event):
        """Never treat a browser/device speaker ID as a trusted identity."""
        if self._closed:
            return
        try:
            self._turns.observe_client(event)
            if (self._familiarity is not None and isinstance(event,dict)
                    and event.get("type") in
                    ("response.cancel","input_audio_buffer.clear",
                     "conversation.item.delete")):
                self._familiarity.interrupted()
        except (ValueError,TypeError,RuntimeError):
            self._turns.unknown_turn()
            if self._familiarity is not None:
                self._familiarity.interrupted()

    def from_provider(self,event):
        """ONLY from the authenticated upstream-provider receive loop.

        A completed provider item can be observed without an explicit VAD
        speech-stop handler. Observation is never owner verification.
        """
        if self._closed:
            return False
        try:
            result=self._turns.observe_upstream(event)
            if (self._familiarity is not None and isinstance(event,dict)
                    and event.get("type") in
                    ("input_audio_buffer.speech_started","error",
                     "conversation.item.input_audio_transcription.failed")):
                self._familiarity.interrupted()
            return result
        except (ValueError,TypeError,RuntimeError):
            self._turns.unknown_turn()
            if self._familiarity is not None:
                self._familiarity.interrupted()
            return False

    def candidate_from_trusted_cpu(self, *, provider_item_id,
                                   speaker_candidate, score, overlap=False):
        """Convenience ONLY: cannot grant history or save an owner profile."""
        if self._closed or self._familiarity is None:
            return None
        return self._familiarity.observe(
            provider_item_id=provider_item_id,
            speaker_candidate=speaker_candidate,score=score,
            recognizer_source="trusted_gateway_cpu",
            echo_or_overlap=overlap)

    def independently_verified(self, item_id, signed_turn_ticket, *,
                               owner_grant=None, audio_sha256=None):
        """Trusted server-side callback ONLY, never an inbound client event."""
        if self._closed:
            return False
        try:
            return self._turns.verify_independent_turn(
                item_id,signed_turn_ticket,owner_grant=owner_grant,
                audio_sha256=audio_sha256)
        except (ValueError,TypeError,RuntimeError):
            self._turns.unknown_turn()
            return False

    async def context_for_verified_item(self,item_id, *,
                                        service_url="",service_token="",
                                        owner_grant=None,
                                        include_owner_history=False):
        if self._closed:
            return ""
        try:
            return await self._turns.context_for_item(
                item_id,service_url=service_url,
                service_token=service_token,
                owner_grant=owner_grant,
                include_owner_history=include_owner_history)
        except (OSError,ValueError,TypeError,RuntimeError,TimeoutError):
            return ""

    def close(self):
        if self._closed:return
        self._closed=True
        self._turns.close()
        if self._familiarity is not None:
            self._familiarity.end_call()
