# Iris

Iris is a self-hosted safety monitor for kids' WhatsApp. It watches the chats and groups of one or more
kids' numbers through [OpenWA](https://github.com/rmyndharis/OpenWA), classifies **text, voice notes,
audio, images and video** for harmful content, and alerts a parent **over WhatsApp** with the kid, the chat,
the sender and the quoted message.

It is built for mixed Hebrew and English chats (nothing is hardcoded to a language), runs as a single Docker
container (amd64 and arm64), and uses free or low-cost models wherever possible.

> **Read this first.** Monitoring a child's messages is a sensitive decision. Use Iris openly and only for
> children you are responsible for, and make sure you are allowed to do so where you live. Iris is
> read-only: it never replies or interacts in a chat. It only sends alerts to the number you choose.

![Dashboard](assets/screenshots/dashboard.png)

## Contents

- [Features](#features)
- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Installation](#installation)
- [Connecting OpenWA](#connecting-openwa)
- [Configuration](#configuration)
- [Using the portal](#using-the-portal)
- [API](#api)
- [Metrics](#metrics)
- [Privacy and security](#privacy-and-security)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [License](#license)

## Features

- **One webhook per number.** Each kid's WhatsApp session gets its own signed webhook; one number is one kid.
- **Text** is checked with OpenAI Moderation (a free endpoint).
- **Images and stickers** (with their caption) go through multimodal moderation.
- **Voice notes, audio and video** are transcribed (OpenAI or Cloudflare Workers AI, your choice), then the
  transcript is moderated.
- **Context-aware second look.** A message that is borderline is re-checked together with the previous
  messages in the same chat. If it is still unclear it lands in a **review queue** instead of a guess.
- **WhatsApp alerts** with the kid, chat, sender, category, score, time and the quoted message. A per-chat
  cooldown avoids floods and the next alert says how many were held back.
- **Both sessions monitored?** A message between two monitored kids is stored once, with both kids on it, and
  produces one alert.
- **Edits and deletes are kept.** A message the sender deletes for everyone stays in Iris with a red border
  and a "Deleted for everyone" label. An edited message gets an **Edited** marker, and the original wording
  and every earlier version stay available as an edit history. Iris tells you on WhatsApp when the message of
  an alert you already received is edited or deleted.
- **Try it page.** Type a message, see how Iris scores and classifies it, and adjust the thresholds with an
  instant preview before saving them.
- **SQLite, PostgreSQL or MySQL.** SQLite is the default and needs nothing; pick a database server under
  **Settings > Database** and copy your data across with one button.
- **Searchable archive** (Hebrew and English; SQLite full-text, or substring search on PostgreSQL and MySQL) with filters, a chat-style context view and
  match highlighting.
- **A modern, responsive portal.** A sidebar on desktop, an icon rail on tablets, and a bottom tab bar on
  phones, so an alert link opens into something you can use one-handed. Light and dark themes follow your
  system, and the whole portal passes an automated accessibility scan (keyboard, contrast, screen readers).
- **Sexual content safety rule.** Content involving minors, or sexual imagery, is withheld entirely: it is
  not stored, not searchable, not shown and not forwarded. The alert says to review the chat directly.
- **Self-hosted and private.** Secrets are encrypted at rest, logs never contain message text, media is
  deleted after processing, and old data is removed automatically.
- Prometheus metrics, a REST API with interactive docs, and a multi-arch image.

## How it works

```mermaid
flowchart LR
    OW["OpenWA<br/>(one session per kid)"] -- "POST /webhooks/&lt;token&gt;" --> IN
    subgraph iris ["iris container"]
        IN["Ingest<br/>validate, dedupe, store, enqueue"] --> Q[("Job queue<br/>SQLite")]
        Q --> W["Workers"]
        W --> M["Media<br/>download, ffmpeg"]
        M --> T["Transcription<br/>OpenAI / Cloudflare"]
        W --> C["Classification<br/>moderation, then context"]
        T --> C
        C --> A["Alert service<br/>cooldown, redaction"]
        A -- "send-text" --> OW
        UI["Portal + REST API"] --- DB[("SQLite, PostgreSQL<br/>or MySQL")]
    end
    A -. "WhatsApp message" .-> P(("Parent"))
```

The webhook handler never calls an external API: it validates, stores, queues and answers `200`. All slow
work (downloading media, transcribing, moderating, alerting) happens in worker tasks inside the same process.
Iris runs as **one process on purpose**: the queue and its locks assume it.

## Requirements

- Docker, on amd64 or arm64.
- An **OpenWA 0.24.0 or newer** server with one running session per monitored number. Older versions cannot
  download media that the session *receives* (see [Troubleshooting](#troubleshooting)).
- An **OpenAI API key** for moderation (the moderation endpoint is free but rate limited). It is also used
  for transcription unless you choose Cloudflare.
- Optional: a Cloudflare account ID and API token for Workers AI transcription.
- A **public hostname or IP for Iris** that OpenWA can reach. OpenWA refuses to send webhooks to private
  network addresses (`Destination address is not allowed`), so a LAN IP will not work: use a reverse proxy or
  tunnel and expose only `/webhooks/*` if you can.

## Installation

### Docker Compose

```yaml
services:
  iris:
    image: techblog/iris:latest
    ports: ["8080:8080"]
    volumes:
      - iris-data:/data        # SQLite database; a named volume keeps non-root ownership
    environment:
      IRIS_SECRET_KEY: ""            # openssl rand -base64 32
      IRIS_ADMIN_USERNAME: admin     # first run only
      IRIS_ADMIN_PASSWORD: ""        # first run only
      IRIS_PUBLIC_BASE_URL: https://iris.example.com   # what OpenWA can reach
    restart: unless-stopped
volumes:
  iris-data:
```

```bash
openssl rand -base64 32      # paste into IRIS_SECRET_KEY, and back it up
docker compose up -d
```

Open the portal on port 8080 and sign in with the admin credentials. They are used only to create the first
account; change the password under **Settings → Account**.

![Login](assets/screenshots/login.png)

> **Back up `IRIS_SECRET_KEY`.** It encrypts every stored secret (API keys). Lose it and you must re-enter them.

The container runs as a non-root user (uid 10001), applies database migrations on start, and has a health
check on `/api/health`.

### Build from source

```bash
uv sync                                    # Python 3.12
cd web && npm ci && npm run build && cd .. # builds the portal into app/static
IRIS_SECRET_KEY=... IRIS_PUBLIC_BASE_URL=http://localhost:8080 \
IRIS_ADMIN_USERNAME=admin IRIS_ADMIN_PASSWORD=change-me IRIS_DATA_DIR=./data \
  uv run alembic upgrade head && uv run uvicorn app.main:app --port 8080
```

`ffmpeg` and `ffprobe` must be installed (the Docker image includes them).

## Connecting OpenWA

1. In the portal go to **Phones → Add a phone** and enter the child's name, your OpenWA address, the
   OpenWA **session ID** (the full UUID, not the name) and an OpenWA API key that can use that session.
2. Click **Register in OpenWA**. Iris subscribes a webhook to `message.received`, `message.sent`,
   `message.edited` and `message.revoked` and sets a signing secret, so deliveries are verified with an HMAC.
   Running it again **updates** the webhook already pointing at Iris (it keeps any other events you added),
   so it never creates a duplicate. Phones registered before edits and deletes were supported need one more click. If registration says the
   destination is not allowed, your `IRIS_PUBLIC_BASE_URL` is a private address (see Requirements).
   You can also paste the shown URL (`https://…/webhooks/<token>`) into OpenWA by hand.
3. Repeat for every number you monitor.
4. Under **Settings → Alerts** choose the instance that **sends** alerts, enter the parent's number
   (international format, digits only, e.g. `972501234567`) and press **Test**. A real WhatsApp message is
   sent using the values you typed, before you save.

![Settings: alerts](assets/screenshots/settings-alerts.png)

![Phones](assets/screenshots/instances.png)

**New webhook address** cuts the old URL off immediately; register the new one afterwards. Each phone shows
when it last received a message, or **Nothing received yet**, and the Home screen flags phones that never
have. Use the switch to pause watching a phone without removing it.

## Configuration

### Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `IRIS_SECRET_KEY` | yes | | 32 bytes, base64. Encrypts secrets at rest and derives session and webhook signing keys. Iris will not start without it. |
| `IRIS_PUBLIC_BASE_URL` | yes | | Externally reachable base URL, used to build webhook URLs and alert links. |
| `IRIS_ADMIN_USERNAME` | first run | | Initial admin user. |
| `IRIS_ADMIN_PASSWORD` | first run | | Initial admin password (stored hashed with argon2; ignored afterwards). |
| `IRIS_DATA_DIR` | no | `/data` | SQLite database (unless another database is chosen), the saved database choice and temporary media. |
| `IRIS_DATABASE_URL` | no | | `postgresql://user:password@host:5432/db` or `mysql://user:password@host:3306/db` (or `sqlite:///path`). Overrides the choice made in Settings, which then becomes read only. Add `?ssl=true` for TLS. |
| `IRIS_PORT` | no | `8080` | Listening port. |
| `IRIS_WORKERS` | no | `3` | Concurrent job workers. |
| `IRIS_LOG_LEVEL` | no | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `IRIS_LOG_JSON` | no | `false` | JSON log lines. |
| `IRIS_METRICS_TOKEN` | no | unset | If set, `/metrics` requires `Authorization: Bearer <token>`. |
| `IRIS_FORWARDED_ALLOW_IPS` | no | `127.0.0.1` | Your reverse proxy's IP, so the login rate limit sees real client addresses. |

### Choosing a database

By default Iris keeps everything in one **SQLite** file in its data folder. To use a database server instead,
open **Settings > Database**:

![Database settings](assets/screenshots/database-postgres.png)

1. Create an **empty** database and a user for Iris on your PostgreSQL or MySQL server. On MySQL create the
   database with the `utf8mb4` character set.
2. Pick the type, enter the host, port, database name, user and password (turn on **Use TLS** if the server
   supports it) and press **Test connection**. Iris tells you whether it can reach the server, whether the login
   works and whether the database is empty.
3. Press **Save**. The choice is stored in `database.json` in the data folder (the password is encrypted with
   `IRIS_SECRET_KEY`) and Iris uses it from the **next start**. Restart Iris, for Docker `docker restart iris`.
4. To keep your history, press **Copy my data to PostgreSQL** (or MySQL) *before* restarting. It copies phones,
   settings, messages, alerts and the edit history into the empty database, checks the row counts, and leaves the
   current database untouched, so the old SQLite file is a backup. Messages that arrive while it copies are not
   included, so copy when it is quiet and restart right after.

**Use SQLite again** forgets the saved choice. If `IRIS_DATABASE_URL` is set the page only shows what is in use,
because the variable wins.

Notes:

- Only one Iris process may use a database (the job queue and locks live in that process), whichever database it is.
- Message search on PostgreSQL and MySQL matches any part of a word and ignores case, and works for Hebrew and
  English; on SQLite it uses the full-text index, which matches the start of words. The results page looks the same.
- Iris creates its tables itself (migrations run at start). It never creates databases or users.
- A different `IRIS_SECRET_KEY` cannot read the saved database password or the encrypted settings.

![Database settings in dark mode](assets/screenshots/database-postgres-dark.png)

### Settings (in the portal)

Everything else is edited under **Settings** and stored in the database. Secrets are write-only: the API and
UI only ever say whether one is set.

| Tab | Setting | Default |
|---|---|---|
| Providers | OpenAI API key | |
| Providers | Transcription provider (`openai` or `cloudflare`) | `openai` |
| Providers | OpenAI transcription model | `gpt-4o-mini-transcribe` (or `whisper-1`) |
| Providers | Cloudflare account ID, API token, model | `@cf/openai/whisper-large-v3-turbo` |
| Classification | Moderation model | `omni-moderation-latest` |
| Classification | Per-category thresholds (low and high) | see below |
| Classification | Context window / max age | 8 messages / 6 hours |
| Alerts | Sender instance, recipient, cooldown, time zone | cooldown 10 min, `Asia/Jerusalem` |
| Alerts | Also alert on items needing review | off |
| Alerts | Tell me when an alerted message is edited or deleted | on |
| Scope | Monitor messages sent by the kid, direct chats, groups | all on |
| Retention | Keep messages / alerts | 90 / 365 days |

Switching the transcription provider takes effect immediately, with no restart.

![Settings: providers](assets/screenshots/settings-providers.png)

![Settings: classification](assets/screenshots/settings-classification.png)

**Thresholds.** For each moderation category a score at or above **high** is harmful; between **low** and
**high** it is inconclusive and gets the context check; below **low** it is safe. Defaults are strictest for
`sexual/minors` (0.05 / 0.30) and self-harm (0.10 / 0.40), and loosest for general harassment, hate, illicit
and violence (0.20 / 0.70). Iris decides from the category scores, not from the API's own `flagged` flag.

## Using the portal

### Home

![Home](assets/screenshots/dashboard.png)

The **iris ring** answers the first question: all violet means all quiet; coral arcs are alerts waiting for
you and saffron arcs are messages Iris could not decide. Below it, **Needs attention** lists everything that
needs you or needs fixing (unread alerts, items to review, undelivered alerts, failed jobs, phones that never
reported) with a button for each, and the **activity chart** shows 14 days of messages by verdict. Everything
refreshes about every minute. The chart is also available as a table.

### Alerts

![Alerts](assets/screenshots/alerts.png)

Each alert shows the kid, chat, sender, categories with scores, the quote and whether it was delivered. Open
one to see how Iris decided, jump to the message **in its conversation**, **mark it as seen** or **dismiss**
it, or **send it again** if delivery failed.

![Alert detail](assets/screenshots/alert-detail.png)

The WhatsApp alert looks like this:

```
⚠️ Iris alert
Kid: Noa, Dan
Chat: Class 6B (group)
From: Yonatan
Category: harassment (0.98)
Time: 06/10 17:14

"You are a worthless idiot, nobody likes you, just disappear"

Open: https://iris.example.com/alerts/12?s=…
```

Voice-note quotes are prefixed with 🎤 and image, sticker and video captions with 🖼️. The signed link at the end lets Iris
recognise its own alerts if they come back through a monitored number, and it cannot be copied onto
different text.

### Messages and context

![Message search](assets/screenshots/messages-search.png)

Search matches words and prefixes in messages **and transcripts**, in Hebrew and English, with filters for
kid, chat, sender, type, verdict and dates. Open a message to see the surrounding chat with the message
highlighted and its classifications.

![Message in context](assets/screenshots/message-context.png)

### Review queue

![Review queue](assets/screenshots/review.png)

Messages that stayed inconclusive even with the surrounding chat wait here. **Mark safe** closes them;
**Mark harmful** creates an alert.

### Edited and deleted messages

![Messages marked as edited and deleted](assets/screenshots/messages-changes.png)

When OpenWA reports that a message was **deleted for everyone**, Iris keeps it, draws a red border around it
and adds **Deleted for everyone** (in words as well as colour). The sender removed it from the chat, but you
can still read it here, and an alert for it stays.

![A deleted message in its conversation](assets/screenshots/message-revoked.png)

An **edited** message shows an **Edited** marker. Open it in the conversation to see the **edit history**:
the current text, every earlier version, and the original wording with when it was sent and replaced.

![Edit history](assets/screenshots/message-edit-history.png)

How Iris treats a change:

- The edited text is checked again and search finds the new wording. The **verdict never improves because of
  an edit**: a message that was harmful or in review keeps that verdict, so editing something into a harmless
  sentence does not hide it. A message that becomes harmful through an edit raises a normal alert.
- Content that was withheld (see the safety rule) is never copied into the history, and withholding a message
  also clears its earlier versions.
- With **Tell me when an alerted message is edited or deleted** on, an alert you already received gets a short
  WhatsApp follow-up (the kid, chat, sender and a link). It never repeats the message text.
- An edit or delete that reaches Iris before the original message was stored is ignored. WhatsApp does not say
  what an edit replaced, so the history holds what Iris saw; the edit time is when Iris received it.

| Phone | Dark mode |
|---|---|
| ![Edit history on a phone](assets/screenshots/phone-edit-history.png) | ![A deleted message in dark mode](assets/screenshots/message-revoked-dark.png) |
### Try it

![Try it](assets/screenshots/try-it.png)

Use **Try it** to tune the [thresholds](#settings-in-the-portal) without waiting for a real message. Type
some text, optionally add earlier lines from the chat (one per line, oldest first) and press **Check**. Iris
asks OpenAI Moderation once and shows the score for every category, the band each one lands in, and the final
verdict: fine, needs a look (review queue) or harmful (alert).

Then change the **Needs a look** and **Harmful** values on any row: the bands and the verdict update at once,
without another request. The orange and red ticks on each bar mark the current thresholds. **Save these
thresholds** stores them (only the rows that differ from the defaults); **Reset to saved** drops the preview.
With earlier lines filled in, Iris also scores the second look, exactly like the real pipeline does for an
unclear message.

The text you check is sent to OpenAI for moderation and is **not stored or logged** by Iris. It never appears
in Messages, Alerts or the review queue. Checks are limited to 30 per 5 minutes.

| Phone | Dark mode |
|---|---|
| ![Try it on a phone](assets/screenshots/phone-try-it.png) | ![Try it in dark mode](assets/screenshots/try-it-dark.png) |

### Chats, instances, jobs

![Chats](assets/screenshots/chats.png)

![Jobs](assets/screenshots/jobs.png)

**Jobs** lists work that failed, with the reason, and a Retry button. A message that failed shows `failed`
and its reason in the message list (it is never silently shown as pending).

### On your phone

The portal is built for phones first: alert links from WhatsApp open straight into it. On a phone the
sidebar becomes a bottom tab bar (Home, Alerts, Review, Messages and a **More** sheet for Chats, Phones, Jobs,
Settings, the theme and sign out), filters tuck behind one **Filters** button, and every control is a
comfortable touch target.

| | | |
|---|---|---|
| ![Home on a phone](assets/screenshots/phone-dashboard.png) | ![Alerts on a phone](assets/screenshots/phone-alerts.png) | ![The More sheet](assets/screenshots/phone-more.png) |
| ![Filters sheet](assets/screenshots/phone-filters.png) | ![Review in dark mode](assets/screenshots/phone-review-dark.png) | |

### Light and dark

The portal follows your system's light or dark preference. Change it from the account menu (bottom of the
sidebar) or the **More** sheet: **System**, **Light** or **Dark**. The choice is remembered in the browser.

![Dashboard in dark mode](assets/screenshots/dashboard-dark.png)

![Alerts in dark mode](assets/screenshots/alerts-dark.png)

## API

All endpoints are under `/api`, return JSON, and need the session cookie from `POST /api/auth/login`,
except `/api/auth/login`, `/api/health` and `/api/version`. Interactive OpenAPI docs are at **`/api/docs`** and the schema at
`/api/openapi.json`, both behind the login.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/auth/login`, `/api/auth/logout`, `/api/auth/password` | Session login (HttpOnly, SameSite=Strict, 7 days; 5 failures per 15 minutes per IP), logout, change password |
| GET | `/api/auth/me` | The signed-in user (401 when not signed in) |
| GET | `/api/health`, `/api/version` | Liveness (database and workers), version |
| GET | `/api/stats` | Dashboard numbers |
| GET | `/api/messages` | Search: `q`, `instance_id`, `chat_id`, `sender`, `type`, `verdict`, `from`, `to`, `page`, `page_size` (max 100) |
| GET | `/api/messages/{id}`, `/api/messages/{id}/context` | One message with classifications; surrounding messages |
| POST | `/api/messages/{id}/reprocess` | Re-queue classification (not for redacted messages) |
| GET | `/api/alerts`, `/api/alerts/{id}` | List with filters (`status`, `delivery_status`, `instance_id`, `chat_id`, `category`, `from`, `to`, `page`, `page_size`); detail |
| PATCH | `/api/alerts/{id}` | Set status to `new`, `acknowledged` or `dismissed` |
| POST | `/api/alerts/{id}/resend` | Send the alert again (ignores the cooldown) |
| GET, POST | `/api/review`, `/api/review/{message_id}` | Review queue; resolve as `safe` or `harmful` |
| GET | `/api/chats` | Known chats with kids and counts |
| GET/POST/PATCH/DELETE | `/api/instances[/{id}]` | Manage monitored numbers (API keys are never returned) |
| POST | `/api/instances/{id}/rotate-token`, `/register-webhook` | Rotate the webhook token; register it in OpenWA |
| GET, PUT | `/api/settings` | Read and write settings (thresholds are the key `classification.thresholds`) |
| GET | `/api/settings/thresholds` | Effective per-category thresholds next to their defaults (read-only) |
| POST | `/api/settings/test/{openai\|cloudflare\|alert}` | Test a provider with the values entered |
| POST | `/api/classify/test` | Score typed `text` (max 4000 chars) with optional earlier `context` lines (max 20); nothing is stored; 30 per 5 minutes |
| GET, PUT, DELETE | `/api/database` | Which database runs and which is saved for the next start (never the password); save a choice (409 when `IRIS_DATABASE_URL` is set); go back to SQLite |
| POST | `/api/database/test` | Try a connection with the values entered (10 per 5 minutes) |
| GET, POST | `/api/database/copy` | Progress of, and start, the copy of your data into the saved database |
| GET | `/api/jobs` | Failed and dead jobs with their errors |
| POST | `/api/jobs/{id}/retry` | Retry a failed or dead job |
| POST | `/webhooks/{token}` | OpenWA delivers here (authenticated by the token, and by an HMAC signature once Iris registered the webhook) |

## Metrics

`GET /metrics` (Prometheus text format):

| Metric | Labels |
|---|---|
| `iris_webhooks_total` | `instance`, `result` (accepted, duplicate, skipped, rejected) |
| `iris_messages_processed_total` | `type`, `verdict` |
| `iris_stage_duration_seconds` | `stage` |
| `iris_provider_requests_total` | `provider`, `endpoint`, `status` |
| `iris_provider_duration_seconds` | `provider`, `endpoint` |
| `iris_transcription_seconds_audio_total` | `provider` |
| `iris_alerts_total` | `category`, `delivery_status` |
| `iris_jobs` | `status` |

`/metrics` is open by default. Because OpenWA needs Iris's port for webhooks, that port may be reachable from
outside, so set `IRIS_METRICS_TOKEN` or restrict `/metrics` in your reverse proxy.

## Privacy and security

- **Sign-in required** for the portal and every API except health and version. Webhooks are authenticated by
  a 32-byte random, rotatable token and, once registered through Iris, an HMAC signature.
- **Secrets are encrypted at rest** (AES-256-GCM) and never returned by the API.
- **Logs contain only IDs, types, categories, scores and timings**, never message text, transcripts or media.
- **Media is never kept.** It is downloaded to a per-job temporary directory and deleted afterwards, also on
  failure and on shutdown; leftovers from a crash are swept at start-up. Only media with a recognised audio,
  video or image signature is passed to ffmpeg.
- **Sexual content is withheld.** If a message involves minors (from the *low* threshold up), or is a
  sexual image, sticker or video, Iris clears its text and transcript, removes it from the search index,
  never quotes it in an alert, and refuses to reprocess it.
- **Retention.** Messages older than the retention window are deleted hourly, except while an alert still
  references them; alerts are deleted after their own window; finished jobs after 7 days.
- **Alert-loop protection.** Iris recognises its own alerts by a signature over the whole alert text, so an
  alert that reaches a monitored number is not classified, while a look-alike typed by someone else is.
- Security headers (CSP, `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options`) are set, and the
  container runs as a non-root user.
- Use HTTPS in front of Iris. Session cookies are marked `Secure` when `IRIS_PUBLIC_BASE_URL` starts with
  `https://`.

## Troubleshooting

**Test connection says "Could not reach the server".** Check the host and port from where Iris runs (in Docker,
`localhost` is the container itself: use the server's address or its compose service name) and any firewall.
"The user name or password was refused" and "That database does not exist" mean the server answered but the
login or the database name is wrong. Iris never shows the password in these messages.

**I changed the database but Iris still shows the old one.** The choice applies at the next start: restart Iris.
If **Settings > Database** is read only, `IRIS_DATABASE_URL` is set and wins.

**Messages show `failed` with "OpenWA has no stored media…".** OpenWA could not download the media of a
message the session *received*. This is a known bug in OpenWA before 0.24.0
([#1739](https://github.com/rmyndharis/OpenWA/issues/1739)): upgrade OpenWA, then press **Reprocess** on the
message. Text is unaffected.

**"Destination address is not allowed" when registering the webhook.** OpenWA blocks private-network
webhook targets. Put Iris behind a public hostname (reverse proxy or tunnel) and set `IRIS_PUBLIC_BASE_URL`
to it.

**No alert arrived.** Open the alert: **Delivery** says why (`not configured`, an OpenWA error, or
`suppressed` by the per-chat cooldown). Check that the sender session is running, then **Resend**. The
**Test** button under Settings → Alerts verifies the sender and recipient.

**A phone shows "Nothing received yet".** OpenWA cannot reach `IRIS_PUBLIC_BASE_URL`, or the webhook was
not registered. Check the URL from the OpenWA host.

**A borderline message was flagged.** Context can raise a score: a casual "you're dead meat, lol" after a
tense exchange may be judged harmful. Dismiss the alert, or raise the threshold for that category.

**Everything is slow or jobs pile up.** The dashboard shows queue depth. Moderation is rate limited by
OpenAI: Iris retries with backoff and honours `Retry-After`. Raise `IRIS_WORKERS` only if the queue stays long.

## Development

```bash
uv sync
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run pytest                    # unit tests: no network, providers mocked
uv run pytest -m integration     # real OpenAI (needs TEST_* variables, see .env.example)

cd web
npm ci && npm run lint && npm test && npm run build   # builds into ../app/static
npm run dev                      # Vite dev server, proxies /api to :8080
```

Layout: `app/` is the FastAPI backend (`ingest/`, `openwa/`, `jobs/`, `media/`, `transcription/`,
`classify/`, `alerts/`, `api/`), `web/` is the React portal, `tests/` mirrors it with real captured and
sanitized OpenWA payloads under `tests/fixtures/openwa/`. New classification stages plug into
`app/classify/stages.py`.

CI runs lint, type checks, tests, the portal build, a security scan, and builds the image for **both**
linux/amd64 and linux/arm64 on every pull request.

## License

Apache License 2.0. See [LICENSE](LICENSE).
