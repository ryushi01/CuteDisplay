# Kitty-chan realtime call continuity checkpoint — 2026-10-28

## Status
**Production hotfix deployed; verification pending.** The user applied two changes to the MacBook's active `server_bounded.py`, passed Python compilation, restarted the `local.kittychan.qwen3tts` LaunchAgent, and confirmed `QWEN3-TTS READY`. A subsequent long voice-call test after these **two** hotfixes has **not yet been reported**; do not label them proven stable.

## Root cause observed in logs
- Open WebUI realtime voice calls disconnected with `Bridge closed ... error_type=ValueError` at 2026-10-28 06:38:06, 06:41:51 and 06:43:18 UTC.
- The MacBook `speech-to-speech` realtime process on port 8765 successfully performed Whisper STT and Ollama chat completion, but downstream TTS returned `502 Bad Gateway`, raised `SpeechRequestError`, marked the turn `status=failed`, and the client session ended.
- On MacBook Qwen3-TTS port 8321, sentence-level heuristic validation exhausted three attempts (e.g. repeated ~0.90–0.96 s audio for a sentence) and raised HTTP 503; Ubuntu `kitty-tts.service` on port 8322 propagated that as HTTP 502 to Open WebUI or realtime clients.
- This supports the error propagation path **TTS sentence rejection 503 -> adapter 502 -> realtime response failed -> call termination**. Other disconnection mechanisms are not ruled out.

## Hotfix applied on MacBook, confirmed by user
Local project: `/Users/shanaderoose/qwen3-tts-mlx-demo/qwen3-tts-mlx-demo/`
Active module: `server_bounded:app` via `local.kittychan.qwen3tts`, `0.0.0.0:8321`.
1. In sentence loop of `_synthesize`, replace the `raise HTTPException(503, ... failed validation after 3 attempts)` branch when `part is None` with a warning and `continue`. This retains successful segments but skips an invalid sentence.
2. Before `np.concatenate(parts)`, guard `if not parts`: create `np.zeros(int(sr * 0.35), dtype=np.float32)`; otherwise concatenate valid parts. This returns a short silent valid WAV if all candidate sentences are rejected.
3. User's tool output: `Call-stability fix applied.`, backup `server_bounded.before-call-stability-fix.py`, `Empty-audio safeguard applied.`, Python `py_compile` completed, LaunchAgent restarted, health `QWEN3-TTS READY`.

**Tradeoffs:** A skipped sentence means missing spoken content. Fully failed requests return silence rather than speech. These changes avoid validation-induced 503 but **do not address** model runtime exceptions, network errors, disconnected sockets, or other 502/503 causes. The heuristic validator still may mistake legitimate speech for invalid audio.

## Architecture retained
- MacBook speech-to-speech v1.1.0 server on port 8765, managed by `local.kittychan.realtime`, script `~/kitty-realtime/start-kitty.sh`: Silero VAD / Smart Turn, Whisper STT, Ollama chat-completions, OpenAI-compatible TTS via Ubuntu.
- MacBook Qwen3-TTS CustomVoice model `mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit` (speaker `ono_anna`), bounded `max_tokens=min(600,max(100,48+len(text)*5))`, generation heuristics and retries.
- Ubuntu `/opt/kitty-tts/adapter.py` at port 8322 translates speech requests to MacBook WAV generator, encoding MP3 at **32 kbps mono, 24 kHz** for Open WebUI where requested; some Mac realtime requests request WAV, not MP3.
- Open WebUI Docker realtime calls and speech cache cleanup hourly with a 24h retention for `/app/backend/data/cache/audio/speech`. Mac LaunchAgent hourly cleanup configured for a dedicated generated-audio directory (no evidence current TTS writes to that directory).
- S3/C5 firmware and hardware-tested rollback branches **unchanged** by this checkpoint.

## Recovery and verification
- MacBook rollback file: `server_bounded.before-call-stability-fix.py` (created before the first hotfix). Restore it to `server_bounded.py` only deliberately, then restart `local.kittychan.qwen3tts`.
- Confirm service: `curl -fsS http://127.0.0.1:8321/api/status`, `launchctl print "gui/$(id -u)/local.kittychan.qwen3tts"`.
- Diagnostics: `tail -100 ~/Library/Logs/kitty-realtime-error.log`, `tail -100 ~/Library/Logs/kitty-tts.log`; Ubuntu `sudo journalctl -u kitty-tts.service --since '10 minutes ago'`, `sudo docker logs --since 10m open-webui`.
- Next acceptance: sustained realtime call with multiple Japanese/French responses; watch for `TTS WARNING` logs, missing sentences, new 502/503, and disconnected sessions; test interruption and latency. Do not merge uncertain hardware/display font work with this voice-service checkpoint.

## Source archive limitation
This GitHub checkpoint documents the exact *observed* hotfix operations; **deployed `server_bounded.py` and Ubuntu `adapter.py` are not included in the GitHub repository**. They reside on the MacBook and Ubuntu host and require a sanitized copy for reproducible code backup. Never commit credentials, tokens, runtime environment files, or user voice recordings.
