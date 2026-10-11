# hr-agent

An agentic HR assistant for a fictional engineering firm: policy RAG with citations, MCP-exposed tools over synthetic employee data, and human-in-the-loop confirmation for anything that looks like an action. Built for Quantic MSAIE *AI Engineering Techniques and Architectures* (Project 3).

> **Status: building.** [SPEC.md](SPEC.md) is the build plan. Slices 1 and 3–7 (code) are in; the corpus prose is a draft pending review (slice 2), and docs, eval runs and the demo (slices 7 runs, 8, 9) are still to come.

## Quickstart (development)

```sh
uv sync                                  # Python 3.12 + locked deps into .venv
cp .env.example .env                     # set LLM_API_KEY, or LLM_PROVIDER=fake for no key
make run                                 # http://127.0.0.1:8000 (chat page, /health, /config)
make test                                # pytest: unit, data, MCP, end-to-end with the fake LLM
make check                               # facts/outlines, Eval Set and corpus checks
make index                               # rebuild the committed policy index after corpus edits
uv run python -m evaluation.run --run-id baseline --runs 3   # evals (manual, costs LLM calls)
uv run python -m evaluation.report       # regenerate the evaluation section
```

- **Map:** see the issue labelled `wayfinder:map`
- **Glossary:** [CONTEXT.md](CONTEXT.md)
- **Research findings:** `research/`, linked from their tickets

## Wayfinding operations

Tracker: GitHub Issues on `i2oss/hr-agent`, via the `gh` CLI.

| Operation | How |
|---|---|
| Map | The issue labelled `wayfinder:map` (issue 1). Edit its body with `gh issue edit 1 -F <file>`. |
| Ticket | A sub-issue of the map with one `wayfinder:<research\|prototype\|grilling\|task>` label. Body is `## Question`. |
| Create ticket | `gh issue create -t "<title>" -l wayfinder:<type> -F <body>`, then attach to the map: GraphQL `addSubIssue(input:{issueId:<map node id>, subIssueId:<ticket node id>})`. |
| Blocking | Native dependency: GraphQL `addBlockedBy(input:{issueId:<blocked>, blockingIssueId:<blocker>})`. Wire in a second pass after all new tickets exist. |
| Claim | `gh issue edit <n> --add-assignee i2oss`, before any work. |
| Resolve | `gh issue comment <n> -F <resolution>`, `gh issue close <n> -r completed`, then add `- [<title>](<issue url>): <gist>` to the map's Decisions so far. |
| Out of scope | `gh issue close <n> -r "not planned"` plus one line in the map's Out of scope. |
| Research assets | Commit to `research/<name>.md` and link from the ticket. |

**Frontier query** (open, unassigned sub-issues whose blockers are all closed):

```sh
gh api graphql -f query='{repository(owner:"i2oss",name:"hr-agent"){issue(number:1){subIssues(first:50){nodes{number title state assignees(first:1){totalCount} blockedBy(first:10){nodes{state}}}}}}}' \
  -q '.data.repository.issue.subIssues.nodes[] | select(.state=="OPEN" and .assignees.totalCount==0 and all(.blockedBy.nodes[]; .state=="CLOSED")) | "#\(.number) \(.title)"'
```
