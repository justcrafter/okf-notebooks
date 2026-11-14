---
title: "The personal-finance preset: household money with an agent"
description: "Personal finances: accounts, debts, budget, goals, investments, reports, decisions"
weight: 32
---

A ready-made preset for a notebook where you and an agent acting as a financial assistant keep the state of one
household's money: accounts and debts, income and budget, goals, investments, period reports, decisions and the
market assumptions behind them.
File: [presets/personal-finance.yaml](https://github.com/justcrafter/okf-notebooks/blob/main/presets/personal-finance.yaml).

## Enabling it

Point `config.yaml` at the presets directory (in Docker it sits next to the config, for example `/config/presets`):

```yaml
presets_dir: ./presets
```

Create the notebook:

```bash
uv run okf-notebooks notebook create family-finance \
  --description "Family finances: accounts, debts, income, budget, goals, investments, monthly reports and decisions" \
  --scope "Balances, debts, budget limits, goals, holdings, period totals, decisions. No account or card numbers, no single transactions" \
  --preset personal-finance
```

## Types

| Type | Directory | What it holds | Required fields | `stale_after` |
|---|---|---|---|---|
| `Account` | `accounts/` | where money or an asset is kept: balance on a date, rate, liquidity, purpose | `kind`, `currency` | 90d |
| `Liability` | `liabilities/` | a debt: rate, payment, balance on a date, payoff date, early repayment terms | `kind` | 90d |
| `IncomeSource` | `income-sources/` | a source of income, active or passive | `nature` | 180d |
| `BudgetCategory` | `budget/` | a spending category and its monthly limit | `kind` | 365d |
| `FinGoal` | `goals/` | a goal: amount, deadline, contribution, priority | `target_amount`, `deadline` | 90d |
| `Holding` | `holdings/` | an investment position with its role, thesis and exit condition | `thesis` | 90d |
| `Policy` | `policies/` | the investment policy: allocation, risk limits, rebalancing, preconditions | — | 365d |
| `Report` | `reports/` | totals of a month, quarter or year: income, expenses, savings rate, net worth | `period`, `period_kind` | — |
| `Decision` | `decisions/` | a question, options, the choice and who proposed it | `question`, `state` | — |
| `Assumption` | `assumptions/` | a market input (rates, inflation, exchange rates) with its date and source | `value`, `as_of` | 30d |
| `AdvisorRule` | `advisor-rules/` | how the agent works here: limits, checks, red lines | — | — |

Values the types expect:

- `BudgetCategory.kind`: `essential`, `variable`, `wants`, `goal-contribution`;
- `IncomeSource.nature`: `active` or `passive`;
- `FinGoal.state`: `planned`, `active`, `reached`, `dropped`;
- `Decision.state`: `open`, `proposed`, `accepted`, `rejected`, `superseded`; `proposed_by` names who suggested it
  (the agent or a person).

## How it works with agents

- Balances, debts and assumptions age fast (`stale_after` 30–90 days). Search marks old ones `stale`, so the agent
  sees that a number needs refreshing before it calculates with it.
- Keep the agent's suggestions apart from your choices: the agent writes a `Decision` with `state: proposed` and
  `proposed_by`; you change it to `accepted` or `rejected`. `status` and `verified` stay yours, as everywhere.
- A `Report` is built from category totals, never from single transactions; put the export it came from (a bank or
  budgeting app CSV) in `sources`.
- Write the advisor's role and limits as `AdvisorRule` notes and tell the agent in `CLAUDE.md` / `AGENTS.md` to read
  them before giving advice in this notebook.
- A goal that serves a life goal kept in another notebook links it in `serves`.
- Never put account or card numbers, logins or broker passwords in a note. Anything that looks like a secret is
  rejected on write, but a card number in prose is still a card number.

## Making your own variant

Copy `presets/personal-finance.yaml`, rename it and adjust the types. The rules, the 12-type limit and the format are
in [presets.md](/docs/presets.md).

This preset is one example of a format, not a requirement. If your case is different, design your own types or
[ask an agent to propose them](/docs/presets.md#ask-an-agent).
