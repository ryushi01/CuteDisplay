# Kitty V6: single public S3 endpoint (Ragnarok HTTPS/443)

**Required network policy:** S3 application traffic for realtime AI, memory sync and updates must use only `ragnarok-project.com:443`. DNS resolution and local Wi-Fi association are prerequisites, not extra application endpoints. Do not expose Ubuntu's ports 8766, 8843, 8772 or 8890 to the internet.

## Firmware

- Voice preflight accepts only `https://ragnarok-project.com` with an optional path; port is implicitly 443.
- SD snapshots: `KITTY_SYNC_V6_URL="https://ragnarok-project.com/kitty-v6/sync"`, with a separate strong `KITTY_SYNC_V6_DEVICE_TOKEN`.
- The CA PEM must validate the *public Ragnarok certificate chain* (not the Ubuntu private self-signed certificate). Do not disable hostname verification or call `setInsecure()`.
- Do not put secrets in committed firmware, GitHub Actions logs or public artifacts. Provision through untracked, local `KittySyncPrivateConfig.h`.
- The existing `server/kitty_ota_client_v6.py` opens a **LAN socket to the S3**, and does **not** satisfy the new policy. It must not be used as the S3 production update path. The Update Center is presently quarantine/preflight only. Implement an authenticated **S3-initiated HTTPS/443 poll/download** with signed manifest, staging, tested rollback and manual authorization before enabling remote updates. Never proxy the raw LAN OTA socket through public HTTPS.

## Reverse proxy route (merge into existing Ragnarok 443 server)

Use the existing TLS vhost and certificate for `ragnarok-project.com`. Example Nginx *location* blocks; do not replace an existing Open WebUI location or its WebSocket settings:

```nginx
location = /kitty-v6/sync/snapshot/chunk {
    client_max_body_size 16k;
    proxy_pass https://127.0.0.1:8843/snapshot/chunk;
    proxy_ssl_trusted_certificate /home/ryushi/kitty-v6/private/tls/gateway.crt;
    proxy_ssl_verify on;
    proxy_ssl_verify_depth 2;
    proxy_ssl_server_name on;
    proxy_ssl_name kitty-v6-sync;
    proxy_set_header Authorization $http_authorization;
    proxy_set_header Content-Type application/json;
    proxy_set_header Host kitty-v6-sync;
    proxy_connect_timeout 3s;
    proxy_read_timeout 10s;
}
location = /kitty-v6/sync/snapshot/finalize {
    client_max_body_size 16k;
    proxy_pass https://127.0.0.1:8843/snapshot/finalize;
    proxy_ssl_trusted_certificate /home/ryushi/kitty-v6/private/tls/gateway.crt;
    proxy_ssl_verify on;
    proxy_ssl_server_name on;
    proxy_ssl_name kitty-v6-sync;
    proxy_set_header Authorization $http_authorization;
    proxy_set_header Content-Type application/json;
    proxy_set_header Host kitty-v6-sync;
    proxy_connect_timeout 3s;
    proxy_read_timeout 10s;
}
location ^~ /kitty-v6/ {
    return 404;
}
```

**Do not apply this snippet unchanged without inspecting the installed reverse proxy:** it may be Caddy, Nginx, Traefik, Cloudflare or another route manager. Check filesystem permissions to the private CA before reloading. If a CDN, WAF or public reverse proxy sits in front, configure it to allow these private authenticated endpoints only with strict limits and never cache responses. Verify the proxy can reach its localhost backend and that the hostname/certificate match. If safe exposure cannot be guaranteed, use a private tunnel on port 443 rather than publishing the sync path.

## Production release gate

1. Confirm the existing 443 ingress implementation and route ownership.
2. Configure the public-domain snapshot routes and verify token auth end-to-end.
3. Compile the firmware with a local untracked cert bundle and token, ensuring no public CI artifact embeds live credentials.
4. Produce a real SD snapshot; verify checksum and successful server index refresh.
5. Verify realtime multilingual recall and speaker attribution with unknown speakers remaining unverified.
6. Design and validate S3-initiated 443-only update transport before changing the updater deployment state.
