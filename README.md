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

Ollama can use accepted parent text reviews as examples for future checks. Settings →
Classification includes Off, Shadow comparison, and conservative Active learning modes.
See the [architecture flowchart, implementation plan, and evaluation guide](OLLAMA_LEARNING.md).

**IrisReview** shows messages queued for AI or being checked, with a thinking icon per message.
Parents and admins can skip AI to move a message into human **Review**. Cancelling AI revokes its
job lease, so a late AI result cannot overwrite a subsequent human decision. Human Review excludes
AI work and shows Safe/Harmful actions only for unresolved decisions; response history is read-only.
Review actions are visible directly, without an additional-options section.

### Operational settings

Settings → Notifications checks the selected channel against current provider readiness and
recipient eligibility. Only explicitly selected recipients receive alerts. GreenAPI requires a verified
provider connection but no individual phone approval. OpenWA numbers and SMTP emails require current
approval; standalone legacy destinations remain supported. One eligible
recipient is sufficient, while ineligible recipients stay visible in Settings and Home.

Device checks can automatically refresh a disconnected child connection. Settings → Schedules controls
the number of attempts, time between attempts, and delay before notifying parents. Defaults are one
attempt and a ten-minute notification delay; Home shows the outage immediately.
Chats and groups can be skipped per child with confirmation, then their history can be deleted separately.
Review can reveal original media, queue another AI check, and copy the full saved execution trace.
Local transcription HTTP 422 and 503 failures use bounded job retries before requiring parent review.
Local Ollama vision models now receive images/stickers and captions together. Settings → Providers
includes a separate Test Ollama image button that verifies model vision support and actual inference
using a bundled sample. Saved traces identify image or text+image classifications. Missing originals,
unsupported models and failed checks still require review; model scores are not calibrated guarantees.
The Ollama model dropdown detects installed models from the entered server and labels vision support.
Refresh the list or enter a custom name; detection preserves the saved choice until you explicitly save.
Review keeps compact Safe (green), Harmful, Ignore and Chat actions visible. AI rejudging, trace copying
and chat skipping sit under “Note: additional options.” Decision, skip and trace actions are disabled
while that message's AI recheck is queued or running.
Animated WebP stickers are unwrapped to their first frame for compatibility with older FFmpeg builds.
Image conversion checks that a nonempty JPEG was produced and bounds both dimensions. This checks
the first displayed frame, not every frame of an animation; the original remains available to view.

Settings → Schedules includes daily summaries, device/webhook verification, incident notifications,
retention, media cleanup, stale job recovery, pending alert catch-up, group names and pairing cleanup.
Daily summaries are disabled by default. Notifications respect child assignments and sending budgets.
Run history retains at most ten runs per schedule, reserving space for three failures within those ten;
failed runs expire after four days. Errors and stack traces are retained with credentials redacted.
Message, alert and media retention controls remain in Settings → Retention.

Settings → Audit records user actions and committed before/after values from the update onward.
Passwords, credentials and message content are redacted. Existing actions cannot be reconstructed.
Group skipping is available per child from Messages, Review and Alerts, with optional history deletion
and a resume control on Phones. Shared records remain available for the other children.

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
  system. Targeted tests cover accessible controls and keyboard interactions; a full automated accessibility audit has not been completed.
- **Sexual content safety rule.** Content clearly involving minors, and sexual imagery, is withheld entirely: it
  is not stored, not searchable, not shown and not forwarded. The alert says to review the chat directly. When
  Iris is only *unsure* about a text or voice message (a low score), it keeps the words so you can read them in
  the review queue and decide. It is never copied into an alert or sent to WhatsApp, and confirming it as harmful
  withholds it at that moment.
- **Hidden until you look.** Stored content (message text, alert quotes, kept media) is hidden by default and
  shown with an eye button; a switch under Settings > Account makes this browser show it by default.
- **Keep the media if you want to (off by default).** Store the photo or voice note behind an alert on
  the server's disk or in S3-compatible storage (Cloudflare R2, AWS S3, SeaweedFS, MinIO); the alert and the
  dashboard link to it.
- **Self-hosted and private.** Secrets are encrypted at rest, logs never contain message text, media is
  deleted after processing unless you turn on keeping it, and old data is removed automatically.
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
    image: ${IRIS_IMAGE:?Set a reviewed release tag or digest}
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
cp docker-compose.example.yml compose.yml   # edit credentials and the image version before starting
export IRIS_IMAGE='techblog/iris:<reviewed-release-tag>'  # replace with your tested version
docker compose up -d
```

More ready-made files, for SQLite, MySQL, PostgreSQL and OpenWA, are in [`docker-compose/`](docker-compose/README.md).

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
| `IRIS_DATA_DIR` | no | `/data` | SQLite database (unless another database is chosen), the saved database choice, temporary media and, if you keep media on this server, the `media` folder. |
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
- The copy reads one consistent snapshot of the current database, so rows written meanwhile cannot break it. If it
  fails part-way, Iris empties the new database again and you can simply retry.

![Database settings in dark mode](assets/screenshots/database-postgres-dark.png)

### Keeping media

By default Iris deletes every photo and voice note as soon as it has been checked. Under **Settings >
Media** you can turn on keeping copies, so you can look at what triggered an alert.

![Media settings](assets/screenshots/settings-media.png)

- **What to keep:** only what Iris judges **harmful**; **harmful and needs a look** (the review queue too); or
  **everything**. The decision is made after the check, so a "harmful only" setting never stores the rest.
  **Videos are not kept at all**: Iris checks what a video says, not what it shows, so it cannot promise that
  a sexual video would be withheld.
- **Where:** **this server's disk** (the `media` folder inside the data folder, so in Docker the data volume) or
  **S3-compatible storage**. Create the bucket first, then enter the endpoint, bucket, access key and secret
  key and press **Test storage**: Iris writes, reads back and deletes a tiny file.

  | Service | Endpoint | Region | Notes |
  |---|---|---|---|
  | Cloudflare R2 | `https://<account id>.r2.cloudflarestorage.com` | `auto` | Create an R2 API token with object read and write for the bucket. |
  | AWS S3 | `https://s3.<region>.amazonaws.com` | the bucket's region, e.g. `eu-west-1` | Turn **path-style addresses** off if your bucket needs `bucket.host` addresses. |
  | SeaweedFS | `http://<host>:8333` | any, e.g. `us-east-1` | Start the S3 gateway with an identity that has the access key and secret. |
  | MinIO | `http://<host>:9000` | any, e.g. `us-east-1` | |

  ![Media settings with S3-compatible storage](assets/screenshots/settings-media-s3.png)
- **How long:** media has its own limit, **30 days** by default. Older files are deleted from the storage; the
  message and its alert stay until their own limits under Retention. If the storage is unreachable, Iris keeps
  trying until the file is gone.
- **Where you see it:** the WhatsApp alert gets a line such as `📎 Media kept (image, 1.2 MB): https://…/media/12`;
  the alert page shows the photo or plays the voice note; the alert list and the dashboard mark alerts
  that have media and the dashboard shows how many files and how much space they use.

  ![A kept photo on its alert](assets/screenshots/media-alert-detail.png)

  ![Dashboard with kept media](assets/screenshots/media-dashboard.png)

  | Alerts with kept media | The media page |
  |---|---|
  | ![Alert list](assets/screenshots/phone-media-alerts.png) | ![Media page](assets/screenshots/media-viewer.png) |

How it stays safe:

- **Withheld content is never kept.** Media of a message withheld by the safety rule (anything sexual involving
  minors, or sexual images and stickers) is not stored whatever you choose, and if a later check withholds a
  message, its kept copy is deleted. Media Iris could not check (a failed conversion or transcription) is not
  kept either.
- **Only after you sign in.** The link in the alert opens an Iris page that needs your login (it lasts 7 days
  on a phone). Iris streams the file itself, with a strict content type, so it is never served straight from the
  bucket and nothing in the WhatsApp text can open it on its own. Keep the bucket private.
- **Only real photos and audio** are kept, recognised by their bytes and matched to the message type. Documents
  and videos are not kept.
- A storage problem never blocks checking or alerting: the alert simply goes out without the link.
- Copying your data to another database does not move the files: they stay in the data folder or the bucket and
  keep working.
- Each file remembers which storage it was written to, so changing the bucket later does not strand old files;
  **Delete all kept media** (Settings > Media) removes everything, also after you turned keeping off.

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
| Media | Keep media: off, harmful, harmful and needs a look, everything; where; how long | off, this server's disk, 30 days |

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

### Live updates

While a page is open, Iris pushes changes to it, so new messages, alerts, review items and job failures
appear without a reload. A **Live** indicator (**Reconnecting…** if the connection drops) shows that the page is
updating by itself, and a new alert also shows a toast, **A new alert needs you**, with an **Open** button, and
puts the number of unseen alerts in the browser tab title until you come back to it.

![Home with the Live indicator](assets/screenshots/dashboard.png)

The stream never carries message content: it only says *what* changed (messages, alerts, stats, ...) and the
page then asks the normal, signed-in API for the new data, so hide and show and withholding apply exactly as
before. If a proxy blocks or buffers the stream, the page keeps working and still refreshes about once a
minute.

Behind a reverse proxy, turn buffering off for `/api/events` (nginx: `proxy_buffering off;` or rely on the
`X-Accel-Buffering: no` header Iris sends) and allow long-lived responses. Iris sends a heartbeat every 20
seconds. Up to 20 portal tabs can listen at once. The stream lives inside the one Iris process, which is how Iris
is meant to run.

### Hide and show

Everything Iris has stored of a message is **hidden by default**: message text and transcripts, alert quotes,
kept photos and voice notes, and edit history. Hidden text appears as a blurred mask that contains none of the
real characters, and hidden media is not even requested from the server. Press the **eye** to show it and again
to hide it. Nothing is remembered between page views, unless you turn on **Settings > Account > Show content by default**
(kept in this browser only), which makes every page start shown; the eye still hides it.

![Alerts, hidden by default](assets/screenshots/alerts-hidden.png)

- On lists (**Alerts**, **Messages**, the **Home** recent alerts) one **Show content** button at the top
  reveals every row on that page.
- On a single alert, conversation, review card or media page the button sits next to the content.

| Hidden | Shown |
|---|---|
| ![Alert, hidden](assets/screenshots/alert-detail-hidden.png) | ![Alert, shown](assets/screenshots/alert-detail-shown.png) |

**Withheld content cannot be shown, on purpose.** If a message clearly involves a minor in a sexual context (or is
a sexual image, sticker or video, or an image of a possible minor), Iris never stores it, because keeping it could be illegal, so there is nothing
behind the eye. The alert says what was detected and tells you to open the chat directly in WhatsApp.

![A withheld alert](assets/screenshots/alert-withheld.png)

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

Messages that stayed inconclusive even with the surrounding chat wait here, with their text (hidden until you
press the eye, or shown if you turned on **Settings > Account > Show content by default**). **Mark safe** closes
them; **Mark harmful** creates an alert and, if the message was flagged as involving a minor, withholds its text
from then on.

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
| GET | `/api/events` | Server-sent events: `change` (topics that changed) and `alert` (id of a new alert), never content |
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
| POST | `/api/settings/test/{openai\|cloudflare\|alert\|media}` | Test a provider with the values entered |
| GET | `/api/media/{id}`, `/api/media/{id}/info` | A kept file (streamed by Iris, byte ranges supported, never from the bucket) and what it belongs to; 404 once it is deleted or withheld |
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
| `iris_live_clients` | none (portal tabs listening for live updates) |

`/metrics` is open by default. Because OpenWA needs Iris's port for webhooks, that port may be reachable from
outside, so set `IRIS_METRICS_TOKEN` or restrict `/metrics` in your reverse proxy.

## Privacy and security

- **Sign-in required** for the portal and every API except health and version. Webhooks are authenticated by
  a 32-byte random, rotatable token and, once registered through Iris, an HMAC signature.
- **Secrets are encrypted at rest** (AES-256-GCM) and never returned by the API.
- **Logs contain only IDs, types, categories, scores and timings**, never message text, transcripts or media.
- **Media is not kept unless you turn it on** (Settings > Media). It is downloaded to a per-job temporary
  directory and deleted afterwards, also on failure and on shutdown; leftovers from a crash are swept at
  start-up. Only media with a recognised audio, video or image signature is passed to ffmpeg. If you do keep
  media, see [Keeping media](#keeping-media): withheld content is never kept, files are served only to a
  signed-in owner, and they expire on their own schedule.
- **Sexual content is withheld.** If a message involves minors at or above the *high* threshold, or is an
  image, sticker or video that involves minors (at any score) or is sexual, Iris clears its text and
  transcript, removes it from the search index, never quotes it in an alert, and refuses to reprocess it. A
  text or voice message that scores only in the uncertain band (above *low*, below *high*) is kept, hidden until
  you press the eye, so you can judge it in the review queue; marking it **harmful** withholds it at once, and
  marking it **safe** leaves it as it is. Kept media is never stored for any message flagged as involving minors.
- **Retention.** Messages older than the retention window are deleted hourly, except while an alert still
  references them; alerts are deleted after their own window; finished jobs after 7 days.
- **Alert-loop protection.** Iris recognises its own alerts by a signature over the whole alert text, so an
  alert that reaches a monitored number is not classified, while a look-alike typed by someone else is.
- Security headers (CSP, `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options`) are set, and the
  container runs as a non-root user.
- Use HTTPS in front of Iris. Session cookies are marked `Secure` when `IRIS_PUBLIC_BASE_URL` starts with
  `https://`.

## Troubleshooting

**Images, videos or stickers show “OpenWA has no saved copy.”** Settings > Retention now
shows persistent archiving and bounded media recovery controls. Previews use Iris's checked,
retained copy first, with byte-range support. If OpenWA omitted its download, Iris can ask
WhatsApp again for the exact message among at most ten recent chat messages. Recovery has a
25 MB limit, a 65-second deadline per attempt, and configurable attempts (0–3) and wait (0–30
seconds). Old media that WhatsApp no longer supplies, or messages outside that recent window,
can remain unavailable. Iris does not follow arbitrary upstream media URLs.

OpenWA 0.24 catches browser media-download failures without retrying and its saved-media
endpoint does not redownload omitted files. Persistent provider storage is configured with
`CHAT_MEDIA_ARCHIVE_ENABLED=true` and `CHAT_MEDIA_ARCHIVE_OUTBOUND=true` in OpenWA's
deployment; redeploy to apply. `CHAT_MEDIA_ARCHIVE_TTL_DAYS=0` disables expiry. Choose a
provider retention window deliberately: Iris's retention does not remove provider copies.
The bundled templates expose these as `OPENWA_MEDIA_ARCHIVE_*` variables, defaulting to off
for compatibility. Retention's provider values are deployment-reported metadata, not a live
API query; keep the matching `IRIS_OPENWA_ARCHIVE_*` metadata in sync when changing an
external OpenWA deployment. The OpenWA archive controls cannot be changed through its 0.24
settings API. Iris's own archive switch and recovery controls save immediately in Iris.

**Test storage fails, or alerts go out without a media link.** Run **Test storage** under Settings > Media: it
says whether the endpoint cannot be reached, the keys are refused, or the bucket does not exist. A failed
upload never blocks checking or alerting; the media is simply not kept. For R2 make sure the token can write to
the bucket, and for AWS check the region and the path-style switch.

**Test connection says "Could not reach the server".** Check the host and port from where Iris runs (in Docker,
`localhost` is the container itself: use the server's address or its compose service name) and any firewall.
"The user name or password was refused" and "That database does not exist" mean the server answered but the
login or the database name is wrong. Iris never shows the password in these messages.

**Iris will not start and the log says it cannot reach the database, or that `database.json` cannot be read.**
Iris never falls back to SQLite on its own, because new messages would then land in a different database than
your history. Start the database server, or restore the `IRIS_SECRET_KEY` the file was saved with. To give up
on the saved choice, delete `database.json` in the data folder (or set `IRIS_DATABASE_URL=sqlite:////data/iris.db`)
and restart.

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
npm ci && npm run lint && npm run format:check && npm test && npm run build   # builds into ../app/static
npm run dev                      # Vite dev server, proxies /api to :8080
```

Layout: `app/` is the FastAPI backend (`ingest/`, `openwa/`, `jobs/`, `media/`, `transcription/`,
`classify/`, `alerts/`, `api/`), `web/` is the React portal, `tests/` contains Python tests with real captured and
sanitized OpenWA payloads under `tests/fixtures/openwa/`. Frontend tests mirror the React
source under `web/tests/`, with shared setup and helpers in that folder. New classification stages plug into
`app/classify/stages.py`.

CI runs lint, type checks, tests, the portal build, a security scan, and builds the image for **both**
linux/amd64 and linux/arm64 on every pull request. Backend tests run on SQLite, PostgreSQL,
and MySQL; frontend tests run with Vitest on Node 22. CI stores JUnit test reports as downloadable
artifacts, including failed runs. The native transcription companion has its own tests under
`docker-compose/local/macos/tests/` and a path-filtered workflow.

Local deployment scripts, private settings and audit outputs belong to the parent workspace,
outside this Git repository. Temporary test runs and generated reports belong under ignored
`.local/` directories. Default test runs use isolated databases and mocked providers; tests that
contact real services are marked `integration` and require explicit test configuration. A green
GitHub run verifies the revision that was pushed, not subsequent uncommitted local changes.

## OpenWA retry settings and missed-message recovery

The Alerts page defaults to **Unseen for the signed-in account**. Opening an alert detail page
marks it read for that account and updates its list and badge. Browsing the list or fetching a
detail through the read-only API does not mark it read; the portal posts to
`/api/alerts/{id}/seen` after opening the detail successfully. **Seen**, **All**, and **Dismissed**
views retain access to existing alert records. **Mark unseen** returns an alert to your Unseen
list. Read/dismiss state is keyed by both account and alert, and cannot clear another account's
unseen alerts. It does not change the message's safety verdict or delete the alert. Existing
global statuses are not attributed to individual users during migration, so older alerts start
unseen for each account until that account opens them.

OpenWA recovery is configured under **Settings → Notifications → OpenWA webhooks**:
choose **1–5 total delivery attempts**, enable automatic catch-up, and set a **1–720 hour**
lookback (default 24 hours). Iris applies the attempt count to its existing webhooks on the next
minute's catch-up run and uses it for new registrations. Other webhooks are left untouched.
Retry backoff/timeout remain OpenWA server settings.

Scheduled operations have one reserved worker whenever classification workers are enabled.
Catch-up and device checks therefore run while AI workers are busy. The health endpoint's worker
count includes this reserved worker; setting classification workers to zero pauses scheduled work.

**Recover missed messages now** queues a manual pull even when automatic recovery is off.
**Settings → Schedules → OpenWA message catch-up** shows counts, errors and execution history,
and controls the schedule. Recovery reads OpenWA's persisted message history with inline media
disabled; failed-delivery diagnostics alone do not contain the message body. Each phone scans
up to three 100-row pages per run with a persistent keyset cursor and a two-minute overlap.
Incomplete runs resume next time, and changing the lookback starts a fresh bounded scan.
The retention window also caps recovery. Scope, paused phones, parent/sender roles, skipped chats,
own-alert detection, existing human decisions and withheld content remain enforced by normal
ingestion. Recovered messages enter IrisReview and the normal classification/alert pipeline.
Upstream errors leave progress unchanged and appear in schedule results without message content.

Recovery requires messages still retained in OpenWA and a key permitted to read session history.
It cannot recreate purged messages, missing media bytes, or historical edit/revocation webhook
events that the history API does not expose. It does not resend failed outgoing WhatsApp messages.


## License

MIT License. See [LICENSE](LICENSE).

## Optional local providers (beta)

The [beta local deployment guide](docker-compose/local/README.md) describes opt-in Ollama moderation, a native Apple Silicon transcription companion, parent recipient management and QR pairing. Existing cloud defaults remain unchanged. Read the guide's validation limits before deploying this beta for monitoring.


### User accounts, 2FA and public alert links

Settings → Users manages admin and Watch-only accounts, email and personal WhatsApp numbers,
account password changes, and 2FA. Settings → Notifications manages encrypted SMTP
and GreenAPI credentials. Gmail SMTP supports STARTTLS 587 or TLS 465 with an app
password. Either SMTP or GreenAPI must pass its test, and each user must approve at least one
contact through a single-use confirmation link before enabling 2FA.
WhatsApp 2FA uses GreenAPI only, sending a Copy code button to each user's personal
number. Each Admin, Parent or Watch user needs an approved email or personal WhatsApp number;
one working, approved channel is sufficient. Login codes expire after five minutes, are single-use,
and have a limited attempt budget. Provider acceptance confirms sending. Confirmation links use Iris base URL and expire
after 30 minutes; opening a link alone does not approve it. Click Approve contact.

Settings → Alerts → Iris base URL sets the public domain used for new alert/media
links (for example `https://iris.example.com`). The saved value overrides
`IRIS_PUBLIC_BASE_URL` in `.env` / Docker Compose and takes effect without restarting.
Configure the domain/reverse proxy first. Existing delivered messages retain their original links.

Human Safe/Harmful reviews are stored separately from original model scores. Iris
stores these labels for review and evaluation only. Reviewed text is never added to model
instructions, and labels do not train the model or automatically alter thresholds.
Labels never bypass moderation based on similarity. Deleting a phone retains messages by default. The optional message deletion
removes messages exclusive to that phone and schedules their stored media for deletion;
messages also received through another phone remain.


OpenWA's webhook destination can be configured independently in Settings → Alerts →
OpenWA webhook base URL (`IRIS_WEBHOOK_BASE_URL` in `.env` / Docker Compose).
Use an address reachable and allowed by OpenWA, for example the private NAS URL;
the public HTTPS Iris URL stays in parent alerts and browser links. Re-pairing
reports WhatsApp connection success separately from webhook restoration failure,
with a retry for monitoring setup. Existing matching webhooks are updated, not duplicated.


### Approving 2FA contacts

1. Set **Settings → Alerts → Iris base URL** to your reachable HTTPS domain. This
   domain is used for email and WhatsApp approval links, as well as alert links.
2. Save each user's email or personal WhatsApp number in **Settings → Users**.
   Personal numbers use international format, such as `+972501234567`. Email addresses
   and WhatsApp numbers cannot be shared by different users; email comparisons ignore case.
   Admins can delete non-admin accounts after confirmation; admin accounts are protected.
   Deleting an account revokes its access and approval links, retaining phones and messages.
3. In **Settings → Notifications**, configure and test the intended channel:
   SMTP for email, or GreenAPI API URL, instance ID and API token for WhatsApp.
   WhatsApp 2FA uses GreenAPI only; OpenWA remains for monitoring and alerts.
4. The admin test message includes an approval link. Open it and select
   **Approve contact**. Use **Approve email** or **Approve WhatsApp** in the users
   list to send approval links to other users or resend an expired link.
5. Enable 2FA after every user has at least one approved contact with a tested
   provider. An approved email with working SMTP is enough; an approved WhatsApp
   number with working GreenAPI is also enough. You do not need both.

Approval links expire after 30 minutes and work once. Loading a link does not
approve it automatically. Changing a contact clears its approval and invalidates
old links. Users without an approved working channel cannot sign in when 2FA is
required. WhatsApp login messages include a **Copy code** button; test messages
contain a demonstration code for checking the WhatsApp Copy code button. Email
approval messages contain only the approval link; login emails contain the actual 2FA code.

### Emergency Docker-only 2FA recovery

Set `IRIS_TWO_FACTOR_RECOVERY_KEY` to a long random key (at least 32 characters)
in `.env` and pass it through the Iris service's Docker Compose environment.
Keep a copy offline. The local installation generates this key in the deployment
`.env`; it is never shown in the UI or accepted by an HTTP login endpoint.

Open an interactive shell on the Docker host or use the Iris container console:

```sh
docker exec -it iris /app/.venv/bin/python -m app.security.recover_2fa --username admin
```

Replace `admin` with your admin username. Enter the predefined key when prompted;
do not pass it on the command line. The command disables 2FA globally for recovery,
revokes all sessions, login challenges and pending approval links, and records an
audit event. User accounts, passwords, messages and approved contacts are retained.
If the admin's IP is locked out, the recovery command does not clear the running
server's in-memory limiter. After recovery, run `docker restart iris` on the Docker
host (or restart the container in Portainer). A restart clears the temporary login
lockout; it does not reset the admin password. Use the HTTPS Iris address, since
HTTP cannot establish a Secure session cookie. Sign in with the normal password,
repair SMTP/GreenAPI delivery, then re-enable
2FA before resuming normal access. There is no local-IP or recovery-key web bypass.

### Monitoring roles and unresolved media

Watch is read-only. Parent can resolve reviews, resend alerts, reprocess messages and delete
saved media evidence; Admin additionally manages accounts, settings and phones. Parent can
purge saved media from the Review page. Review decisions affect that message only.
Video transcripts do not check video visuals: videos require parent review in local safety mode.
The review page records why each item needs attention. Review notifications default to enabled;
configure the alert recipient and sender under Alerts for WhatsApp delivery.
Skipped and failed messages expire at the configured message retention age, while active jobs
and unresolved reviews are preserved. Pairing cleanup logs failures and retries automatically.

OpenWA deployments require a tested immutable `OPENWA_IMAGE` digest and disable Watchtower
updates. Upgrade the gateway explicitly after testing pairing and signed webhooks.
Database backups must be copied to a separate machine or backup destination and verified
before pruning NAS copies. Keep a bounded set of recent local recovery snapshots; snapshots
on the database disk alone do not protect against loss of that disk.

For a complete recovery set, back up Iris's entire `/data` volume, the OpenWA `/app/data`
volume, the deployed Compose configuration, `IRIS_SECRET_KEY`, and the Docker 2FA recovery
key. Keep credentials and session files in an encrypted, access-controlled backup outside
the application disk. An Iris SQLite snapshot alone does not include retained media or
WhatsApp sessions. S3-backed evidence also needs the bucket's own backup/versioning policy.

Rehearse recovery into **new directories**, never by overwriting the live volumes. Check
SQLite `PRAGMA integrity_check` and verify that the saved encryption key decrypts a stored
credential. Restore the same reviewed image versions and test Iris on a separate port with
alert delivery disabled. Stop the original OpenWA before starting a restored WhatsApp
session; running both copies can disrupt pairing. Verify user sign-in, retained media, and
session readiness before moving traffic. Keep the original volumes until recovery is verified.

This procedure requires a separately configured backup schedule; deployment snapshots do
not provide continuous backups or prove a complete OpenWA/media restore.

Skipped messages carry a specific processing reason. New messages preserve OpenWA's original
type plus event name and content-presence flags, without storing a second raw payload. In
safety mode, unknown messages with no analyzable content or unsupported attachments require
manual review. Only allowlisted, content-free system events are skipped as system events.
Legacy unknown skips with no recoverable original type are routed to review on startup.

Review notification catch-up waits for the alert sender to reconnect. Failed review delivery
gets one automatic recovery retry, with existing recipient tracking and cooldowns preserved;
persistent failures stay visible for a Parent or Admin to correct and resend.

Automatic alert delivery and review catch-up respect paused source phones, including queued
alerts and follow-ups. A shared message may still alert through another active monitored
phone. Parent sender connections can send alerts while their own monitoring is off.
Review notices are identified as unconfirmed, and matching alert/message IDs are shown in
Iris and new WhatsApp notifications. Cooldown-held and failed rows remain in Iris without
being sent. Saving an unchanged user profile keeps pending login codes valid; actual account
security changes invalidate them and the login page explains the reason.


### Queue and notification reliability

Retention preserves pending and processing messages, unresolved reviews, and messages with
active classification jobs in every mode. Terminal failed/skipped messages still expire under
the configured retention window. Classified harmful/review decisions keep durable alert-creation
retry jobs if their notification hook fails; retrying these jobs does not rerun AI classification.
Held harmful alerts resume when a source phone resumes monitoring and delivery is configured.
Confirming a review retries an existing undelivered alert while preserving recipient checkpoints.
Parent alert delivery remains opt-in and requires configured sender/recipients.

`IRIS_JOB_TIMEOUT_SECONDS` bounds each handler attempt (default 900 seconds, maximum 3600),
even while its lease heartbeat runs. Without heartbeats, attempts are capped at 570 seconds
to end before the ten-minute stale lease can be claimed again. Classification and alert-creation timeouts retry with the
queue's bounded backoff. Delivery timeouts remain visibly failed for manual inspection because
a provider may have accepted a send before its response was lost.

When 2FA is already enabled, new users require a contact backed by a tested provider; send its
approval link from Settings → Users before their first login. An enrolled user's last approved
working channel cannot be removed while 2FA is enabled.

Webhook token rotation now rejects unsigned deliveries and shows that re-registration is
required. Register the new webhook URL and signing secret before expecting delivery to resume.
Pairing registers signed webhooks automatically. Manual installations can enforce signatures
for every instance with `IRIS_REQUIRE_WEBHOOK_SIGNATURES=true`; configure matching signing
secrets at the gateway before enabling that setting.


New phone connections require HMAC-signed webhooks from creation, including manual additions.
For manual connections, use **Register webhook** in Phones before expecting messages to arrive;
Iris configures the URL and signing secret in OpenWA. Existing legacy connections retain their
registration setting to avoid interrupting monitoring; re-register them to enable signing, or
use the global strict-signature setting after configuring the gateway.

Job acknowledgements and failures are tied to the claimed attempt. An old attempt cannot
complete or fail its recovered replacement. Stale delivery/follow-up jobs are marked visibly
failed with an uncertain-delivery warning rather than automatically sending again. Check
whether the recipient received the message before explicitly retrying. Automatic review
catch-up excludes these uncertain deliveries; confirmed recipient checkpoints remain preserved.


In Review, parents and admins can choose **Ignore — missing data** when there is not enough
information to decide. The item leaves the active queue and is available under **Ignored:
missing data**. Iris preserves its evidence and diagnostic reason and records the data-quality
report separately from safety judgements for later design review. Ignoring does not label it
safe or harmful, train Ollama, change thresholds, or automatically approve similar messages.
Parents can make a safety decision later from the ignored view.

Async requests show an indeterminate progress bar while Iris is working. Ordinary API
requests time out after 30 seconds and release controls for retry; provider tests and
classification checks allow two minutes, and database copying allows five minutes. A
browser timeout does not cancel work already accepted by the server: check its result
before repeating a change. Login can retry session loading without resubmitting an
accepted verification code.

WhatsApp alert delivery uses persistent sending budgets shared by all chats, parents,
follow-ups and manual resends. Settings → Alerts controls the default 30-second spacing,
60 sends per hour and 250 sends per 24-hour window per sender. Each recipient also has
60-second spacing, 20 sends/hour and 100/day. Every provider call reserves capacity;
failed or uncertain calls also count. Jobs exceeding a budget remain queued with the next
attempt time, retain recipient checkpoints and do not consume failure retries. Delivery
still obeys the per-chat cooldown; suppressed alerts are counted in later alert summaries.
These are Iris traffic controls, **not WhatsApp-approved safe sending limits**. Account
restrictions remain possible with unofficial automation; use an eligible official WhatsApp
Business Platform integration or a different notification channel for supported automation.
Provider throttling pauses the sender for five minutes; authorization rejection pauses it
for 24 hours and requires checking the connection. Test messages use the same budgets.

GreenAPI verification and approval messages use a separate persistent budget: five seconds
between sends per instance, 60/hour and 250/day; per contact, one minute between requests,
five/hour and 20/day. Excess requests return a retry delay instead of queueing an expiring
code behind alerts. Use email when WhatsApp code delivery is unavailable. Iris does not
change provider-side queue settings or send anything merely by upgrading.

For a multi-parent alert test, Iris may send the first test immediately and queue the
remaining tests behind the same sender budget. Successful recipients are not repeated;
Settings reports that the rest are queued, and Jobs shows completion or failure. A repeated
single-recipient test during its limit returns a retry delay instead of sending again.


### Phone alert review (beta.10)

Notifications includes a private-summary/message-preview design and an opt-in review button setting.
GreenAPI and Telegram personal alert recipients can choose SAFE, Harmful or Ignore. The first
accepted parent response is final; subsequent choices become notes in Review → Parent responses &
notes and the alert detail. Buttons are bound to their recipient, provider and alert, expire after
four days, and revalidate current recipient eligibility and child assignment before accepting.
GreenAPI buttons are a beta provider feature. Use dedicated notification connections without a
webhook or another polling consumer, and enable incoming messages for GreenAPI. Iris consumes that
instance's notification queue. Telegram polls callback updates. The Parent alert responses schedule
checks every 30 seconds by default; it supports run-now, bounded history and dashboard failures.
Decisions and notes are committed before provider acknowledgement; replayed responses are ignored.
Private summaries continue to omit message content. All notices include the configured Iris server
address. WhatsApp and Telegram control their native fonts; Iris and HTML email use lighter type.


GreenAPI recipient phones do not need individual approval. A successfully verified GreenAPI
connection and a valid selected recipient number are sufficient. Missing optional phone numbers,
watch users, deleted accounts and empty child assignments remain ineligible. The same policy is
used for channel selection, delivery, review-button responses and dashboard readiness.


## Chats filters

Chats supports the same time, phone, message type, verdict, sender, and message/transcript search filters as Messages, including Hebrew. A conversation matches only when a single message satisfies all selected filters. Opening a chat carries those filters into Messages. Chat message and alert counts continue to show the full conversation totals.


## Home resource metrics

System resources appears last on Home. Activity, alerts per group/contact, recent alerts and system resources each have an accessible collapse control and start expanded. Collapsing preserves filters and loaded content. Disk measures the filesystem hosting Iris, including other files on that volume. CPU samples the Iris container over 250 ms and respects its CPU quota; RAM measures its cgroup memory use (including cache) against its configured limit. The cards refresh each minute, support Hebrew RTL and reduced motion, and show unavailable when counters cannot be read. Disk uses a liquid glass, CPU a pulse, and RAM illuminated segments.


### Reading alerts on page entry

Entering Alerts marks the displayed batch read for the signed-in user and refreshes Home/sidebar unread counts. The rows stay visible during that visit so they can be read; returning to Unseen excludes them. Next unread alerts loads the first remaining batch, avoiding pagination skips as the unread list shrinks. Background data requests remain read-only, other accounts are unaffected, and read errors offer a retry.


### Missing saved media

Home's missing-media warning links to `/alerts?view=all&media=missing`, so its affected list includes read alerts. Alerts offers a No saved media copy filter. The warning and list share the same predicate: retained non-withheld image/audio/voice/video/sticker/document alerts with no non-purged saved media row. This differs from Human review, which lists messages awaiting a human decision.


### WhatsApp message types

Polls are recognized separately and their available text can be searched and checked. Empty deleted-message markers and unsupported gateway messages have explanatory labels instead of `[other]`. Deleted content and unsupported fields cannot be reconstructed when OpenWA provides neither a body nor media. Catch-up can repair older missing type metadata on duplicate messages without restoring content or changing existing verdicts. Empty confirmed deletion markers bypass AI; genuinely unsupported messages stay subject to review.


The installed OpenWA poll mapper also preserves question, option names and multiple-answer mode in webhooks and stored-message metadata. Iris converts these fields into searchable/classifiable text; incomplete polls stay reviewable. Poll secrets and voter identities are not included. Older gateway rows may contain only the question; changing a type label cannot reconstruct missing options or votes.

Home shows unfinished or skipped setup steps to admins. OpenWA, a tested notifier, an approved parent recipient and a connected child remain visible until ready. The defaults-review reminder is dismissible per admin; dismissal does not complete setup. The setup checklist remains available from Home and Settings.
