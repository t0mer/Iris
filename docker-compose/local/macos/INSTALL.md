# Install a native Mila transcription API on Apple Silicon

The custom companion scripts are MIT licensed. Read [licenses and attribution](LICENSES.md) and keep the bundled [LICENSE](LICENSE) with shared copies. Mila, engines and models retain their own licenses.

This setup provides a private HTTP transcription API on an Apple Silicon iMac or another Mac with an M1 or later chip. Hebrew uses the full ivrit.ai large-v3 model; English uses the full Whisper large-v3-turbo model. Neither model is quantized. Docker and cloud inference are not used.

There are two separate components: the official Mila desktop app, and the custom Python API companion included in this bundle. Mila itself does not expose this HTTP API. The companion invokes whisper.cpp directly and reuses Mila's model files. The desktop app can stay closed while the API operates. [Mila documents its on-device transcription and remote API client separately](https://github.com/island-io/mila).

## 1 Check the Mac and prerequisites

Run in Terminal:

```sh
sw_vers
uname -m
sysctl -n hw.memsize
xcode-select -p
```

The architecture should be `arm64`. Use macOS 14 or later for Mila. Install current Command Line Tools if they are missing:

```sh
xcode-select --install
```

Allow that installation to finish before continuing. Full Xcode is not needed for the prebuilt Mila app or this CMake engine build.

16 GB RAM is recommended for this configuration. An 8 GB Mac has less headroom for the full Hebrew model, especially if other large applications or Ollama models are loaded. Allow at least 10 GB of free disk space for models, the application, build files and dependencies; optional Core ML model downloads use additional space. M1 and later machines are the intended targets; run the verification steps on each installation rather than assuming every chip and macOS combination has been tested.

## 2 Install native dependencies

Install Homebrew from its [official website](https://brew.sh/) if it is missing. Follow its printed shell setup instructions. On a native Apple Silicon installation its prefix should be `/opt/homebrew`:

```sh
brew --prefix
brew install python@3.12 uv ffmpeg cmake git
/opt/homebrew/bin/python3.12 --version
/opt/homebrew/bin/ffmpeg -version
```

Node.js is not required for this transcription API. Iris and OpenWA are separate installations.

## 3 Install the official Mila desktop app

The reference installation used Mila **1.9.6**. Download its ZIP from the [official release](https://github.com/island-io/mila/releases/tag/v1.9.6). The reproducible commands below pin that release:

```sh
mkdir -p "$HOME/Downloads/mila-setup"
cd "$HOME/Downloads/mila-setup"
curl -fL --retry 2 \
  https://github.com/island-io/mila/releases/download/v1.9.6/Mila-1.9.6.zip \
  -o Mila-1.9.6.zip
printf '%s\n' \
  '75ba16e9779e696dc6e4f389f799e6e62222d2d10959a29531c51f0b422896a3  Mila-1.9.6.zip' \
  | shasum -a 256 -c -
ditto -x -k Mila-1.9.6.zip extracted
codesign --verify --deep --strict extracted/Mila.app
spctl --assess --type execute --verbose=2 extracted/Mila.app
```

Continue only if the checksum and signature checks pass and Gatekeeper accepts the app. Copy `Mila.app` to Applications using Finder; do not overwrite an existing installation without checking its version and backing up its data.

Open Mila. Under Settings:

1. Models → Backend: **On-device**.
2. Wait until both **ivrit.ai large-v3** and **OpenAI large-v3-turbo** show Installed.
3. AI Provider → Tool: **Off**, unless you separately configure a local provider.
4. Turn automatic summaries and Live AI off if you only need transcription.
5. Leave remote cloud transcription disabled.

No microphone or screen-recording permission is needed for the HTTP API. Mila may request these when you use its recording features; they are separate from server setup.

Mila's model location is:

```text
~/Library/Application Support/Mila/Models/
```

The API needs these two files:

```text
ivrit-ai-whisper-large-v3.bin
openai-whisper-large-v3-turbo.bin
```

Verify the full model files:

```sh
cd "$HOME/Library/Application Support/Mila/Models"
printf '%s\n' \
  '09e66ec67b2e00c6933afab6684cbf78fe023e8ad153c1848f62000e4335a07f  ivrit-ai-whisper-large-v3.bin' \
  '1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69  openai-whisper-large-v3-turbo.bin' \
  | shasum -a 256 -c -
```

These hashes identify the files used by the reference installation. If an upstream update changes them, investigate the change rather than disabling verification. [The ivrit.ai GGML model is compatible with whisper.cpp](https://huggingface.co/ivrit-ai/whisper-large-v3-ggml).

## 4 Copy the API companion files

Extract the sanitized installation bundle. In Terminal, change into the extracted `mila-api-share` directory. Keep the following variable names; do not replace the system `HOME` variable:

```sh
API_ROOT="$HOME/Library/Application Support/MilaAPI"
mkdir -p "$API_ROOT"
chmod 700 "$API_ROOT"
cp app.py pytest.ini requirements.lock configure.py verify.py LICENSE LICENSES.md "$API_ROOT/"
mkdir -p "$API_ROOT/tests"
cp tests/test_api.py "$API_ROOT/tests/"
/opt/homebrew/bin/python3.12 -m venv "$API_ROOT/.venv"
/opt/homebrew/bin/uv pip install \
  --python "$API_ROOT/.venv/bin/python" \
  -r "$API_ROOT/requirements.lock"
```

The bundle contains the actual companion code, not just configuration for a nonexistent Mila server. The dependency lock includes the verification and test tools.

## 5 Build whisper.cpp with Metal

The reference installation compiled a pinned whisper.cpp commit reporting **1.9.5-dev**. It is a development revision, not a stable release label. Pinning it reproduces the tested engine; review and revalidate before substituting another release.

```sh
API_ROOT="$HOME/Library/Application Support/MilaAPI"
git init "$API_ROOT/engine-source"
git -C "$API_ROOT/engine-source" remote add origin \
  https://github.com/ggml-org/whisper.cpp.git
git -C "$API_ROOT/engine-source" fetch --depth 1 origin \
  d1be6fde11ac6e0407606b4e42fe72d34add8037
git -C "$API_ROOT/engine-source" checkout --detach FETCH_HEAD
cmake -S "$API_ROOT/engine-source" \
  -B "$API_ROOT/engine-source/build" \
  -DCMAKE_BUILD_TYPE=Release \
  -DGGML_METAL=ON \
  -DGGML_METAL_EMBED_LIBRARY=ON
cmake --build "$API_ROOT/engine-source/build" \
  --target whisper-cli -j 2
"$API_ROOT/engine-source/build/bin/whisper-cli" --version
```

The original setup built the engine elsewhere and copied its executable and dynamic libraries, then changed their library paths to `@loader_path`. This generic layout builds directly in its permanent location, so that relocation step is unnecessary. Keep the build directory and its dynamic libraries together.

Do not quantize the Hebrew model or substitute a smaller Hebrew model. The companion uses Metal, two CPU threads, normal beam/best-of settings of 5, and one inference process at a time. [whisper.cpp documents Apple Silicon and Metal support](https://github.com/ggml-org/whisper.cpp).

## 6 Generate private configuration and credentials

For access only from the same Mac:

```sh
API_ROOT="$HOME/Library/Application Support/MilaAPI"
"$API_ROOT/.venv/bin/python" "$API_ROOT/configure.py" --host 127.0.0.1
```

For Iris on another private machine, use a private LAN IP **assigned to this Mac**. Find it in System Settings → Network, then run:

In macOS's default Zsh shell:

```sh
read 'API_BIND_IP?Enter this Mac private LAN IP: '
API_ROOT="$HOME/Library/Application Support/MilaAPI"
"$API_ROOT/.venv/bin/python" "$API_ROOT/configure.py" --host "$API_BIND_IP"
```

Do not use `0.0.0.0`, a public IP, or router port forwarding. Reserve the Mac's LAN address in DHCP so it does not change. If using a Tailscale IP, it must be assigned to the Mac and available when the service starts; this binds only that address, not both LAN and Tailscale.

The script creates:

| File or directory | Purpose |
| --- | --- |
| `~/.config/mila-api/config.json` | Per-machine paths, bind address and API key |
| `~/.config/mila-api/api-key.txt` | Client's Bearer API key |
| `~/Library/LaunchAgents/io.local.mila-api.plist` | Login service definition |
| `~/Library/Application Support/MilaAPI/tmp` | Temporary uploaded audio |
| `~/Library/Application Support/MilaAPI/logs` | Service logs |

Keys/configuration have permission `600`; private directories have permission `700`. The installer generates a new key on each fresh machine and preserves an existing key when rerun. No key is included in the shareable bundle. The engine's Git checkout contains no credentials.

Plain LAN HTTP is unencrypted even with an API key. Use a trusted LAN or a separately configured private TLS/Tailscale path for transport protection. Public exposure is not part of this installation.

## 7 Start and supervise the API with launchd

```sh
launchctl bootstrap "gui/$(id -u)" \
  "$HOME/Library/LaunchAgents/io.local.mila-api.plist"
launchctl print "gui/$(id -u)/io.local.mila-api"
```

This is a user **LaunchAgent**: it starts at login, is restarted after crashes, and stops at logout. It does not run before the first login after a reboot. `Nice=10` reduces its CPU scheduling priority. Do not start a second API process manually alongside it.

After changing configuration or code:

```sh
launchctl kickstart -k "gui/$(id -u)/io.local.mila-api"
```

If bootstrap says the service is already loaded, use `kickstart`; do not repeatedly bootstrap it.

## 8 Verify health and real transcription

Run:

```sh
API_ROOT="$HOME/Library/Application Support/MilaAPI"
cd "$API_ROOT"
"$API_ROOT/.venv/bin/python" -m pytest -q
"$API_ROOT/.venv/bin/python" "$API_ROOT/verify.py"
```

The unit suite should report 9 passed. The API verification checks health, authentication, the bundled public Hebrew sample, the whisper.cpp English sample and invalid audio rejection. Hebrew should contain `שלום עולם`. The key is read from the private configuration and is not printed.

Verify the actual GPU backend with a direct sample:

```sh
API_ROOT="$HOME/Library/Application Support/MilaAPI"
"$API_ROOT/engine-source/build/bin/whisper-cli" \
  -m "$HOME/Library/Application Support/Mila/Models/ivrit-ai-whisper-large-v3.bin" \
  -f /Applications/Mila.app/Contents/Resources/ConnectionTestSample.wav \
  -l he -t 2 -bs 5 -bo 5
```

Its diagnostics should show a GPU device such as `MTL0`. An engine compiled with Metal can still fall back to CPU if GPU initialization fails, so inspect the actual diagnostics. Do not run this direct test concurrently with an API transcription.

When the service is idle, test crash recovery:

```sh
launchctl kill SIGKILL "gui/$(id -u)/io.local.mila-api"
```

Wait a few seconds, inspect `launchctl print` for a new PID, and rerun `verify.py`. Do this only when no real audio job is running.

Also test `/healthz` from the machine hosting Iris. A successful request from the Mac itself does not prove the remote client can reach it. Check macOS firewall rules if remote requests fail; allow only the required private access.

## 9 Configure the client

Replace `<MAC_PRIVATE_IP>` with the configured bind address. These are templates, not real addresses:

```text
Base URL:       http://<MAC_PRIVATE_IP>:8081/v1
Transcription:  http://<MAC_PRIVATE_IP>:8081/v1/audio/transcriptions
Health:         http://<MAC_PRIVATE_IP>:8081/healthz
Models:         http://<MAC_PRIVATE_IP>:8081/v1/models
Authentication: Authorization: Bearer <API_KEY>
```

Use multipart fields:

| Use | model | language |
| --- | --- | --- |
| Hebrew with one inference pass | `ivrit-large-v3` | `he` |
| English with one inference pass | `large-v3-turbo` | `en` |
| Unknown Hebrew or English | `auto` | `auto` |

With automatic selection, the multilingual model runs first. If it detects Hebrew, the full ivrit.ai model runs afterward. Explicit `he` or `en` avoids the additional pass. Very short or mixed-language clips can be misdetected; automatic routing is not an accuracy guarantee.

The request needs `file`; `response_format` can be `json`, `verbose_json` or `text`. `temperature` must be zero. JSON contains `text`, `language`, `duration` and `model`; verbose JSON adds timestamped segments. A `/inference` alias accepts the same requests and key.

The API limits files to 25 MiB and audio to 5 minutes. Iris extracts video audio to MP3 before calling this API; this path has been verified. Direct MP4 upload returned HTTP 422 in the live reference check, so do not rely on direct video uploads without validating your installation. Video frames are not inspected. It allows one running request and one additional waiting request. Larger bursts get HTTP 429 and should retry.

**Iris supports the local transcription provider.** Configure `local_whisper` and `IRIS_WHISPER_URL` with this service's endpoint and Bearer key. Failed, empty or malformed transcription remains failed or requires review. This bundle installs the transcription API; it does not install Iris or OpenWA.

## 10 Keep idle resource use low

Each request starts a native model process that exits afterward. That frees model memory while idle, at the cost of loading the model for the next request. Quit Mila's desktop app when only the API is needed. Avoid loading another large local AI model concurrently when RAM is tight.

Reference tests measured about 36 MiB idle API resident RAM and 3.75 GiB peak resident RAM for a short Hebrew test. Unified GPU memory and overall system pressure also matter. The first Metal run can spend extra time compiling kernels. These figures are observations, not guarantees for every Mac or clip.

For a desktop Mac that must remain available, inspect the current settings:

```sh
pmset -g custom
```

The reference Mac already had computer sleep disabled. To deliberately configure an always-available desktop while allowing its display to sleep:

```sh
sudo pmset -c sleep 0 displaysleep 10
```

Record the previous values first so you can restore them. This changes AC-power settings; it does not enable pre-login service startup. For a laptop, consider power and battery requirements separately. If the Mac sleeps or the user logs out, the API is unavailable.

## 11 Backup update and uninstall

Back up the companion source, dependency lock, launchd plist and private configuration securely. Keep keys out of Git and shared archives. Models can be downloaded again; audio in `tmp` is temporary and is deleted after requests or during startup cleanup.

Before an update, stop the service:

```sh
launchctl bootout "gui/$(id -u)" \
  "$HOME/Library/LaunchAgents/io.local.mila-api.plist"
```

Back up the current version, install reviewed dependencies or a reviewed engine revision, then repeat unit, Hebrew, English, authentication and restart checks. Start it again with the bootstrap command. Updating the desktop app does not update this companion engine. Do not delete the shared models through Mila while the API relies on them.

To uninstall, boot out the service and move its plist and `MilaAPI` directory to Trash. Remove `~/.config/mila-api` only when its key is no longer needed. This leaves Mila's application, recordings and shared models intact. Do not uninstall Homebrew packages used by other software.

## 12 Troubleshoot common failures

| Symptom | Check |
| --- | --- |
| Connection refused | Login service status, configured IP, port conflicts and `logs/api.log` |
| Health 503 | Engine executable and both model files exist |
| HTTP 401 | Exact Bearer API key; do not place it in the URL |
| HTTP 413 | Upload is within 25 MiB and 5 minutes |
| HTTP 415 | Input contains a supported real audio/video container |
| HTTP 422 | Decode failure, silence, unusable speech or unsupported detected language; require review |
| HTTP 429 | Retry after the indicated delay; reduce concurrent client workers |
| HTTP 504 | Native inference timed out; review or retry a shorter clip |
| High CPU during inference | Verify Metal initialized; two CPU threads still perform some work |
| High RAM | Full Hebrew weights require several GB; quit the GUI and other large model processes |

The API does not log transcripts or API keys. Diagnostic logs still belong in a private directory. Never resolve an error by silently switching to cloud transcription or treating unprocessed audio as safe.

## License files and bounded logs

The companion source files are [app.py](app.py), [configure.py](configure.py), [verify.py](verify.py), [tests/test_api.py](tests/test_api.py) and [requirements.lock](requirements.lock). Keep [LICENSE](LICENSE) and [LICENSES.md](LICENSES.md) alongside them.

The updated API rotates `logs/api.log` at 10 MiB, retaining five older files. launchd redirects bootstrap stdout/stderr to `/dev/null`; if startup fails before logging initializes, stop the agent and run the API in Terminal using its private `MILA_API_CONFIG` to diagnose it, then restart the agent. The API does not log transcripts or credentials.

For an existing installation, first boot out the agent using section 11, copy the updated `app.py`, `configure.py`, `LICENSE` and `LICENSES.md` into `MilaAPI`, rerun `configure.py` with the existing bind IP (the key is preserved), then bootstrap it and run section 8 verification. Existing engine/model/tool paths are preserved by the updated configure script. Do not change bind IP or engine paths without checking them. This is a manual update: Iris does not install Mac files remotely. Old `service.log` and `error.log` can be archived or removed after the stopped agent closes them.
