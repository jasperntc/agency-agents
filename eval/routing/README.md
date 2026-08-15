# Routing benchmark

`cases.jsonl` — one task per line, written the way a *user* would phrase it, with
the specialist that should be found.

```json
{"case": "c041", "kind": "independent", "task": "I want a second pair of eyes on this pull request before it goes in.", "expect": ["engineering-code-reviewer"], "why": "Code review. Deliberately very short input."}
```

| field | meaning |
| --- | --- |
| `case` | stable id. Never reuse one. |
| `kind` | `independent`, `paraphrase`, or `adversarial` |
| `task` | the request, in the user's vocabulary |
| `expect` | acceptable agent ids, best first. More than one only where two agents genuinely overlap. |
| `why` | why that is the right answer — read by humans reviewing a diff, not by the harness |

## The one rule that matters

**Write the task before you read the agent's description.** A case paraphrased
out of the description it is supposed to find will match perfectly and prove
nothing. `scripts/eval_routing.py` measures the token overlap of every case and
fails the build if it climbs, but the guard only works if it is guarding against
accidents rather than habit.

A case that fails is a result. Do not reword it until it passes — the failures
are the useful output. See [../../docs/routing-evaluation.md](../../docs/routing-evaluation.md).
