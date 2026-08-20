# KAAPAV ComfyUI one-click launcher

The Windows shortcut starts or reuses the private Kaggle kernel, waits for the
named Cloudflare tunnel to expose a healthy ComfyUI API, then opens
`https://comfy.kaapav.com/`.

The Kaggle kernel remains alive for up to ten hours, subject to Kaggle quota and
session limits. It uses the existing private `kaapav-models` dataset and the
existing `CF_TUNNEL_TOKEN` Kaggle secret. No credentials are stored locally in
this package.
