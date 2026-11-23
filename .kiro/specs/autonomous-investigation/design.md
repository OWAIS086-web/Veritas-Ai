# Design: Autonomous Investigation (as built, Phase 6)

## Components
- `app/workflows/investigation_pipeline.py` builds a LangGraph `StateGraph` with these nodes in order: planner → document → forensics → cross_reference → entity → graph → risk → report.
  - It compiles with `interrupt_before=["report"]`, so the run pauses for human review.
  - The graph is linear, so the iteration budget is the only bound needed on cycles.
  - The planner and report steps are required: if either fails, the investigation fails. Any other failed agent is recorded and the run continues.
- `app/workflows/checkpointer.py` (`SqlCheckpointer`) stores LangGraph checkpoints in `investigation_checkpoints` and `investigation_checkpoint_writes`.
  - It uses the app's SQLAlchemy and asyncpg stack under RLS, with LangGraph's own serializer and the semantics of its reference `InMemorySaver`.
  - `langgraph-checkpoint-postgres` was rejected for two reasons: it needs a second driver (psycopg), and its tables have no `organization_id`, so they couldn't carry the tenant policy.
- `app/agents/<name>.py` defines one `AgentSpec` per agent:
  - its role and prompt version;
  - its Pydantic output model and example;
  - `gather`: deterministic reads through the gateway;
  - `finalize`: deterministic post-processing.
- `app/agents/runner.py` (`run_agent`) runs one step. It:
  - gathers the facts;
  - builds the prompt (system rules, the objective, facts as JSON, and page text only in `<document_data …>` blocks in the user message);
  - calls the model, validates the answer, and retries invalid output at most twice;
  - executes allowlisted `tool_requests`, at most 3 per round, charging an iteration per extra round;
  - validates references;
  - runs `finalize`.
- `app/agents/tools.py` holds the registry of `Tool(name, input_model, output_model, fn, permission, writes)` and `ToolGateway.call(agent, name, args)`. The gateway:
  - checks the allowlist and the permission of the role that started the run;
  - refuses requests for writing tools that come from the model;
  - validates the arguments and the result;
  - charges the budget and logs an event.

  Every tool is scoped to the investigation's organization and case. An id outside them is `not_found`.
- `app/agents/references.py` (`validate_refs`) checks every cited `document_id`, page, `field_id`, `finding_id`, `entity_id`, `relationship_id` and `anomaly_id` against the same organization and case. In the output, the runner then:
  - drops an item whose own id is invalid;
  - removes invalid citations from a statement and marks it `supported: false`;
  - records a `reference_rejected` event for each removal.
- `app/agents/budget.py` (`Budget`) tracks iterations, tool calls, tokens and wall-clock time, and is restored from the persisted `usage` on resume.
  - Tokens count only what the provider reports. Calls whose provider reports no counts are counted as `unmetered_calls`.
  - `Completion.usage` was added to the provider interface for this.
- `app/services/investigations/run.py` (`run_investigation`) is called by the Celery task `investigations.run`. It:
  - starts or resumes the run from its persisted status and checkpoint;
  - leaves a run that is `awaiting_review` or finished alone;
  - refuses to run if the starter is no longer a member.

## Tool allowlists
| Agent | Tools |
|---|---|
| planner | list_case_documents, list_findings |
| document | get_document_fields, get_page_text |
| forensics | get_forensic_results |
| cross_reference | list_findings, get_finding_evidence, list_case_documents |
| entity | list_entities, get_entity_mentions |
| graph | get_case_graph, get_entity_relationships |
| risk | list_findings, get_finding_evidence |
| report | create_report_draft |

All tools are read-only except `create_report_draft`. That tool writes only the draft onto the investigation row, and only from the report agent's deterministic code. The model can't request it. No tool can change a finding.

## Outputs
- **Planner:** the focus and open questions. It also keeps the deterministic document and finding lists for later agents.
- **Document:** per-document facts citing `field_id`, document and page.
- **Forensics:** observations plus the persisted limitations. The mandatory limitation always comes first.
- **Cross-reference:** supporting and conflicting evidence per finding, and missing information. Absences already detected by comparison rules are added with `source: "rule"`.
- **Entity and graph:** observations citing entity, relationship and finding ids.
- **Risk:** for each finding, `evidence_strength`, `review_urgency`, `uncertainty` and `alternative_explanations`. Each alternative explanation is marked `hypothesis: true`. The finding's persisted anomaly score, evidence confidence, priority, severity and status are attached unchanged. A finding the model skipped is listed with `assessed: false`.
- **Report** (after approval): a structured draft with sections, and an executive summary checked by `unverified_tokens`. A summary that names a number or id absent from the structured content is replaced by a factual one, with `summary_status: "rejected"`.

## Data model (migration 0006)
The spec's 0007 number was corrected because Phase 5 took 0005.

| Table | Contents | `veritas_app` grants |
|---|---|---|
| `investigations` | `objective, status, budget, usage, result, error, event_seq, created_by, approved_by, approved_at, started_at, finished_at` | SELECT, INSERT, UPDATE |
| `agent_runs` | `agent, status, input_refs, output, output_summary, model, provider, prompt_version, tool_calls, tokens, duration_ms, error` | SELECT, INSERT, UPDATE |
| `agent_events` | ordered by `(investigation_id, seq)` | SELECT, INSERT (append-only) |
| `evidence_requests` | | SELECT, INSERT |
| `investigation_checkpoints` | | SELECT, INSERT, DELETE |
| `investigation_checkpoint_writes` | | SELECT, INSERT, UPDATE, DELETE |

Every table has `organization_id` and RLS.

Statuses: `queued → running → awaiting_review → approved → completed`, or `failed` / `budget_exhausted`. Only one active investigation is allowed per case; a second start is a 409.

## Deviations from the requirements text
- 1.1: a new investigation starts as `queued` and becomes `running` when the worker picks it up. The UI can then show runs that haven't started yet.
- 5.4: the requirements name no permission for `request-evidence`. It uses `findings:comment`, held by admins, managers, investigators and reviewers.

## Failure handling
- **Provider failure.** The provider retries and falls back to its other models. If all of them fail, the step fails with the reason. The deterministic facts are kept in `agent_runs.output`.
- **Invalid output.** It is retried twice with a correction message, and each attempt is recorded as `output_invalid`.
- **Budget exhausted.** The status becomes `budget_exhausted` with the limit reached. The outputs of the steps that completed are kept in `result.agents`.
- **Worker crash.** On redelivery the run resumes from the last checkpoint. The interrupted node runs again, and completed nodes don't.
- **Commit timing.** API sessions use `Depends(db_session, scope="function")`, so the transaction commits before the response is sent. This bug was found in Phase 6 and fixed for every endpoint.

## Testing
The test model is a scripted double (`tests/agent_provider.py`). It answers from the facts in the prompt, can be configured to inject failures, and is used only in tests. Live tests use the configured provider.

- `tests/integration/test_investigations.py` (10 tests):
  - the pause, approval and report path;
  - invented references removed and recorded, and the report summary verifier;
  - an injected document plus a model that obeys it: tool calls refused and findings unchanged;
  - a never-ending model stops with `budget_exhausted` and keeps its partial results;
  - provider failure and invalid-output retries;
  - worker crash and resume;
  - SSE with `Last-Event-ID`;
  - evidence requests;
  - a removed starter can't run;
  - cross-org 404 on all 7 endpoints and RLS on the 6 tables.
- `tests/property/test_agent_invariants.py`: budget invariants, data-block placement of document text, the allowlist structure, citation stripping, the summary verifier and risk finalization.
- `tests/unit/test_dependency_scopes.py`: every session dependency commits before the response.
- Live tests (`-m live`): `tests/integration/test_live_investigation.py` and the Playwright test `tests/e2e/agents.spec.ts` (with `VERITAS_E2E_LIVE_MODEL=1`).
