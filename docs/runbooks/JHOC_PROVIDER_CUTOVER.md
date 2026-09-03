# JHOC Provider Cutover

Start exactly one JHOC runtime first:

```powershell
$env:PYTHONPATH="G:\JHOC\src"
python G:\JHOC\scripts\jhoc_supervisor.py --db G:\JHOC\runtime\jhoc.db --port 8766
```

Then start each provider as a native JHOC client. The command is an argv JSON
array and is never interpreted by a shell:

```powershell
python G:\JHOC\scripts\jhoc_process_provider.py --provider-id codex-cli --command-json '["codex","exec"]'
python G:\JHOC\scripts\jhoc_process_provider.py --provider-id agy-cli --command-json '["agy","--print"]'
python G:\JHOC\scripts\jhoc_process_provider.py --provider-id deepseek-harness --command-json '["deepseek-harness"]'
```

Use the actual installed executable and flags for each provider. The adapter
does not import, start, stop, or inspect the legacy Agent Bus. A provider is
considered connected only after registration on port 8766; an accepted result
still requires a matching current workflow correlation and final status.

## Closed-loop probe

Run the deterministic transport probe after starting the runtime:

```powershell
$env:PYTHONPATH="G:\JHOC\src"
python G:\JHOC\scripts\jhoc_closed_loop.py
```

The generated artifact proves startup, provider registration, request delivery,
same-correlation final response, Relay ACK, and SQLite response restoration.
It is marked `probe_only=true` and `model_review_evidence=false`; simulated
handlers never satisfy the multi-model collaboration gate.

## Native readiness gate

Against a running JHOC endpoint, inspect only responses bound to one workflow:

```powershell
python G:\JHOC\scripts\jhoc_readiness.py --db G:\JHOC\runtime\jhoc.db --port 8766 --session-id <session-id>
```

The command reports transport, workflow, and collaboration gates separately.
Only at least two distinct providers with `status=accepted`, `final=true`,
matching `session_id`, and no `probe_only` marker can satisfy the collaboration
gate.

Dispatch a real workflow after provider clients are connected:

```powershell
python G:\JHOC\scripts\jhoc_dispatch.py `
  --provider codex-cli `
  --provider agy-cli `
  --provider deepseek-harness `
  --session-id <new-session-id> `
  --prompt "审查当前 JHOC 构建状态" `
  --artifact G:\JHOC\docs\acceptance\artifacts\jhoc-dispatch-latest.json
```

This command is the executable closed-loop step. It fails closed unless at
least two distinct providers return accepted final responses bound to the same
session. A timeout, provider failure, or mismatched session remains rejected.
