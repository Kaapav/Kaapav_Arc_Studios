# KAAPAV Control Room

Colourful neumorphic Flutter client for the KAAPAV ARC Studios control plane.

## Targets

- Windows: reads the localhost dashboard API directly.
- Android: reads `https://yt.kaapav.com` through the secure read-only tunnel.

Ready-to-use packages are in `D:\Apps\YT-Auto\flutter\releases`:

- `KAAPAV-Control-Room-Windows.zip`
- `KAAPAV-Control-Room-Android.apk`

## Security

- Remote access is read-only; server-side POST controls return HTTP 403.
- First Android use requires a single-use 60-second pairing code created on the authorized studio PC.
- The signed session expires after seven days and contains no Google or Cloudflare credentials.
- The browser dashboard remains the independent fallback.

## Validate

```powershell
D:\flutter\bin\flutter.bat analyze
D:\flutter\bin\flutter.bat test
D:\flutter\bin\flutter.bat build windows --release
D:\flutter\bin\flutter.bat build apk --release
```
