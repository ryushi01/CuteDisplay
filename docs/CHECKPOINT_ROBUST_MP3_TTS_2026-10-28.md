# CuteDisplay checkpoint — Robust Qwen3-TTS + MP3 verified (2026-10-28)

## Status: production playback tested
User confirmed successful MP3 listening test, successful playback via Open WebUI after promotion, and successful service checks. This is an **infrastructure/TTS checkpoint**, not a new firmware or real-time voice implementation. Hardware-tested firmware fallback branches documented in the preceding handoff remain untouched.

## Verified deployment (2026-10-28)
| Component | Endpoint / runtime | Current behavior |
| --- | --- | --- |
| MacBook Qwen3-TTS | `10.5.5.224:8321` — launchd `local.kittychan.qwen3tts` | `server_robust:app`, `/api/tts`, custom voice model `mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit`, voice `ono_anna` |
| MacBook Kitty Realtime | port `8765` — launchd `local.kittychan.realtime` | Listener confirmed; broader conversation functionality not retested in this checkpoint |
| Ubuntu TTS adapter | port `8322` — systemd `kitty-tts.service` | OpenAI-compatible `/v1/audio/speech` → MacBook `/api/tts`; FFmpeg encodes requests for MP3 to **32 kbps mono, 24 kHz** |
| Ubuntu Open WebUI | port `8080` — Docker `open-webui` | MP3 playback successfully tested using speaker button; the public HTTPS Open WebUI route is used by CuteDisplay firmware |

The active production chain is **text → Open WebUI → Ubuntu TTS adapter → MacBook Qwen3-TTS waveform generation → WAV returned over LAN → Ubuntu FFmpeg MP3 encoding → Open WebUI → MP3 playback**. This is **not native MP3 model inference**; model speech generation remains the dominant latency cost. `response_format=mp3` is configured for the Open WebUI TTS request. WAV remains an option for other consumers.

## Bug investigated and remediation
Previously a long Open WebUI response produced an endless `uuuu` sound. MacBook TTS logs showed unexpectedly short segments (0.96s, 1.60s) and excessively long segments (28.80s, 26.88s). The earlier `server_fixed.py` split sentences but accepted any nonempty audio segment and returned HTTP 200.

A new `server_robust.py` was created by patching the sentence loop in `server_fixed.py`:
- Split input into sentences, synthesize each independently.
- Up to three attempts per sentence with small text/sampling changes on retries.
- Heuristic Japanese-character-dependent minimum/maximum duration, finite/sample peak/RMS checks, and low-level sustained-audio screening.
- Return HTTP 503 if a sentence fails all attempts instead of delivering obviously invalid audio.
- Keep a brief silence gap between accepted sentences.

These are **heuristics, not guaranteed humming detection, forced alignment, or intelligibility verification**. Repeated real conversation testing remains advisable.

## Local source-of-truth and rollback — important
**The actual working MacBook `server_robust.py` was not copied into this GitHub repository during this checkpoint.** It is local at:
`/Users/shanaderoose/qwen3-tts-mlx-demo/qwen3-tts-mlx-demo/server_robust.py`

Earlier local fallback: `server_fixed.py` and `server_fixed.working-20261028.py`. LaunchAgent plist: `~/Library/LaunchAgents/local.kittychan.qwen3tts.plist`; saved previous plist `local.kittychan.qwen3tts.plist.before-robust` if present. Plist runs `.venv/bin/python -m uvicorn server_robust:app --host 0.0.0.0 --port 8321`. Health `http://127.0.0.1:8321/api/status`.

Ubuntu adapter source is local to Ubuntu at `/opt/kitty-tts/adapter.py`; systemd environment `/etc/kitty-tts.env` contains the **secret API key** and must **never be committed**. Existing Ubuntu backup `/opt/kitty-tts/adapter.py.backup-20261028` and `adapter.py.pre-mp3-deploy`. Adapter remains responsible for MP3 conversion.

MacBook manual development TTS on port 8323 was stopped; Ubuntu development adapter on 8324 is not running. Production LaunchAgent was re-bootstrapped after it was found unloaded; it subsequently reported ready on port 8321 with PID 53090, running `server_robust:app`. The user confirmed Ubuntu service verification succeeded, including automatic startup.

### Maintenance / tests
MacBook:
```bash
launchctl print "gui/$(id -u)/local.kittychan.qwen3tts"
curl -fsS http://127.0.0.1:8321/api/status
lsof -nP -iTCP:8321 -sTCP:LISTEN
tail -80 ~/Library/Logs/kitty-tts.log
```
Ubuntu:
```bash
systemctl is-active kitty-tts.service
systemctl is-enabled kitty-tts.service
curl -fsS http://127.0.0.1:8322/health
docker ps --filter name=open-webui
```

## Next work
1. **Back up the exact deployed `server_robust.py` and sanitized `adapter.py` to the repo**, only after retrieving source from the hosts and confirming it contains no tokens, passwords, local secrets, or credentials. This checkpoint documents production behavior but does not reproduce the source files.
2. Preserve main's firmware behavior: C5 face, UART recovery, hold-to-talk fallback, MP3 decode, iPhone app, I2S pinout. Immutable hardware-tested stable branches remain intact.
3. Continue feature work on a separate real-time voice branch after verifying actual Open WebUI voice protocol; implement incremental speech/playback and interruption in stages. Do **not** assume sentence streaming or native MP3 model generation is already implemented.
4. Test multi-language sustained conversations and measure text-to-first-audio; monitor unusual TTS segments and HTTP 503.

## Follow-up checkpoint — bounded generation, extended conversation test (2026-10-28)

**Latest observed user acceptance:** User reports a successful **long conversation with Kitty-chan** after switching the MacBook LaunchAgent to `server_bounded:app`. This is a meaningful functional test, not a proof that all intermittent defects are eliminated. The earlier humming, increased latency, dropped final speech and Open WebUI realtime bridge `ValueError` have occurred on previous configurations and must remain documented as regression risks.

### Current production configuration supersedes earlier sections
- MacBook LaunchAgent `local.kittychan.qwen3tts` now launches `.venv/bin/python -m uvicorn server_bounded:app --host 0.0.0.0 --port 8321`. User's process listing confirmed `server_bounded:app` running as PID 53811. The immediate health response showed `custom.status=loading` during startup; a subsequent successful extended conversation is evidence of operation. **Do not confuse `loading` with an immediate boot failure.**
- `server_bounded.py` was copied from `server_robust.py` locally and changes sentence-level `max_tokens` from `min(4096, 300 + len(text)*6)` to `min(600, max(100, 48 + len(text)*5))`. Its syntax was verified; two standalone MP3 sample generation requests returned HTTP 200, and the user later reported a long successful conversation after deployment.
- The base inherited sentence splitting, up to three retries, duration/audio-signal heuristics, 85% minimum-duration tolerance, and a modification to discard chunks flagged by `_is_hum` rather than yielding them back. These heuristics can discard genuine quiet speech or still admit humming and must be monitored.
- Ubuntu `/opt/kitty-tts/adapter.py` was updated to pass `temperature=0.7`, `top_k=40`, `top_p=0.9`, `repetition_penalty=1.05` to MacBook TTS. The adapter continues to encode 32 kbps MP3 for Open WebUI. These are user-tested settings, not a guaranteed fix.
- Prior testing demonstrated generated runaway segments of ~20–35 s for much shorter Japanese text, and entire TTS requests sometimes returned 503 when sentence retries failed; the Ubuntu adapter could then return 502 and the Open WebUI realtime bridge logged `Bridge closed: error_type=ValueError`. Later bounded generation is intended to reduce this waste, but no proof of error-free long-term operation is available.
- MacBook realtime service `local.kittychan.realtime` (8765) remains distinct from Open WebUI's own realtime voice bridge. Do not equate successful Open WebUI calls with tested CuteDisplay firmware real-time voice.

### Preserve and reproduce
- **Deployed source not yet stored in GitHub:** exact current `/Users/shanaderoose/qwen3-tts-mlx-demo/qwen3-tts-mlx-demo/server_bounded.py` (and prior `server_robust.py`) plus sanitized Ubuntu adapter remain on the hosts. This GitHub change is a documentation checkpoint, **not a full reproducible source archive**.
- Local MacBook backups include `server_robust.before-duration-tolerance.py`, `server_robust.before-hum-buffer-fix.py`, `server_fixed.working-20261028.py`, and the previous LaunchAgent plist backup `local.kittychan.qwen3tts.plist.before-bounded` when created. Keep all local files; confirm their presence before rollback.
- Avoid committing API keys, environment files, credentials, or personal conversation recordings.
- Mac health: `curl -fsS http://127.0.0.1:8321/api/status`; service: `launchctl print "gui/$(id -u)/local.kittychan.qwen3tts"`. Ubuntu: `systemctl is-active kitty-tts.service`, `curl -fsS http://127.0.0.1:8322/health`.
- Do not change hardware-tested S3/C5 firmware, release workflow, or stable rollback branches based solely on this server-side TTS checkpoint.

### Next work
1. Repeated voice calls with new uncached text; validate full speech, first-sentence latency, conversation continuity, and correct final sentence. Collect event-timed logs only if the bug recurs.
2. Obtain and sanitize the **exact deployed** `server_bounded.py` and adapter source and commit them on a follow-up source checkpoint; do not reconstruct source from this documentation.
3. Only then plan lower-latency incremental TTS and firmware real-time voice integration; preserve the functioning MP3 pipeline.
