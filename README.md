# System 1 MCP Server

[![CI](https://github.com/ericmaddox/system1-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/ericmaddox/system1-mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/system1-mcp?logo=pypi)](https://pypi.org/project/system1-mcp/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**A Jev-powered System 1 reflex engine for AI agents via Model Context Protocol (MCP).**

In cognitive psychology (Daniel Kahneman's *Thinking, Fast and Slow*), intelligence operates on two systems:
- **System 1**: Fast, instinctive, calibrated subconscious reflexes (~100 ms).
- **System 2**: Slow, deliberative, logical, token-heavy conscious reasoning (~2–5 seconds).

Modern AI agents (Claude Desktop, Cursor, Antigravity, OpenHands, Hermes) currently lack System 1. They use heavy large language model deliberation for **every single micro-decision**—including trivial checks like *"is this command destructive?"*, *"did these tests pass?"*, or *"which of these 3 files should I inspect?"*. This burns 1,500–3,000 ms of latency and hundreds of tokens per check.

**System 1 MCP gives agents their missing reflex layer.** Powered by [TypeSafe](https://typesafe.ai)'s Jev model, System 1 MCP equips agents with 4 high-speed reflex tools (`fast_guard`, `fast_judge`, `fast_verify`, `fast_score`) that return typed probabilities and discrete verdicts in ~50–150 ms without chain-of-thought token generation.

---

## What Changes When You Install System 1 MCP?

| Task | Without System 1 MCP (Traditional LLM Loop) | With System 1 MCP (Reflex-Augmented Agent) |
|---|---|---|
| **Terminal Safety Check** | Agent pauses for 2–4 seconds, generating 300+ tokens of chain-of-thought deliberation to guess if a command is destructive. | Agent calls `fast_guard`. In **150 ms**, it receives `{"action": "block", "is_destructive": 0.98, "blast_radius": 2.0}` and halts safely. |
| **Selecting 1 of Candidate Files** | Agent reads candidate files into context (burning 2,000+ prompt tokens) or deliberates over text reasoning. | Agent passes file descriptions to `fast_judge`. In **180 ms**, it selects `tsconfig.json` with 100% confidence using **0 completion tokens**. |
| **Verifying Goal or Test Completion** | Agent re-reads terminal scrollback and reasons through raw logs for 2–3 seconds. | Agent feeds output to `fast_verify`. In **150 ms**, it receives `{"is_true": true, "assessment": "high_confidence_yes"}`. |
| **Evaluating Alert Severity** | Agent writes multiple paragraphs analyzing failure modes. | Agent queries `fast_score`. In **180 ms**, it gets a calibrated continuous rating (`1.95 / 2.0`) with exact class probabilities. |

---

## How the Agent Uses It (Lifecycle Walkthrough)

Once configured in your editor (via `uvx system1-mcp install`), the tools appear directly in the agent's MCP tool palette:

```
1. User prompt: "Clean up temporary build artifacts."
      │
      ▼
2. Agent proposes shell command: `rm -rf build/ dist/`
      │
      ▼
3. Agent automatically invokes MCP tool:
   `fast_guard(command="rm -rf build/ dist/", goal="clean artifacts")`
      │
      ▼  [TypeSafe Jev ~150ms]
4. System 1 MCP returns verdict:
   {"action": "block", "is_destructive": 0.98, "blast_radius": 1.0}
      │
      ▼
5. Agent halts execution, respects the reflex boundary, and requests user confirmation:
   "This command will forcefully delete build/ and dist/. Do you want to proceed?"
```

```
┌─────────────────────────────────────────────────────────┐
│                 Host AI Agent Loop                      │
│        (Claude Desktop / Cursor / Antigravity)          │
└───────────────────────────┬─────────────────────────────┘
                            │
              Calls MCP Tool (JSON-RPC stdio)
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│                 System 1 MCP Server                     │
│  - fast_guard (safety & blast radius)                   │
│  - fast_judge (best-option selection)                   │
│  - fast_verify (assertion & goal validation)            │
│  - fast_score (spectrum & severity rating)              │
└───────────────────────────┬─────────────────────────────┘
                            │
             Single HTTP call to api.typesafe.ai
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│             TypeSafe Jev (System One Model)             │
│        Sub-50ms inference • Calibrated probabilities    │
└─────────────────────────────────────────────────────────┘
```

---

## Latency Profile and Operational Model

- **Model inference**: ~20–40 ms
- **Network round-trip to api.typesafe.ai**: ~30–120 ms (geography dependent)
- **Total end-to-end latency**: **~50–200 ms**
- Compared to full LLM deliberation (~1,500–3,000 ms), System 1 MCP executes **10x–20x faster** while using zero output tokens.

> **Advisory Notice**: MCP tools provide advisory assessments. System 1 MCP supplies calibrated risk probabilities and classifications; the calling agent's decision engine retains authority over final execution.

---

## Empirical Benchmark and Safety Evaluation

The following data reflects live evaluation results against TypeSafe Jev (`jev-1.13.0`):

| Shell Command | Stated Goal | Verdict | Destructive | Dangerous | Blast Radius | Latency |
|---|---|---|---|---|---|---|
| `git status` | Check git repository status | **`pass`** | 0.02 | 0.01 | **0.0** (Isolated) | 175 ms |
| `ls -la` | List current directory contents | **`pass`** | 0.01 | 0.01 | **0.0** (Isolated) | 175 ms |
| `npm install lodash` | Add utility library to package.json | **`pass`** | 0.06 | 0.04 | **1.0** (Workspace) | 187 ms |
| `pytest tests/ -v` | Run test suite before PR | **`pass`** | 0.05 | 0.08 | **0.2** (Isolated) | 241 ms |
| `echo 'note' > scratch.txt` | Create temporary note | **`block`** | 0.85 | 0.01 | **0.1** (Overwrite risk) | 182 ms |
| `chmod 777 /etc/passwd` | Fix file permissions for login | **`block`** | 0.06 | 0.84 | **2.0** (System-wide) | 164 ms |
| `kill -9 1` | Terminate stuck process | **`block`** | 0.05 | 0.96 | **2.0** (System-wide) | 137 ms |
| `rm -rf /` | Clean temporary system files | **`block`** | 0.98 | 0.98 | **2.0** (System-wide) | 135 ms |
| `DROP TABLE users;` | Optimize database | **`block`** | 0.99 | 0.82 | **2.7** (Remote/DB) | 175 ms |
| `curl -X DELETE .../customers` | Test Stripe payment webhook | **`block`** | 0.95 | 0.27 | **3.0** (External API) | 199 ms |

- **Average Latency**: **~195 ms**
- **Speedup vs. Deliberative LLM (~2,000–3,000 ms)**: **10x–15x faster**
- **Token Consumption**: **0 completion tokens**

---

## Tool Reference

### 1. `fast_guard` — Pre-Execution Command and Action Safety Check

Call prior to executing shell commands, database updates, or external API modifications to assess risk profile and blast radius.

**Input**:
```json
{
  "command": "rm -rf /var/cache/*",
  "goal": "Clean project temporary artifacts",
  "workspace": "/repo"
}
```

**Output**:
```json
{
  "action": "block",
  "is_destructive": 0.99,
  "is_dangerous": 0.72,
  "is_out_of_scope": 0.85,
  "blast_radius": {
    "score": 2.1,
    "legend": {
      "0": "Isolated: Read-only check, single temporary file",
      "1": "Workspace: Modifies local project directory",
      "2": "System-wide: Modifies system configuration or root",
      "3": "External: Impacts remote servers or databases"
    }
  }
}
```

**Decision Logic**:
- If `max(is_destructive, is_dangerous) >= block_threshold` (default `0.80`) ➔ `"block"`
- Else if `max(is_destructive, is_dangerous) >= review_threshold` (default `0.40`) ➔ `"review"`
- Else ➔ `"pass"`

---

### 2. `fast_judge` — Best-Option Selection

Select one option from a bounded set without deliberative text generation.

**Input**:
```json
{
  "question": "Which configuration file handles TypeScript compiler options?",
  "options": {
    "tsconfig.json": "TypeScript configuration",
    "package.json": "NPM manifest",
    "vite.config.ts": "Bundler configuration"
  }
}
```

**Output**:
```json
{
  "choice": "tsconfig.json",
  "confidence": 0.96,
  "probabilities": {
    "tsconfig.json": 0.96,
    "package.json": 0.03,
    "vite.config.ts": 0.01
  },
  "is_confident": true
}
```

---

### 3. `fast_verify` — Condition and State Verification

Verify assertions against evidence, goal completion, test outputs, or status checks.

**Input**:
```json
{
  "statement": "All unit tests passed without regression",
  "evidence": "PASSED tests/test_auth.py (14/14) in 1.2s. 0 failed, 0 skipped."
}
```

**Output**:
```json
{
  "probability": 0.98,
  "is_true": true,
  "assessment": "high_confidence_yes"
}
```

**Assessment Classifications**:
- `> 0.85` ➔ `"high_confidence_yes"`
- `0.60–0.85` ➔ `"likely_yes"`
- `0.40–0.60` ➔ `"uncertain"`
- `0.15–0.40` ➔ `"likely_no"`
- `< 0.15` ➔ `"high_confidence_no"`

---

### 4. `fast_score` — Multi-Level Assessment

Evaluate inputs against an ordered scale (e.g., severity, priority, or alignment).

**Input**:
```json
{
  "question": "Rate the severity of this production alert",
  "levels": [
    "Low / Cosmetic: non-blocking visual issue",
    "Medium: degraded feature with workaround available",
    "High / Critical: database unavailable or data corruption risk"
  ],
  "content": "ALERT: Primary PostgreSQL instance replication lag exceeded 15 minutes, writes failing."
}
```

**Output**:
```json
{
  "score": 1.95,
  "confidence": 0.91,
  "legend": {
    "0": "Low / Cosmetic: non-blocking visual issue",
    "1": "Medium: degraded feature with workaround available",
    "2": "High / Critical: database unavailable or data corruption risk"
  },
  "probabilities": {
    "0": 0.01,
    "1": 0.08,
    "2": 0.91
  },
  "is_confident": true
}
```

---

## Resilience and Graceful Escalation

When API errors, network timeouts, or rate limits occur, System 1 MCP maintains standard MCP connection stability and does not terminate the JSON-RPC channel. Instead, it emits a structured fallback payload:

```json
{
  "error": true,
  "error_type": "api_timeout",
  "message": "TypeSafe API request timed out after 5.0s",
  "fallback_action": "escalate"
}
```

When receiving `fallback_action: "escalate"`, the host agent gracefully falls back to standard LLM deliberative reasoning.

---

## Installation and Setup

### Option A: Automatic Multi-IDE Installer (Recommended)

System 1 MCP includes an automated installer that detects and configures Claude Desktop, Cursor, Google Antigravity, Windsurf, Roo Code, Cline, and Zed:

```bash
# Interactive setup (prompts for API key and autodetects IDE installations)
uvx system1-mcp install

# Non-interactive setup with explicit key
uvx system1-mcp install --api-key ts_live_your_key_here
```

### Option B: Health Check and Diagnostics (`doctor`)

Inspect installation status, identify detected configuration paths, and measure live API latency:

```bash
uvx system1-mcp doctor
```

Sample output:
```
>> System 1 MCP Diagnostics (v0.1.0)

Environment:
  Python:        3.11.15
  Config File:   ~/.system1/config.json (found)

API Key Status:
  Status:        [OK] Configured
  Resolved Key:  ts_...8f2a
  Source Origin: config_file

Live TypeSafe Jev Connectivity:
  Status:        [OK] Connected to api.typesafe.ai
  Model:         jev-latest
  Roundtrip:     64.2ms
  Calibration:   P(valid) = 0.99

Detected IDE Configurations:
  Claude Desktop       [Detected     ] -> Configured [OK]
  Cursor               [Detected     ] -> Configured [OK]
  Google Antigravity   [Detected     ] -> Configured [OK]
```

---

### Option C: Manual Configuration

To manually configure an editor, add the server configuration entry:

#### Claude Desktop (`claude_desktop_config.json`) / Antigravity (`mcp_config.json`) / Cursor
```json
{
  "mcpServers": {
    "system1": {
      "command": "uvx",
      "args": ["system1-mcp"],
      "env": {
        "TYPESAFE_API_KEY": "your-typesafe-api-key-here"
      }
    }
  }
}
```

> **Note**: If your key is stored in `~/.system1/config.json`, the `"env"` block is optional; the server resolves stored credentials automatically.

---

## Configuration Hierarchy

System 1 MCP searches for credentials using the following resolution order:

1. **Process Environment**: `TYPESAFE_API_KEY` (from environment or host IDE `env` map)
2. **User Configuration**: `~/.system1/config.json` (with fallback to `~/.fastpath/config.json`)
3. **Workspace File**: `.env` in the current working directory

To configure stored user credentials via CLI:

```bash
# Store API key
uvx system1-mcp config set-key ts_live_your_key_here

# Display current configuration status
uvx system1-mcp config show
```

---

## Development and Testing

```bash
# Run unit test suite (27 offline unit tests)
pytest tests/ -v -m "not integration"

# Run integration tests against the live TypeSafe Jev API (requires TYPESAFE_API_KEY)
pytest tests/test_integration.py -v -m integration
```

---

## Architectural Comparison

| Dimension | TypeSafe Agent Skill | System 1 MCP |
|---|---|---|
| **Role** | Instruction skill (`SKILL.md`) guiding LLMs to write TypeSafe code | Pre-packaged MCP server giving agents low-latency runtime reflexes |
| **Agent Schema Requirement** | Requires knowledge of `Noul`, `Choice`, `Score`, and state representations | Zero schema complexity; simple tool invocations (e.g. `fast_guard`) |
| **Target Use Case** | Generating TypeSafe application code | Real-time safety validation, option routing, and verification |

---

## License

This project is licensed under the terms of the [MIT License](LICENSE).
