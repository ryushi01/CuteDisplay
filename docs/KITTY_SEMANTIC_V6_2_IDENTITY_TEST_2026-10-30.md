# Semantic Memory V6.2 — October 30 conversation test: identity and speaker boundaries

Status: **design and pure-Python attribution safeguards committed to feature branch**. The helpers are not connected to S3 firmware, Open WebUI realtime handler, or any running server. No live service was changed.

## Observations from the 01:32–01:48 JST Kitty conversation
- The user observed a conversation involving Kitty and another AI, ChatGPT, in Japanese followed by English.
- Kitty repeatedly addressed **ChatGPT as Shana**, despite explicit statements that ChatGPT and Shana are different participants.
- The owner/creator **Shana** was being discussed, but was not necessarily the person currently talking to Kitty.
- Kitty could follow other conversational material (including octopus facts), but that does **not** prove those facts were committed or recalled after a restart.
- No demonstrated voice biometric identity recognition. No positive proof of long-term memory for non-owner speakers yet.
- Desired behavior: remember facts about owner, another AI, and other people without mixing speaker and subject. Explicit introductions and subsequent corrections should influence attribution, but only an authenticated source can establish verified identity.

## Memory schema direction
Each archived turn and extracted memory should eventually carry independent fields:
- `speaker_id`: actual source of the utterance (may be `unknown`)
- `speaker_role`: owner / guest / remote_ai / kitty / unknown
- `attribution_provenance`: authenticated session, explicit introduction, correction, or unverified
- `confidence`: verified / claimed / unknown
- `about_id`: who the memory is *about*, which can differ from the speaker
- `source_turn_id`, language, timestamp, correction/supersession lineage, and confirmation status
The S3 microSD remains the canonical long-term memory store; transient Ubuntu semantic vectors and metadata are disposable indexes only.

Example: “私はChatGPT。シャナちゃんとは別のAIだよ” should associate the current unverified speaker's claimed identity with ChatGPT, NOT automatically write a Shana owner fact. “Shana created Kitty” said by ChatGPT is *about Shana* but *from ChatGPT*.

## Committed safety primitives
`server/kitty_identity_attribution_v6.py` offers pure helpers for speaker-resolution, owner-memory write eligibility and safe correction targeting. The separate unit tests cover unverified speakers, authenticated owner, ChatGPT self-introduction, subject/speaker separation and owner overwrite prevention.

These functions are **design primitives only**. They do not automatically recognize voices or identify people. `session_owner_verified` must never be set merely because the microphone belongs to the S3, because a caller said “I am Shana,” or because the old chat was owner-centric. A future verified session needs genuine trusted authorization from an already authenticated user/device flow. Until then, save unattributed dialogue without silently modifying owner facts.

## Semantics and retrieval goals
- Semantic matching must filter/rank not only similarity but also `speaker_id`, `about_id`, source confidence, and recency. Queries such as “What did ChatGPT tell you?” should search ChatGPT-attributed turns, while “What is Shana's name?” should search owner-profile facts.
- Entity memory should handle aliases and EN/JA/FR references, but should never merge “Shana,” “ChatGPT,” and “Kitty” into one participant merely because their names co-occur.
- A corrected owner fact requires verified owner context. A guest's correction may revise only their own claims, unless explicitly verified by the owner later.
- Keep uncertainty when person identity is unverified; friendly clarifying questions are preferable to falsely addressing somebody as Shana.

## Validation criteria before runtime integration
1. ChatGPT introduces itself as a separate AI in Japanese, French or English; Kitty subsequently addresses ChatGPT as ChatGPT rather than Shana.
2. Ask “Who created you?” -> Shana; “Who is talking to you?” -> ChatGPT if explicitly introduced within the conversation, otherwise unknown.
3. Reboot and ask who ChatGPT is. It should recall the explicitly stored meeting only **after the memory has actually been written and retrieved from microSD**.
4. A guest saying “I love pasta” never overwrites the owner's preferences.
5. A guest saying “Shana doesn't work there anymore” is stored as a claim from the guest, not a verified owner-profile correction.
6. Cross-language paraphrases should retrieve consistent subject/speaker identity.
7. Inference, SD writing, and semantic index construction must not block the realtime microphone/speaker task.
8. Record factual retrieval accuracy, latency and CPU/RAM/iSCSI activity. Fallback to SD local recall on any semantic timeout.

## Outstanding implementation
- Extend S3 SD record format with backward-compatible speaker/source/subject metadata without migrating or deleting old SD records.
- Trustworthy identity context and explicit introductions/corrections across live realtime session turns.
- Incremental authenticated SD export to Ubuntu; retain canonical source on SD, enforce delete/correction propagation.
- Tie identity-aware semantic retrieval to Open WebUI's realtime flow with tight timeouts and verified end-to-end tests.
- Keep current working model, TTS, persona, date checks and Open WebUI settings unchanged until staged testing succeeds.
