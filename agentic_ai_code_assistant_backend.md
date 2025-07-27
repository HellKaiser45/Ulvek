```markdown
# 🛠️ Baby-Step Roadmap to a Production-Grade **Agentic AI Code-Assistant Backend**
*(Each checkbox is intentionally granular. Move to the next step only when the previous is green across local, CI and staging.)*

---

## 0. Prerequisite Checklist
- [ ] Python 3.11 + Poetry or uv virtualenv.
- [ ] Mono-repo layout (`/services`, `/agents`, `/memory`, `/api-gateway`).
- [ ] Lint/format (`ruff`, `black`) + type-check (`mypy`).
- [ ] Pre-commit & unit test skeletons (`pytest-cov`).

---

## 1. Core Scaffold
- [ ] `src/api_gateway/` FastAPI app listening on `0.0.0.0:8000`.
- [ ] Health check `GET /readyz`.
- [ ] Environment dot-file template (`.env.example`) with `CODE_ASSISTANT_API_KEY`, `REDIS_URL`, `POSTGRES_URL`.

---

## 2. Multi-Agent Framework Skeleton
### 2.1 Language Server Orchestrator
- [ ] Pydantic model: `BaseAgentMessage(role, payload, timestamp, token_usage)`.
- [ ] Message bus interface: `class Bus(Protocol): publish, consume`.
- [ ] In-mem `SimpleBus` impl for local dev.

### 2.2 Agent Blueprint
- [ ] Abstract `class Agent`: `name`, `prompt_template`, `models`, `receive(msg) -> List[msg]`.
- [ ] Define 4 core agents:
  - `PlannerAgent`: Turn user prompt → sub-task tree.
  - `CodeRetrieverAgent`: Searches local & remote indexes (ripgrep, GitHub).
  - `RefactorAgent`: Applies diffs via tree-sitter.
  - `VerifierAgent`: Runs & reports unit-test results async.

- [ ] Agent registry singleton `AgentRegistry().get("refactor")`.

### 2.3 Agent Scheduling
- [ ] Simple `RoundRobinScheduler` → later upgrade to `ReAct` loop with `AgentEvaluator`.

---

## 3. Model Layer
- [ ] Integrate:
  - OpenAI GPT-4-turbo.
  - Anthropic Claude 3 Opus.
  - Local CodeLlama-34b via vLLM.
- [ ] Router service: `LLMProviderSelector` chooses model based on token cost & SLA.
- [ ] Streaming responses (SSE) wrapped in `async def stream_chat(prompt) → AsyncIterator[str]`.

---

## 4. Context Engine
- [ ] `ContextBuilder` class:
  - Parses workspace (language → AST, imports).
  - Slices relevant snippets (import graph, symbol references).
  - Token-budgeting (`tiktoken` encoding).
- [ ] Implement hierarchical context windows:
  1. Active tab (priority = 1.0).
  2. Related files (priority = 0.7).
  3. Repo README (priority = 0.4).
  4. External docs (priority = 0.1).

---

## 5. Memory Systems
### 5.1 Episodic
- [ ] Postgres table `episodes(id UUID PK, session_id UUID, role TEXT, content JSONB, ts)`.  
- [ ] Conversation fetcher: `def load_last_k_turns(session_id, k=20)`.

### 5.2 Semantic
- [ ] `pgvector` extension install (`CREATE EXTENSION vector;`).
- [ ] Encoder: `sentence-transformers/all-MiniLM-L6-v2`.
- [ ] Service `SemanticStore.index(text, metadata)`.
- [ ] Retrieve: `similarity(query, top_k=5, threshold=0.83)`.

### 5.3 Procedural
- [ ] Key-value Redis store:
  - `shortcuts:<user_id>` →  user hot-keys & macros.
  - `lint_suppressions:<path>` → per-file linter ignore rules.

---

## 6. Agent Workflows
- [ ] `PlanningWorkflow`:
  1. Receive full prompt.
  2. Invoke PlannerAgent → returns Task-DAG (`networkx.DiGraph`).
  3. Persist DAG to Redis with TTL 15m.
- [ ] `RefactorWorkflow`:
  1. Receive diffSpec.
  2. RefactorAgent applies change via tree-sitter.
  3. VerifierAgent runs relevant tests (`pytest -k`).  
  4. On failure, auto-retry RefactorAgent ≤2 times.

- [ ] `ContextReplayWorkflow`: Before every LLM call, inject last 3 similar episodes from semantic search.

---

## 7. Tooling & Sandboxes
- [ ] Containerized Python sandbox (`python:3.11-alpine`) w/ seccomp profile.
- [ ] gRPC service `code_runner` for running code in 2 GiB seccomp jail.
- [ ] Streaming logs back via websockets (`/ws/log/{run_id}`).

---

## 8. APIs & Contracts
- [ ] OpenAPI schema file (`openapi.json`).
- [ ] WebSocket route `/ws/v1/chat` for streaming.
- [ ] REST routes:
  - `POST /sessions` – create new chat session.
  - `POST /sessions/{id}/messages` – push user message & trigger agentic loop.
  - `GET /sessions/{id}/messages?limit=50`.
  - `DELETE /sessions/{id}` – purge memory.

---

## 9. Persistence & Migrations
- [ ] Alembic initial migration (`001_create_episodes.sql`).
- [ ] Automated backup cron to nightly S3 bucket.

---

## 10. Observability
- [ ] Structured logging (`StructLog`) to JSON.
- [ ] OpenTelemetry traces (FastAPI middleware).
- [ ] Prometheus metrics: `total_tokens_sent`, `latency_per_agent`.
- [ ] Grafana dashboard template committed (`/observability/grafana.json`).

---

## 11. Security & Privacy
- [ ] Input sanitization via `bleach` (strip dangerous markup).
- [ ] Rate-limiting (`slowapi`).
- [ ] PII redaction with `spacy`'s `en_core_web_sm` NER before storing.
- [ ] Row-level access policy for team workspaces.

---

## 12. Testing Matrix
- [ ] Unit tests: `>90 %` coverage on agents and workflows.
- [ ] Scenario tests (BDD): `behaving` tests using FastAPI TestClient.
- [ ] Load test: `locust` target 100 concurrent sessions (avg latency <800 ms).
- [ ] Chaos test: kill RediSearch node during chat — expect graceful retry.

---

## 13. Deployment & CI/CD
- [ ] Dockerfile multi-stage for speed (`poetry.lock` layer cached).
- [ ] `docker-compose.dev.yml` mounts `/src` for hot-reload.
- [ ] GitHub Action:
  - lint/test → build image → scan (`trivy`).
  - push to ECR → deploy to staging via `helm`.
- [ ] Canary rollout (`argocd app sync --prune --grpc-web`) with 5 % traffic.

---

## 14. Future Enhancements (post-MVP)
- [ ] Fine-tuned `RefactorAgent` LoRA model using collected diffs.
- [ ] Graph-based agent state (`neo4j`) to capture repo-wide refactor impact.
- [ ] Multi-language support via tree-sitter grammars.
- [ ] Self-healing infra (KEDA autoscaling based on Redis queue length).

```