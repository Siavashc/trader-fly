# Trader Fly — run forever on ClawCloud Run (free, no card)

## Why ClawCloud
Recurring **$5/month credit** from a GitHub login, **no credit card**. Real
24/7 container (no sleep), **persistent volume**, public HTTPS URL.
0.5 vCPU + 1 GB RAM + 1 GB volume ≈ **$4.15/mo → inside the free $5**.
(HF Spaces went paywalled for Docker in July 2026; Render/Koyeb sleep and are
too small for brian2; everything else needs a card.)

## One-time setup

1. **Push the image** (automatic once the repo is on GitHub):
   - repo has `.github/workflows/docker.yml` → builds → pushes to
     `ghcr.io/<user>/trader-fly:latest` on every push to main.
   - Make the GitHub repo **public** (or add an imagePullSecret on ClawCloud).

2. **Sign up**: https://run.claw.cloud → **Log in with GitHub**
   (account must be ~180+ days old for the recurring $5; check Billing page
   shows $5.00 credit every month).

3. **Create the app** (App Launchpad → Create):
   - Image: `ghcr.io/<user>/trader-fly:latest`
   - CPU: **0.5**, Memory: **1 GB**
   - Network: expose port **8791**, enable public access → note the URL
     `https://<something>.run.claw.cloud`
   - **Persistent volumes (2)**:
     - mount `/<app>/data` → container path `/app/data`
     - mount `/<app>/user_states` → container path `/app/user_states`
   - Environment variables:
     | key | value |
     |-----|-------|
     | `BOT_TOKEN` | the bot token (get from the local `.env`, do NOT bake into image) |
     | `PORT` | `8791` |
     | `HOST` | `0.0.0.0` |
     | `BASE_URL` | the public URL from the Network tab |
   - Replicas: 1. Deploy.

4. **Verify**: open `https://<url>/health` → `{"ok": true, ...}`; then message
   the bot → /status. Mini App button points at the same URL.

## Local machine keeps working in parallel? NO.
**Only ONE instance may poll** — stop `start_trader.ps1` locally once the
cloud one is live, or Telegram get_updates will 409-conflict and both crash.
The local copy stays as the emergency backup: to fail over, stop the cloud
app and run `start_trader.ps1` here.

## What survives what
- `data/` + `user_states/` are on the persistent volume → position, ledger,
  brain memory survive restarts/redeploys.
- Seed state (current ledger + brain) is baked into the image for a fresh boot.
- The fly's frozen LONG from 9/24 will be marked against the live price on
  first cloud boot.

## Watch-outs
- Credit meter: Billing → Usage. If it approaches $5, drop RAM to 0.75 GB.
- If the container OOMs (brian2 peak), ClawCloud restarts it — state survives.
- ghcr image is public → code is public, but **no secrets in the image**
  (.env is dockerignored; token arrives via env var only).