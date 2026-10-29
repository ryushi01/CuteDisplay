# Kitty local calendar awareness — 2026-10-29

Base: `feature/memory-v2-lifecycle`, checkpoint `checkpoint/2026-10-29-before-calendar-awareness`. Production `main` unchanged.

- The S3 already synchronizes UTC by SNTP and stores a configurable POSIX local timezone (default JST).
- Every ordinary AI request now includes the **current local calendar date, day of week, time, timezone and interpretation of today/yesterday** as a system context message; no network time API is added.
- Realtime auth sends the same local date with the compact device-memory snapshot, within the existing 850-byte server limit.
- On negotiated `kitty.memory.refresh` support, the firmware refreshes date context at the next safe idle turn following a local midnight rollover without disconnecting/restarting the call.
- Today/tomorrow upcoming plans expire from *active future-plan recall* at the relevant **local midnight**, not after a rolling 24/48 hours. Historical SD conversations remain intact. Expiry means the planned time has passed, **not** that the user completed the plan.
- Without the optional Open WebUI live-refresh extension, a realtime session still receives the date only on connection. Start a new Call session to update it after midnight; ordinary S3 AI prompts always refresh per request.
- The local timezone is set on the S3. Open WebUI browser chats by other clients do **not** automatically receive this context. A separate server-side time injection would be needed for every browser chat.
- Relative wording like `next Friday`, explicit dates, recurring appointments, and cross-midnight long activities are not yet covered by the simple expiry classifier.
- Confirm C5+S3 combined CI and hardware acceptance before merging.

Acceptance: `system status` confirms NTP; ask Kitty `What day and date is today?`, including Japanese and French; record `tomorrow I will go to the shop`; verify the plan is future today, current tomorrow, historical after the next midnight; confirm same-session refresh with the server patch installed and barge-in/audio remains stable.

## Standard Open WebUI browser chat (no custom patch required)

In **Workspace > Models**, edit Kitty's model **System Prompt** (append to the existing Kitty persona, do not replace it). Open WebUI documents system-prompt placeholders which are expanded each request:

```text
Temporal context: Today is {{CURRENT_WEEKDAY}}, {{CURRENT_DATE}}.
User timezone: {{CURRENT_TIMEZONE}}.
Understand today, tomorrow and yesterday relative to the user's local calendar day.
A plan scheduled for yesterday is in the past, not still upcoming.
Do not assume the plan was completed unless the user said so.
Preserve long-term preferences and routines across days; consider dates when recalling plans.
Answer in the language used by the user (English, French, Japanese, or others).
```

Prefer the date and weekday rather than `{{CURRENT_TIME}}` or `{{CURRENT_DATETIME}}` when minute-level accuracy is not needed: changing system-prompt text every second can reduce Ollama prefix-cache reuse. Timezone variables are browser-provided; non-browser API clients may not substitute them, so the S3's explicit NTP context remains necessary.

This is a **manual Open WebUI model setting**; nothing has been automatically changed on the running server.
