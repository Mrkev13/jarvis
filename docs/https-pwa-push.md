# HTTPS via Tailscale Serve, installable PWA and Web Push (MRK-24)

Browsers allow PWA installation and Web Push only in a secure context (HTTPS, or `localhost` on the same machine).
Standa Hub gets HTTPS **inside the tailnet only** through Tailscale Serve. It is never exposed to the internet:
**no Funnel**, no router port forwarding, no public DNS.

## Architecture

| Browser URL (tailnet only) | Tailscale Serve upstream | Service |
|---|---|---|
| `https://<host>.<tailnet>.ts.net/` | `http://127.0.0.1:3000` | Next.js frontend (`StandaHub-Frontend`) |
| `https://<host>.<tailnet>.ts.net:8443/` | `http://127.0.0.1:8000` | FastAPI backend (`StandaHub-Backend`) |

- Tailscale terminates TLS with an automatically issued and renewed certificate for the MagicDNS name, then proxies to
  loopback. The MRK-23 runtime (Task Scheduler, start scripts, ports 3000/8000) is unchanged; it just becomes the
  internal upstream.
- **Why two ports, not one origin with `/api`:** the browser already talks to the backend cross-origin with a CORS
  allowlist and credentialed requests. Same-origin would need a separate server-side API URL for the Next auth
  proxy, rely on Serve path-prefix semantics, and put SSE (`/events/stream`) behind an extra hop. It gains no
  security: both variants are tailnet-only TLS. The session cookie is host-only, and cookies ignore ports, so the
  frontend's auth gate on `:443` sees the cookie the API on `:8443` set.
- After acceptance, both services bind to `127.0.0.1` (`register-tasks.ps1 -BindAddress 127.0.0.1`). Plain HTTP on
  the tailnet IP then stops working, and Serve is the only way in.

## Prerequisites (once per tailnet)

In the Tailscale admin console, under DNS: **MagicDNS** on and **HTTPS Certificates** enabled. Check:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\tailscale-serve.ps1 -Mode Status
```

`Status` fails with "HTTPS certificates are not enabled" until that is done. Exit codes: `0` = both routes as
expected (after `Reset`: both removed), `2` = routes missing or pointing elsewhere, `1` = error (CLI failed or not
elevated, certificates off, or **Funnel on**). Funnel is detected anywhere in the Serve config, foreground sessions
included. `Apply` refuses to run and every mode ends with an error while it is on. `Reset` still removes our
listeners first, so rollback works. `Apply` never overwrites a port that already serves a different upstream, and
`Reset` removes only listeners that point at `127.0.0.1:3000`/`:8000`.

## Tailscale Serve: apply, inspect, remove

Run in an elevated PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\tailscale-serve.ps1 -Mode Apply    # idempotent
powershell -ExecutionPolicy Bypass -File scripts\windows\tailscale-serve.ps1 -Mode Status
powershell -ExecutionPolicy Bypass -File scripts\windows\tailscale-serve.ps1 -Mode Reset    # only these two ports
tailscale serve status                                                                     # raw view; must say "(tailnet only)"
```

Tailscale stores the Serve config itself, so it survives service, Tailscale and machine restarts. Re-run
`-Mode Apply` after a Tailscale reinstall, logout/login, or a machine/tailnet rename. Applying Serve alone changes
nothing for existing HTTP access.

## Cutover (production, elevated, no reboot)

1. **Backup** through the canonical pipeline (`docs/backups.md`).
2. **Apply Serve** (above). Check with
   `scripts\windows\check-health.ps1 -BackendUrl https://<host>.<tailnet>.ts.net:8443 -FrontendUrl https://<host>.<tailnet>.ts.net`.
3. **Backend `.env.production`**, edited in place so its ACL stays:
   - `FRONTEND_ORIGINS`: add `https://<host>.<tailnet>.ts.net`. Keep `http://127.0.0.1:3000` for local checks.
   - `AUTH_COOKIE_SECURE=true`. `production.py` refuses an https origin without it, and `true` without any https
     origin.
   - `EXTERNAL_DELIVERY_ENABLED=true` and `REMINDERS_CHECK_ENABLED=true`, with the VAPID keys present (see below).
4. **Frontend `.env.production.local`**: `NEXT_PUBLIC_API_URL=https://<host>.<tailnet>.ts.net:8443`. This is the only
   frontend value; never an `http://` URL on an https page.
5. Stop both tasks, `start-frontend.ps1 -ProjectDirectory C:\StandaHub -Build`, start the backend, then the
   frontend. Check `/health` (commit, migration) and the HTTPS health check from step 2.
6. **Acceptance** (desktop first, then the phone on the tailnet):
   - log in over HTTPS;
   - install the PWA and launch it;
   - `/reminders` → **Zapnout upozornění** → **Test**, with the app not focused;
   - a reminder due in about 2 minutes arrives as a push, including with the phone locked.
7. **Close direct HTTP**: `register-tasks.ps1 -ProjectDirectory C:\StandaHub -BackendEnvFile <env> -BindAddress 127.0.0.1`,
   restart both tasks, then confirm `http://<tailnet-ip>:3000` and `:8000` are refused from another device while
   HTTPS still works.

Once the cookie is `Secure`, plain-HTTP access via the tailnet IP can no longer log in. That is intended: HTTPS is the
only browser entry.

## Rollback

1. Restore the previous `FRONTEND_ORIGINS`, `AUTH_COOKIE_SECURE=false`, previous `EXTERNAL_DELIVERY_ENABLED` and
   `NEXT_PUBLIC_API_URL=http://<tailnet-ip>:8000`.
2. If bound to localhost: `register-tasks.ps1 … -BindAddress 0.0.0.0`.
3. Rebuild the frontend and restart both tasks.
4. `tailscale-serve.ps1 -Mode Reset`.

No data migration is involved. Push subscriptions made over HTTPS stay in the DB, but are only usable from the HTTPS
origin.

## Certificate or hostname changed

- Certificate renewal is automatic (tailscaled). If the browser shows a certificate error, check `tailscale status`
  and the HTTPS Certificates setting, then re-run `-Mode Apply`.
- After a machine rename, a tailnet rename or a move to another device (e.g. the mini PC, MRK-27):
  - update `FRONTEND_ORIGINS` and `NEXT_PUBLIC_API_URL`, rebuild the frontend, re-run `-Mode Apply`;
  - reinstall the PWA (its origin changed) and re-enable notifications, since the subscriptions belong to the old
    origin.

## VAPID keys (server-side only)

- Generate once with `python backend/scripts/generate_vapid_keys.py`. Put `WEB_PUSH_VAPID_PRIVATE_KEY`,
  `WEB_PUSH_VAPID_PUBLIC_KEY` and `WEB_PUSH_CONTACT` **only** in the protected `backend\.env.production` (ACL:
  SYSTEM + Administrators). Never put them in git, Linear, logs or the frontend.
- The browser receives only the public key, from `GET /push/config` (session required).
- Rotating the keys invalidates every existing subscription: re-enable notifications on each device afterwards.

## PWA and service worker behaviour

- The manifest (`app/manifest.ts`, `/manifest.webmanifest`) has `id`/`scope`/`start_url` `/`, `standalone` display,
  and 192/512 px icons. The manifest, `sw.js` and icons are the only files the auth proxy serves without a session.
- **Install:**
  - desktop Chrome/Edge: the install icon in the address bar;
  - Android Chrome: menu → *Install app*;
  - iPhone/iPad (iOS 16.4+): Safari → Share → *Add to Home Screen*, then enable notifications **from the home-screen
    app**.
- `public/sw.js` handles only `push` and `notificationclick`. It has **no fetch handler and no Cache API**, so private
  data is always fetched live and never served stale from a cache. Clicks open only same-origin paths. Tests in
  `lib/pwa.test.mjs` enforce this.
- The worker is registered (scope `/`, `updateViaCache: "none"`) **only** when the user clicks *Zapnout upozornění*,
  and permission is asked only then, never on page load.
- **Updates:** browsers re-check `/sw.js` on navigation (at least daily). `skipWaiting` + `clients.claim` let the
  new version take over immediately. To remove: *Vypnout* on `/reminders` (unsubscribe + server-side disable) or
  the browser's site settings.

## Troubleshooting

- **Push toggle missing or "not supported":** the page isn't a secure context (open the `https://…ts.net` URL), or
  on iOS the app isn't installed to the home screen.
- **The test push works but reminders don't arrive:** check `EXTERNAL_DELIVERY_ENABLED=true`,
  `REMINDERS_CHECK_ENABLED=true`, that `/health` shows the reminders job `ok`, and `GET /push/status` (last
  delivery and its category).
- **Device silently stops receiving:** the push service answered 404/410, so the device was disabled. Enable
  notifications again on that device.
- **Nothing shows on Windows:** check Windows notification settings and Focus Assist / Do Not Disturb for the browser
  or installed app.
- **Login loops over HTTPS:** check `FRONTEND_ORIGINS` contains the exact https origin, `AUTH_COOKIE_SECURE=true`, and
  that the frontend was rebuilt after `NEXT_PUBLIC_API_URL` changed (it is baked in at build time).
