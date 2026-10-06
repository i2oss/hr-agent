# hr-agent

An agentic HR assistant for a fictional engineering firm: policy RAG with citations, MCP-exposed tools over synthetic employee data, and human-in-the-loop confirmation for anything that looks like an action. Built for Quantic MSAIE *AI Engineering Techniques and Architectures* (Project 3).

> **Status: planning.** The route to a build-ready [SPEC.md](SPEC.md) is being charted as a wayfinder map in this repo's Issues.

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
