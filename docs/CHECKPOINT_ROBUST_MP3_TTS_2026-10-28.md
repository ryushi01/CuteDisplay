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
