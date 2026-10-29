# Kitty temporal awareness — October 29, 2026

## Design
- S3 SNTP clock and user-selectable local timezone are authoritative for Kitty device requests. If the clock is unsynchronized, the firmware does not invent a date.
- Normal/delegated AI requests receive a small system message with local YYYY-MM-DD, English weekday, UTC offset, and a reminder not to confuse historical plans with confirmed completed activities.
- Realtime auth appends the same date context to the existing bounded `kitty_sd_memory` field. The opt-in refresh protocol updates it after local midnight when the matching Open WebUI extension is deployed; older gateways retain the connect-time date.
- A user plan explicitly referring to today/tomorrow/yesterday in English, French or Japanese is anchored to the **actual local date when written**. The key is `dated_plan_YYYY-MM-DD`; the value says `Plan for YYYY-MM-DD (completion not confirmed)`. These plans remain on the SD card after their date. A plan mentioned later with no clear date is left undated instead of guessing.
- Dates across DST boundaries use local calendar arithmetic, not an assumed fixed day-length.
- This is not a full natural-language date parser (e.g., next Friday, next month), and does not prove whether a plan actually happened. The existing per-date key currently represents only one consolidated plan per day, so multiple same-day plans need a later richer schema.

## Open WebUI browser chats
Open WebUI supports prompt placeholders `{{CURRENT_DATE}}`, `{{CURRENT_WEEKDAY}}`, `{{CURRENT_TIME}}`, `{{CURRENT_DATETIME}}` and (browser-side) `{{CURRENT_TIMEZONE}}`. Add the date and day placeholders to Kitty's **model system prompt** to enable date-aware regular chats. This is a model configuration step, not server deployment.
Suggested system prompt addition:

```text
Current local date: {{CURRENT_DATE}} ({{CURRENT_WEEKDAY}}).
Use the current date when interpreting today, yesterday, tomorrow, and past plans.
When a planned date is in the past, describe it as a past plan, not proof of completion.
Keep dated memories in historical context. Ask whether an activity happened if its outcome was never recorded.
Do not guess dates when the user's time zone or date is unknown.
```

Avoid inserting a second-by-second clock into all prompts: it can invalidate LLM prompt prefix caching unnecessarily.

## Validation
1. Verify combined S3 + C5 build, then check the device clock zone and NTP sync.
2. Tell Kitty 'I am going shopping tomorrow' on day D; check stored key `dated_plan_D+1`, reboot and ask again on D+1 and D+2.
3. Check yesterday's plan is recalled as a *plan that was scheduled*, not a completed event.
4. During a realtime call, check the date changes only on local day rollover; live refresh requires the guarded Open WebUI memory extension on the server.
5. Validate English, French and Japanese phrases and ensure no speech/audio latency regression.
6. Recovery: `checkpoint/2026-10-29-memory-v2-before-temporal`. `main` unchanged.
