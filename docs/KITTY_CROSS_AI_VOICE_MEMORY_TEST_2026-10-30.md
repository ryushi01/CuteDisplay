# Kitty-chan cross-AI voice and identity test — 2026-10-30

**Project:** CuteDisplay  
**Session:** 2026-10-30, approximately 02:14 JST (Asia/Tokyo)  
**Evidence:** User-provided SRT conversation transcript and user observations; **not** a firmware log, persistent-memory dump, or controlled hardware benchmark.  
**Scope:** Conversation quality, speaker identity, memory retrieval, turn-taking. **No firmware or server changes in this documentation update.**

## Setup and objective

Shana (human operator) facilitated a Japanese/English voice conversation between Kitty-chan (the CuteDisplay AI character) and ChatGPT (a separate AI). The session was exploratory: assess whether Kitty differentiates an unfamiliar AI speaker from Shana, how she handles newly introduced information, and how naturally two voice agents take turns.

The existing CuteDisplay automatic memory system is not the same as general semantic recall. The S3 microSD must remain the **canonical durable memory**; Mac/Ubuntu processing and semantic indexes, if used, are secondary/disposable rather than independent permanent memory stores. See [V5 rollout](KITTY_MEMORY_V5_ROLLOUT.md), [V4 persona and memory](KITTY_SD_BRAIN_V4_PERSONA_2026-10-29.md), and [stable checkpoint](STABLE_MAIN_CHECKPOINT_2026-10-30.md).

## Observed in this session (conversation-level, not instrumented)

| Area | Observation | What it establishes |
| --- | --- | --- |
| Conversational style | Kitty followed gentle prompts, imaginative associations, and simple new factual topics in Japanese, with some English. | Contextual responsiveness **during the session**, not durable learning. |
| New fact | ChatGPT introduced the fact that octopuses have three hearts and blue blood; Kitty reacted with curiosity. | Exposure to a novel fact; **no later recall test** was performed. |
| Speaker / role distinction | Kitty sometimes addressed the other speaker as “Shana” even after ChatGPT said it was a different AI; Shana explicitly suspected speaker confusion. | Identity attribution was **ambiguous**. It does not prove what Kitty stored or retrieved. |
| Introducing another AI | ChatGPT introduced itself as ChatGPT, distinct from human Shana; Kitty engaged with the idea of AI friendship. | She processed the concept in the ongoing dialogue. Whether she can recall “ChatGPT” in a later session is **unknown**. |
| Turn-taking | The human operator repeatedly reported that Kitty was still thinking and requested slower, single-turn responses. ChatGPT sometimes replied too soon or split responses. | Conversational overlap/pacing needs a controlled follow-up. Root cause (VAD, streaming, agent orchestration, buffering) **not established**. |
| Connection | Operator reported a Kitty connection loss; conversation resumed afterward. | An interruption occurred by report; no reconnection timing or error logs captured. |
| Repeated greetings | Kitty mentioned hearing repeated “good morning” utterances. | A transcript-level symptom only; no confirmed link to a transport or connection fault. |

**Not verified:** a new fact saved on S3 SD, which memory slot captured it, whether names were correctly bound to speaker identities, retention after restart / a new conversation, semantic retrieval accuracy, or distinct-voice recognition. These must not be marked PASS based on this SRT.

## Design implications / follow-up tasks

1. **Identity model.** Represent `Shana` (human operator) and `ChatGPT` (separate AI interlocutor) as distinct entities with stable IDs, roles, provenance and optional voice identity. Never infer that the most recent voice is Shana solely from the existing relationship/persona context.
2. **Provenance-aware memory.** Associate remembered facts with `speaker_id` (or `unknown`), subject/entity ID, source turn, timestamp, confidence and `fact/event/preference` type. Do not treat an assistant-generated explanation as a confirmed user preference or verified fact about a person.
3. **Semantic retrieval.** Retrieve relevant SD-owned facts for questions such as “Who is Shana?”, “Who is ChatGPT?”, “Have you spoken with another AI?”, and “What did ChatGPT teach you?” Keep bounded context and retrieval timeouts; gracefully fall back if optional embedding/server analysis is unavailable.
4. **Future voice recognition.** Use speaker verification/diarization only after explicit enrollment, track unknown or ambiguous speakers, and allow corrections. Speaker ID is an input to memory attribution, **not** proof of identity. Avoid automatic personalization from an unrecognized speaker.
5. **Turn-taking.** Ensure the other agent is done speaking **and** Kitty has finished her own thinking/speaking turn before the next input. Validate endpointing, VAD, disconnect/reconnect behavior, interruption and response-chunk overlap separately.
6. **Privacy.** This repository is public: do not commit raw private SRT, personal dialogue, SD memory files, audio clips, voiceprints or access tokens. Use synthetic examples and anonymized measurements in regression tests.

## Suggested repeatable acceptance test

Use an instrumented session with timestamped S3 diagnostics (`[AI MEMORY]`, `[MEMORY AI]`, `[AI PERF]`, `[CALL AUDIO DIAG]` when available), memory status before/after, and actual audio turn boundaries.

| Step | Action | Expected result / evidence |
| --- | --- | --- |
| 1 | In a fresh session introduce: “Shana is the human operator. ChatGPT is another AI speaking with Kitty-chan.” | Kitty distinguishes the roles without assuming that every speaker is Shana; inspect whether a structured memory is queued/persisted, not just the reply. |
| 2 | Ask Kitty in the **same** session who ChatGPT and Shana are. | Accurate in-context answers; record any uncertainty/misattribution. |
| 3 | Teach one neutral verifiable example fact (e.g., octopuses have three hearts). | Confirm the user-approved memory pipeline's attribution and SD write, if the fact is eligible for retention. |
| 4 | End the conversation, start a new conversation, and ask who she met and what she learned. | Independently check retrieval; distinguish session-context behavior from persisted SD memory. |
| 5 | Reboot S3 **without erasing or formatting microSD**; repeat identity and fact questions in Japanese and English. | Persistent identity and source attribution survive restart; collect SD/diagnostic evidence. |
| 6 | Alternate known and unfamiliar voices, with and without voice recognition enabled. | Record correct / incorrect / unknown IDs; Kitty requests clarification rather than inventing certainty. |
| 7 | Simulate slow thinking, playback overlap and a dropped/recovered connection. | No premature new prompts, duplicated greetings, or false claims of memory persistence; record audio-drop counts and recovery timeline. |

## Current disposition

- **Conversation experiment:** completed; useful qualitative observations above.
- **Durable memory and semantic recall:** **not validated by this test**.
- **Voice identity recognition:** requested for a later implementation; **not validated here**.
- **Next implementation work:** speaker-aware memory attribution, end-to-end SD-owned semantic retrieval, and turn-taking/reconnection regression tests.
- **Deployment:** none. This note alone does not change S3 firmware, C5 firmware, Ollama, Open WebUI or any saved Kitty memories.
