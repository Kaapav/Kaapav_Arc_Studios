# KAAPAV ARC Studios — Safe Codex Handoff

This folder transfers project context, not authentication.

## Same computer, another Codex account

1. Sign into the other account.
2. Open `D:\Apps\YT-Auto` as the project folder.
3. Paste the contents of `KAAPAV_MEMORY_CODE.md` into the first task.
4. Ask Codex to run the universe audit before changing anything.
5. Reauthorize YouTube or other connections only if the new account/session requests it.

The project-level `AGENTS.md` supplies durable instructions whenever Codex opens this folder.

## Different computer

Copy the project content and source files through your own secure method, but exclude `.env`, `credentials/`, OAuth tokens, client secrets, service-account keys and private keys. Install dependencies, provide fresh credentials locally, and run the audit before production.

## Important distinction

This is a handoff code, not a hidden account-memory export. It works because the project carries its own instructions, manifests, bibles and evidence. The official OpenAI import documentation also notes that imported plugins or connections may need authorization again.

## Verification

Run:

```powershell
.\.venv\Scripts\python.exe -u audit_studio_universe.py
```

Expected structural result: PASS, 10 series, 300 episode manifests and 2,340 scene scripts. Pending images/videos must remain upload-blocked.
