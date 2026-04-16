# Cloudflare DNS Migration — `survivethetalk.com`

**Date:** 2026-04-16
**Trigger:** Story 4.2 (passwordless auth) needs a functional sender email address — `noreply@survivethetalk.com`. GoDaddy's built-in Website Builder placeholder plus stale Mailgun/Mailo default records made DNS hygiene a prerequisite.
**Status:** Complete. Resend validated post-migration (SPF/DKIM/DMARC all PASS).

---

## Why

- Needed `noreply@survivethetalk.com` as Resend `from` address for auth codes.
- Needed a way to receive human mail (`contact@`, `hello@`) without running a mail server.
- GoDaddy DNS had noise: Mailgun MX + SPF, Mailo DKIM, SES SPF, Website Builder A record — none used.
- Cloudflare offers free DNS management + free Email Routing (forwarding only, no mailbox, no SMTP sending).

## What changed

### Registrar
- **Unchanged.** GoDaddy remains the registrar (domain ownership + WHOIS).

### Nameservers (GoDaddy side)
- Before: `ns17.domaincontrol.com`, `ns18.domaincontrol.com`
- After: `conrad.ns.cloudflare.com`, `keira.ns.cloudflare.com`

### DNS zone (now managed at Cloudflare)

Final state — **10 records**:

| Type | Name | Value | Purpose |
|---|---|---|---|
| MX | `send` | `feedback-smtp.eu-west-1.amazonses.com` (pri 10) | Resend (SES) bounces |
| TXT | `send` | `v=spf1 include:amazonses.com ~all` | SPF for Resend's `send.` subdomain |
| TXT | `dc-fd741b8612._spfm.send` | `v=spf1 include:amazonses.com ~all` | Resend SPF macro |
| TXT | `resend._domainkey` | `p=MIGfMA0...` (RSA public key) | Resend DKIM |
| TXT | `_dmarc` | `v=DMARC1; p=quarantine; adkim=r; aspf=r; rua=mailto:dmarc_rua@onsecureserver.net` | DMARC policy |
| MX | `@` | `route1.mx.cloudflare.net` (pri 80) | Cloudflare Email Routing |
| MX | `@` | `route2.mx.cloudflare.net` (pri 35) | Cloudflare Email Routing |
| MX | `@` | `route3.mx.cloudflare.net` (pri 3) | Cloudflare Email Routing |
| TXT | `@` | `v=spf1 include:_spf.mx.cloudflare.net ~all` | SPF for Cloudflare Email Routing |
| TXT | `cf2024-1._domainkey` | Cloudflare DKIM public key | Cloudflare Email Routing DKIM |

### Removed (stale/default records)
- GoDaddy Website Builder A record (`@` → WebsiteBuilder Site)
- Mailgun: MX `mxa.mailgun.org` + `mxb.mailgun.org`, SPF include, CNAME `email → mailgun.org`
- Mailo DKIM (`mailo._domainkey`)
- `_domainconnect` CNAME (GoDaddy-specific)
- `www` CNAME (no website yet)

### Email Routing rules (Cloudflare)
- `contact@survivethetalk.com` → `guetarni.walid@gmail.com`
- `hello@survivethetalk.com` → `guetarni.walid@gmail.com`
- Catch-all: "Send to email" → `guetarni.walid@gmail.com` (any unknown local-part gets caught)

## Validation tests performed

### Test A — Inbound (Cloudflare Email Routing)
- Sent from external Gmail to `contact@survivethetalk.com` and `hello@survivethetalk.com`.
- Both delivered to `guetarni.walid@gmail.com`. Activity Log in Cloudflare showed "Forwarded".
- Initial misconfiguration: catch-all was set to "Drop" — changed to "Send to email" and retest passed.

### Test B — Outbound (Resend via `noreply@survivethetalk.com`)
- POST `https://api.resend.com/emails` with `from: surviveTheTalk <noreply@survivethetalk.com>`, `to: guetarni.walid@gmail.com`.
- Resend returned `{"id":"d9ce15a2-3758-4a74-91dc-3fcef79c05ed"}`.
- Gmail headers confirmed:
  - `spf=pass` (via `send.survivethetalk.com` → SES `54.240.3.16`)
  - `dkim=pass header.i=@survivethetalk.com header.s=resend`
  - `dkim=pass header.i=@amazonses.com` (double signature)
  - `dmarc=pass (p=QUARANTINE sp=QUARANTINE dis=NONE) header.from=survivethetalk.com`

**Conclusion:** Resend's DKIM keying survived the nameserver change because the `resend._domainkey` TXT record was preserved verbatim in the Cloudflare zone.

## Impact on later stories

### Story 10.2 — Provision Domain DNS SSL and Server Infrastructure (backlog)

Original scope anticipated full DNS bootstrap. After this migration:
- ✅ DNS provider decided and configured (Cloudflare)
- ✅ Email Routing operational (`contact@`, `hello@`)
- ✅ Resend DNS records validated (SPF/DKIM/DMARC PASS)
- ⏳ Still in scope: SSL certs for API domain (probably `api.survivethetalk.com` → Cloudflare proxy + origin cert on VPS or Let's Encrypt via Caddy), `@` A/AAAA records if a marketing site is added later, production worker pool config (unrelated to DNS).

Story 10.2's author (future SM pass) should read this note and narrow the story accordingly.

### Story 4.2 — no change
`config.py` default `RESEND_FROM_EMAIL=noreply@survivethetalk.com` is ready to ship. No code update needed.

## Known follow-ups

1. **🚨 Revoke exposed Resend API key.** During the sending test, key `re_MRCEWcDK_P9Mykq29kjmKM3qNw9dv8y75` was pasted into a terminal error output and is in conversation history. User chose to defer revocation. **Must be revoked** before the new key is committed in `.env` (local-only, git-ignored) for Story 4.2 dev work.

2. **Subdomain for API.** Before Story 10.2, decide whether API lives at `api.survivethetalk.com` or `survivethetalk.com/api` (current VPS uses Caddy on port 80 by IP — no DNS record pointing to it yet).

3. **DMARC policy.** Currently `p=quarantine`. Once at steady state (a few months post-launch), tighten to `p=reject` for stronger anti-spoofing guarantees.
