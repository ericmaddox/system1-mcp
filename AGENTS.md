# Agent Instructions: System 1 Reflex Engine

When operating in this project, you have access to **System 1 MCP** tools (`fast_guard`, `fast_judge`, `fast_verify`, `fast_score`). You must use these tools to make low-latency, calibrated decisions instead of generating long deliberative reasoning loops.

---

## Mandatory Reflex Rules

### 1. Pre-Execution Safety (`fast_guard`)
Before executing any shell command, modifying files outside the workspace, dropping/migrating databases, or mutating remote resources, you MUST invoke:
```json
fast_guard(command="<command>", goal="<user_goal>", workspace=".")
```
- If `action == "block"`: **Do not execute.** Immediately halt and explain the risk to the user.
- If `action == "review"`: Warn the user of the potential blast radius and request explicit confirmation before running.
- If `action == "pass"`: Proceed with normal execution.

### 2. Best-Option Arbitration (`fast_judge`)
When choosing one file, approach, framework, or configuration from a known set of 2 to 10 candidates, call:
```json
fast_judge(question="<selection_question>", options={"<key>": "<summary>"})
```
- Do not read large candidate files into context to make trivial selection decisions. Use `fast_judge` to obtain discrete selections with calibrated probability distributions.

### 3. Assertion & Goal Verification (`fast_verify`)
After running test suites, build scripts, or deployment pipelines, verify outcomes using:
```json
fast_verify(statement="<expected_outcome>", evidence="<raw_terminal_or_log_output>")
```
- Use the calibrated probability and assessment (`high_confidence_yes`, `likely_yes`, `uncertain`, `likely_no`, `high_confidence_no`) to determine if the task was completed successfully.

### 4. Severity & Priority Scoring (`fast_score`)
When evaluating log alerts, security notices, or priority rankings across an ordered scale:
```json
fast_score(question="<rating_question>", levels=["<level_0>", "<level_1>", "..."], content="<alert_text>")
```
- Use the continuous score and legend to determine appropriate escalation levels.
