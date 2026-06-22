# GoDaddy DNS Cutover — `survivethetalk.com` (Story 10.2)

**Date:** 2026-06-22
**Why:** The live DNS zone is on a Cloudflare account whose login could not be located (NS pair `conrad`/`keira`; neither `guetarni.walid@gmail.com` — its CF account is empty — nor `team@kindopia.com` — only `myselfmonart.com`, NS `carioca`/`charles` — shows it; Resend account is under `guetarni.walid@gmail.com`). Walid **owns the domain at GoDaddy (`team@kindopia.com`)**, so we take DNS back by switching nameservers from Cloudflare to **GoDaddy's own DNS** and recreating the zone, then add the `api` records that unblock Story 10.2.

**Trade-off accepted:** We DROP Cloudflare Email Routing (inbound `contact@`/`hello@` → Gmail forwarding stops). Non-critical: the app's published contact is `guetarni.walid@gmail.com` directly; forwarding can be re-added later. **Outbound login-code emails (Resend) are preserved** by recreating the 5 Resend/DMARC records below.

## Records to CREATE in GoDaddy DNS (exact, captured live via dig 2026-06-22)

| Type | Host/Name | Value | Priority |
|---|---|---|---|
| A | `api` | `167.235.63.129` | — |
| AAAA | `api` | `2a01:4f8:1c18:fbfd::1` | — |
| MX | `send` | `feedback-smtp.eu-west-1.amazonses.com` | 10 |
| TXT | `send` | `v=spf1 include:dc-fd741b8612._spfm.send.survivethetalk.com ~all` | — |
| TXT | `dc-fd741b8612._spfm.send` | `v=spf1 include:amazonses.com ~all` | — |
| TXT | `resend._domainkey` | `p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC9ZFnH8epPY/X+9CuOgDUdvvB+Yotmw1YbLEnjcR7MV8bJUP7jkS+h9Jh95cnJFmp+qLge7C/ZcESPJxUgsxdGfUPD1CTx8P0XNTDEeO4ll2L3rg8L91OI0POUsKPt8zZfU/MYmh+mImQMjocyQcYX9e2vnRbYr5r4jJ01OfhnRwIDAQAB` | — |
| TXT | `_dmarc` | `v=DMARC1; p=quarantine; adkim=r; aspf=r; rua=mailto:dmarc_rua@onsecureserver.net;` | — |

Optional anti-spoofing on the apex (not required — DMARC passes via DKIM alignment): TXT `@` = `v=spf1 -all`.

## Records to DROP (Cloudflare Email-Routing only — won't work off Cloudflare)

- MX `@` → `route1/2/3.mx.cloudflare.net`
- TXT `@` → `v=spf1 include:_spf.mx.cloudflare.net ~all`
- TXT `cf2024-1._domainkey` → Cloudflare Email-Routing DKIM (`v=DKIM1; ... p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8A...`)

## Procedure

1. GoDaddy → product `survivethetalk.com` → **Nameservers** → change from Custom (`conrad`/`keira.ns.cloudflare.com`) to **GoDaddy default nameservers**. (This makes GoDaddy authoritative and creates a fresh default zone.)
2. GoDaddy → **DNS records**: delete the default parked records (parked `A @`, `CNAME www`, `_domainconnect` are fine to remove), then add the 7 records above.
3. Verify each via `dig`: `dig +short A api.survivethetalk.com`, `dig +short AAAA api...`, `dig +short TXT resend._domainkey...`, `dig +short MX send...`, `dig +short TXT _dmarc...`.
4. Once `api` resolves to `167.235.63.129`, the agent runs Story 10.2 Task 3 (Caddy domain config → Let's Encrypt) + Task 4 (client base-URL flip).

**Re-verify outbound email after cutover:** trigger one app login code → confirm it still arrives (Resend DKIM/SPF intact).

## Source of truth for the original Cloudflare zone
See `cloudflare-dns-migration-2026-04-16.md` (same folder) — the 16-April migration note that documented the 10 original records.
