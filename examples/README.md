# Example reports

All reports use fictional data. `.txt` files show plain output; terminal colors are omitted.

| Report | Scenario |
| --- | --- |
| [Default report](sample-output.txt) | Active service, four forecast baselines and a history summary. |
| [Expanded history](sample-output-history.txt) | Full past service and commitment details. |
| [Overage](sample-output-overage.txt) | All four baselines forecast overage. |
| [Mixed outcomes](sample-output-mixed.txt) | Some baselines forecast overage, others unused credit. |
| [Exhausted credit](sample-output-exhausted.txt) | Existing overage stays separate from future overage. |
| [Missing days](sample-output-missing-days.txt) | 64/90 daily records; average = sum of the 64 reported days / 64. Coverage retains 64/90. |

See the [validation report](../overage-test-report.md) for test scope and expected results.
