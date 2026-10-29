# Kitty SD Brain v4 + personality — 2026-10-29

## Branch and recovery
- Experimental branch: `feature/kitty-sd-brain-v4-persona`
- Previous working code checkpoint: `checkpoint/2026-10-29-sd-brain-v3`
- Production `main` unchanged. Never format the microSD for this update.

## SD is durable memory; PSRAM is a cache
- Working facts enlarged from 256 to 512 entries using PSRAM. Durable current facts remain in `/kitty/facts.tsv` plus its backup, with metadata in a separate SD sidecar for backwards compatibility.
- Conversations live in `/kitty/conversations.tsv` and `/kitty/memory.idx`; long archives beyond the 150,000-row PSRAM index window now get an older-row pass through the SD index on the low-priority worker.
- All dated plans remain in `/kitty/dated_plans.tsv`; the entire archive is scanned on the low-priority worker for temporal retrieval rather than truncating lookup to a 16 KiB tail.
- SD writes, history reads and semantic-topic ranking are never on the I2S callback. Large archives can still take longer than the 25ms retrieval wait used by regular AI requests. Never claim every archive item is instantly recalled.
- Search is topic-expansion and hashed term overlap across the full archive, **not vector-embedding semantic search**. A truly multilingual unrestricted semantic search requires embeddings or an LLM reranker, likely on the existing Ubuntu server, with SD-owned storage and a bounded off-device query path. This is not yet deployed.

## Calendar and chronology
- Existing EN/FR/JA relative date recognition, ISO dates, weekday plans and local NTP date context are retained.
- Plan statements preserve the intended date and an outcome-unconfirmed label; old plans are historical and never automatically treated as completed.
- This remains a bounded grammar, not a fully general multilingual natural-language calendar parser. For ambiguous dates Kitty should ask a brief clarifying question instead of fabricating one.

## Onee-san conversational personality
- On-device normal/delegated AI system context and opt-in realtime Open WebUI prompt patch now use a playful, affectionate and witty Kitty-chan オネエ voice, multilingual Japanese/English/French.
- Curiosity: sometimes a single relevant follow-up, not a question after every answer.
- Occasionally introduce a connected topic during a comfortable lull; do not derail emotional, serious or technical exchanges.
- Preserve privacy and never claim that a remembered plan happened just because its date passed.
- Device-side prompt is committed in firmware. The realtime server patch is committed in GitHub but **requires separately deploying the guarded Open WebUI image**; source commits do not change the live Ubuntu service. Do not override the user's existing longer persona prompt blindly; review before applying.

## Testing and rollout
1. Confirm combined S3+C5 GitHub Actions completion at the final commit; compile alone does not prove runtime safety.
2. Check `memory status`, SD file preservation, and power-cycle recall.
3. Fill >256 distinct facts; verify 512 working slots and old facts still on SD.
4. Test hundreds of dated plans; historical scan should return relevant records without I2S dropout.
5. Validate Japanese, English and French conversation style and memory after a reboot; test curious follow-ups and optional topic transitions.
6. Validate Open WebUI realtime prompt compatibility and authentication in a staged copy before deploying; keep the exact prior container image/volume backup.
7. `system status` during audio for heap low water, stack headroom and mic/speaker drops. Do not merge to main until acceptable.

## Not complete
- An unbounded vector-index semantic retrieval engine and comprehensive NLP calendar parser have **not** been implemented in this branch.
- The running Open WebUI server has **not** been updated.
