# Examples

Each folder is a complete recorded run: the input diff, the recorded DataHub
responses, the agent's analysis, and every artifact it produced. Read them to judge
output quality without running anything; replay them to watch it happen:

```bash
fuse replay examples/01-drop-column
```

Every column named below is a real column of the `showcase-ecommerce` catalog, not an
invented one - the demo dbt project mirrors `order_entry.orders` and
`order_entry.customers`, so a local diff lands on the actual DataHub graph.

| Scenario | Input | Why it matters |
|---|---|---|
| `01-drop-column` | `promotion_id` removed from the `orders` mart | It propagates into `order_details` on dbt, Snowflake **and** PowerBI, plus the dashboards built on them |
| `02-type-change` | `order_total` narrowed from FLOAT to INT | Passes every test and silently truncates money |
| `03-ml-feature-break` | `credit_limit` removed from `customers` | It is the strongest feature of a churn model serving production traffic |

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

