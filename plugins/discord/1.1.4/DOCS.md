# Discord Plugin

Control Discord mute and deafen from any button on your deck.

---

## How it works

The Discord plugin connects to the **local Discord desktop client** via Discord's IPC socket (no cloud request on every button press). It uses OAuth2 to obtain an access token with the `rpc`, `rpc.voice.read`, and `rpc.voice.write` scopes, then keeps a persistent authenticated socket open so toggle actions are instant.

---

## Prerequisites

- The **official Discord desktop app** installed and running on the same machine as PyDeck
- A Discord account with Developer Mode available
- PyDeck running (default port `8686`)

> **The Discord plugin uses Discord's IPC socket, which is only exposed by the official desktop client.**
>
> The following will **not** work:
> - **Browser Discord** (`discord.com/app`) — no IPC socket is available in a browser tab
> - **Vencord, BetterDiscord, or any other modified client** — these clients do not reliably expose the IPC socket that the RPC protocol depends on
> - **Discord PTB / Canary** — may work, but is not officially supported and behaviour may differ
>
> If you are currently using a modified client, switch to the official release build of Discord before authorising.

---

## Step 1 — Create a Discord application

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Click **New Application** → give it a name (e.g. `PyDeck`)
3. Open the application you just created

---

## Step 2 — Enable RPC and add a redirect URI

1. In the left sidebar click **OAuth2**
2. Under **Redirects** click **Add Redirect** and enter exactly:
   ```text
   http://127.0.0.1:8686/oauth/discord/callback
   ```
3. Click **Save Changes**

> **Important:** Use `127.0.0.1`, not `localhost`. OAuth providers do exact-string
> matching and PyDeck sends `127.0.0.1` in the token exchange request.

---

## Step 3 — Copy your credentials

Still on the **OAuth2** page:

- Copy **Client ID** — you will need this in PyDeck
- Click **Reset Secret**, confirm, then copy **Client Secret**

Keep the Client Secret private — treat it like a password.

---

## Step 4 — Enter credentials in PyDeck

1. Open PyDeck in your browser (`http://127.0.0.1:8686`)
2. Click the **Settings** icon in the deck header
3. Navigate to **Credentials → Discord**
4. Paste your **Client ID** and **Client Secret**
5. Click **Save**

---

## Step 5 — Authorize

1. Still in **Settings → Credentials → Discord**, click **Authorize**
2. Your browser opens Discord's OAuth page — log in if prompted
3. Click **Authorize** on the Discord consent screen
4. The browser redirects back to PyDeck automatically
5. You will see **"Discord connected! You can close this tab."**

PyDeck stores the access and refresh tokens in
`~/.config/pydeck/core/credentials.json`. The token refreshes automatically — you should only need to authorise once.

---

## Step 6 — Add buttons to your deck

1. Drag **Discord Mute** or **Discord Deafen** onto any button slot
2. Press the button — the button image switches between the muted/unmuted state images

The plugin polls Discord's voice state every 10 seconds and keeps the button image in sync even if you mute/deafen from inside Discord itself.

---

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `redirect_uri: Not matching configuration` | Redirect URI in Discord portal doesn't match | Ensure it is exactly `http://127.0.0.1:8686/oauth/discord/callback` |
| `Discord IPC socket not found` | Discord is not running, or you are using a browser / modified client | Start the **official** Discord desktop app; browser and modified clients (Vencord, BetterDiscord) do not expose the IPC socket |
| `Authentication failed` | Token is invalid or expired | Go to Settings → Credentials → Discord and click **Authorize** again |
| `Not authorized` | No token saved yet | Complete Step 5 (Authorize) |
| Button image stuck after mute inside Discord | Poll hasn't fired yet | State syncs within ~10 s |

---

## Required Discord application scopes

| Scope | Purpose |
|---|---|
| `rpc` | Connect to the local Discord client via IPC |
| `rpc.voice.read` | Read current mute / deafen state |
| `rpc.voice.write` | Toggle mute / deafen |

These are requested automatically during the Authorize step — you do not need to configure them manually.
