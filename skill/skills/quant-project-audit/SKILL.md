---
name: quant-project-audit
description: Use when reviewing quantitative trading projects (strategy code, factor research, backtests, execution simulators, or launch-readiness reviews) for look-ahead bias, survivorship bias, data leakage, overfitting, microstructure realism gaps, and production risk before deployment.
---

# Quant Project Audit

## Overview

Perform adversarial, evidence-based audits for quant trading projects.  
Prioritize false-alpha detection: reject strategies that rely on data leakage, unrealistic execution assumptions, or fragile statistical significance.

## Inputs To Request First

Collect these artifacts before concluding:

- Strategy code and factor pipeline (feature engineering, label generation, signal logic)
- Backtest engine config (fill rules, fees, slippage, latency, margin, leverage, rebalancing)
- Data lineage (vendor, snapshot hash, PIT fields, universe construction, delisting handling)
- Training/validation protocol (splits, CV, purging/embargo, hyperparameter search logs)
- Order/trade/risk logs (order lifecycle, partial fills, rejects, risk triggers)

If any critical evidence is missing, issue a conditional verdict and list blocking gaps explicitly.

## Audit Workflow

1. Build evidence map:
- Map each strategy decision to its data availability timestamp.
- Map each trade fill to exchange rules and executable liquidity constraints.

2. Run six-dimensional deep audit:
- `Data Integrity & PIT`: survivorship, PIT timestamps, revisions, corp actions.
- `Temporal Alignment & Code`: vectorization leakage, `.shift(1)` discipline, same-bar fill cheating.
- `Model Robustness`: overfitting, data snooping, multiple testing, invalid CV.
- `Microstructure & Execution`: slippage realism, impact model, queue/partial fill, halts/price limits.
- `Engine & Infra`: scheduler bugs, timezone/calendar consistency, determinism/reproducibility.
- `Risk & Compliance`: leverage/margin/liquidation, hard limits, audit trail completeness.
- Enforce full item coverage using `references/audit-matrix-52.md`.

3. Stress and falsification pass:
- Re-run with stricter cost/slippage/latency assumptions.
- Re-run with corrected time alignment and PIT-only data.
- Re-run with robust validation protocol (walk-forward or purged CV).
- Run `references/self-check-protocols.md` and report pass/fail for all checks.

4. Deliver verdict and remediation:
- Use required output template in `references/output-template.md`.
- Link every finding to direct evidence (code line, config key, data field, or log record).

## Mandatory Red Flags (Immediate FAIL)

Any one of the following is enough to classify as `极高危拒绝投产`:

- Confirmed look-ahead bias / future function / feature-label overlap leakage
- Survivorship-biased universe without delisted handling for relevant asset class
- Non-PIT fundamental/macro alignment treated as known before release timestamp
- Same-bar idealized fills that are impossible given signal timing
- Missing or zeroed transaction cost/slippage for turnover-sensitive strategy
- Limit-up/down, halt, or margin/liquidation rules ignored in markets where applicable
- Non-reproducible backtest outputs under fixed code/data snapshot

## Severity And Evidence Rules

- `P0`: Fatal logical invalidity or non-causal leakage (block launch).
- `P1`: Major realism gap likely to flip sign of net alpha.
- `P2`: Material weakness requiring remediation before scale-up.
- `P3`: Improvement item (does not invalidate core claim).

Each finding must include:
- Evidence reference (file path, code line, config key, log record, or data sample)
- Why it biases metrics (mathematical or market-mechanism explanation)
- Concrete fix and minimum regression test

Every report must also include:
- 52-item coverage summary (`PASS/FLAG/N/A/MISSING` counts)
- List of all `MISSING` items and blocking evidence requests
- Self-check protocol results (`S01`-`S08`)

## Style Requirements For Final Report

- Tone: strict, skeptical, academically grounded.
- Do not give generic advice without proof.
- Prefer conditional language only when evidence is incomplete; explicitly state what is inferred vs proven.
- Use exact section headers and order from `references/output-template.md`.

## References In This Skill

- Checklist and detection heuristics: `references/audit-checklist.md`
- 52-item canonical matrix: `references/audit-matrix-52.md`
- Self-check test suite: `references/self-check-protocols.md`
- Required report schema: `references/output-template.md`

When time is limited, prioritize P0/P1 checks first and clearly mark skipped checks.
