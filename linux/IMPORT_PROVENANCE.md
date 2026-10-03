# Import Provenance

## Source

- Repository: kolmaf-ai (standalone source)
- Branch: main
- Commit: a0299b8fbd5f41aaf8a2e1c09da47b109ba6c744
- Import date: 2026-10-03
- Import mode: Snapshot from working tree (no history merge)

## Classification summary

| Category | Count | Disposition |
| --- | --- | --- |
| FORBIDDEN | 8 | Excluded (agentflow/runtime/*.json + logs/.gitignore) |
| LOCAL_ONLY | 36 | Excluded (flagged dirs + >2 personal hits) |
| PUBLIC_SANITIZE | 15 | Imported with sanitization |
| SPECIAL_INCLUDE | 1 | Imported with sanitization (action_broker.py) |
| PUBLIC_INCLUDE | 136 | Imported as-is |
| **Total tracked** | **196** | |

## Sanitization applied

- `/home/sticky-ricky` → `$HOME`
- `/mnt/user-data` → `$UPLOADS`
- `doncannoli` / `stickyricky` → `test_player`
- Session paths removed

## Authority model preserved

- T1/T2/T3 classification
- ActionBroker single-writer boundary
- ConfirmationStore durable confirmations
- RelayWriter transport binding
- Loopback policy
- DryRunGcliWriter default
- Evidence != authority
