# ❌ Scenario validation FAILED: `cop_hard_01`

Edit `server/pipeline/scenarios/` for `cop_hard_01`, then re-run: `python scripts/calibrate_scenario.py cop_hard_01 --force`
Full JSON report: `C:\Users\gueta\Documents\Mes_projets\surviveTheTalk2\_bmad-output\implementation-artifacts\calibration-tests\calibrate_cop_hard_01_2026-06-10T17-23-02Z.json`

## Golden net failures (the judge mis-verdicts known cases)

### Off-topic input was accepted (this is the 2026-05-30 'judge passes everything' class of bug)

These off-topic / tangential lines were judged **met**, but they do NOT accomplish the objective. The `success_criteria` is too permissive — tighten it so only a genuine attempt passes.

- checkpoint **respond** (`checkpoints[0].success_criteria`): user said "I think the traffic was terrible this morning." → judged **met** (should be unmet). [seed]

---
Paste this whole block to an AI agent to propose the YAML edit, then re-run the command above to confirm.