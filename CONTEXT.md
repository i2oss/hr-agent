# HR Agent — Domain Glossary

The language of this project. Glossary only: no implementation decisions (those live in SPEC.md and the map's tickets).

**Company** — the fictional mid-size engineering firm whose policies and employees the system serves. Entirely synthetic.

**Policy Corpus** — the set of the Company's policy and procedure documents (5–20 files, 30–120 pages, at least two source formats). The only source of policy truth.

**Policy Document** — one file in the Policy Corpus, identified by a stable document ID and title, divided into **Sections**.

**Chunk** — a retrievable slice of a Policy Document, carrying enough metadata (document ID, title, Section, snippet) to be cited.

**Citation** — a pointer from an answer back to the Policy Document and Section that supports it, with a supporting snippet. A policy claim without a Citation is unsupported.

**Policy Fact** vs **Recommendation** — a Policy Fact is stated by the Policy Corpus and cited; a Recommendation is the agent's suggested next step. Answers keep the two visibly distinct.

**Mock Data** — clearly synthetic structured records (employee profiles, PTO balances, benefits elections, manager relationships, locations, employment types, tickets). Never real personal data.

**Employee** — a person in the Mock Data, identified by an employee ID. The user of the chat speaks *as* an Employee.

**Tool** — a capability the agent may invoke, exposed only through an MCP server. A direct function call that bypasses MCP is not a Tool call.

**Mock Action** — a Tool call that would change the world in a real system (create an HR ticket, draft a manager message, update a case). Always simulated, and only performed after explicit user **Confirmation**.

**Workflow** — a multi-step task the agent completes by combining retrieval and Tool calls. The two demo Workflows are **PTO Request Guidance** and **Remote-Work Eligibility**.

**Trace** — the concise, operational record of a run: Tools selected, arguments, outputs, retrieved sources, answer basis, and any Escalation. Not hidden chain-of-thought.

**Clarification** — the agent asking the user for missing or ambiguous input (e.g. no employee ID) instead of guessing.

**Escalation** — the agent deciding a request should go to a human (HR) rather than be answered directly.

**Refusal** — the agent declining an out-of-corpus or out-of-scope question rather than inventing policy.
