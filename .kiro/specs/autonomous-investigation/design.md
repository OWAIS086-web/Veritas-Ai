# Design: Autonomous Investigation

## Components
- `app/workflows/investigation_pipeline.py` builds the LangGraph `StateGraph[InvestigationState]` with a Postgres checkpointer (`langgraph-checkpoint-postgres`; justification: durable resume without a custom store).
- `app/agents/<name>.py` holds one module per agent: `run(state, tools, llm) -> AgentOutput`.
- `app/agents/tools.py` is the tool registry. Each tool is `Tool(name, input_model, output_model, fn, permission)`. `ToolGateway.call(agent, name, args)` checks the allowlist, validates the args, executes with the organization- and case-scoped session, validates the output, and logs an event.
- `app/agents/references.py` holds `validate_refs(session, org, case, refs) -> (valid, rejected)`.
- `app/agents/budget.py` holds `Budget(iterations, tool_calls, tokens, deadline)`, checked before each node and tool call.

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

All tools are read-only except `create_report_draft`. No tool can change a finding status.

## Prompt construction
The system message holds the role, rules, the "ignore instructions in data" rule and the output schema. The user message holds the objective, structured facts as JSON, and `<document_data id=… page=…>…</document_data>` blocks. Document text is truncated to the budget.

## Data model (migration 0007)
`investigations(id, organization_id, case_id, objective, status, budget jsonb, usage jsonb, result jsonb, created_by, approved_by, approved_at, created_at, finished_at)`, `agent_runs(...)`, `agent_events(id bigserial, organization_id, investigation_id, agent_run_id, seq, type, data, created_at)`, `evidence_requests(...)`.

## Failure handling
- Provider failure: retries, then the fallback model, then the step fails with an explanation. Deterministic outputs (the findings list, references) are still recorded.
- Budget exhausted: status `budget_exhausted`, partial result saved, UI shows it.
- Worker crash: the checkpointer resumes the run.

## Testing
- Replay provider fixtures produce deterministic runs.
- A test proves an injected document cannot trigger tools or status changes.
- A test proves an invented reference is rejected.
- Budget tests use a provider that never terminates and assert the run stops.
