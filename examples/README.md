# Examples

Each folder is a complete recorded run: the input diff, the recorded DataHub
responses, the agent's analysis, and every artifact it produced. Read them to judge
output quality without running anything; replay them to watch it happen:

```bash
fuse replay examples/01-drop-column
```

| Scenario | Input | Why it matters |
|---|---|---|
| `01-drop-column` | `discount_code` removed from the `orders` mart | The everyday break: a downstream mart and a dashboard depend on it |
| `02-type-change` | `order_amount` narrowed from FLOAT to INT | Passes every test and silently truncates money |
| `03-ml-feature-break` | a column feeding a feature table is removed | Reaches a model deployed to production — the failure nobody sees |

Layout of each folder:

```
diff.patch          the change that was analysed
repo/               the data repo at the moment of the change
fixtures/           recorded DataHub responses (what makes replay honest)
impact-report.md    the analysis, with every score explained
PR_BODY.md          what the reviewer sees
generated/          every artifact Fuse produced
run.log             node-by-node trace, including validation retries
```

Populated on Day 13 from real runs. Nothing here is hand-written.
