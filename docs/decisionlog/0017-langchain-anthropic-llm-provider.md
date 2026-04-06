# ADR-0017: langchain-anthropic LLM Provider

**Status**: ACCEPTED
**Date**: 2026-04-04
**Author**: developer

## Context

Sprint B2 introduces the LangGraph ReAct loop in `agents/graph.py`. The agent needs a chat model that supports structured tool calling. The project currently depends on `langchain-openai>=0.3` for OpenAI-compatible endpoints (used by `chains/scribe.py` with `ChatOpenAI` targeting `openai/gpt-oss-120b` and Nemotron Ultra). Adding `langchain-anthropic` enables Claude models as a first-class option alongside OpenAI-compatible models.

Legion is an SRE platform. Model diversity matters for resilience — if one provider has an outage, operators can switch to another by changing `AgentConfig.model_name`. Both providers use official SDKs maintained by their respective companies, minimizing supply chain risk.

## Decision

Add `langchain-anthropic` to the `[project.optional-dependencies] agents` group with pin `>=0.3,<1`.

`langchain-anthropic` wraps the official `anthropic` Python SDK (maintained by Anthropic). It provides `ChatAnthropic` which implements the same `BaseChatModel` interface as `ChatOpenAI`, making it a drop-in swap in `agents/graph.py`. Both support structured tool calling via `bind_tools()`, which LangGraph's `ToolNode` requires.

Model selection is configured via `AgentConfig.model_name` and routed at graph construction time:
- `model_name` starting with `anthropic/` or `claude-` → `ChatAnthropic`
- Everything else → `ChatOpenAI` (covers OpenAI, Nemotron Ultra, gpt-oss/120b, and any OpenAI-compatible endpoint via `model_base_url`)

Both `langchain-openai` and `langchain-anthropic` use their respective official Python SDKs (`openai` and `anthropic`) under the hood. These are the safest options from a supply chain perspective — maintained by the model providers themselves, widely audited, and promptly patched.

## Dependency Details

| Field | Value |
|:------|:------:|
| Package | `langchain-anthropic` |
| Version | `>=0.3,<1` |
| License | MIT |
| PyPI downloads/month | ~5M |
| Maintainers | LangChain Inc (5+ active) |
| Transitive deps | ~3 (anthropic, langchain-core, tokenizers) |
| Last release | 2025 |
| Known CVEs | None |

## Alternatives Considered

1. **`litellm`** — Universal LLM proxy supporting 100+ providers through a single interface. Rejected: massive transitive dependency tree (~50+ deps), proxies API calls through its own abstraction adding latency and debugging opacity, and its broad provider surface increases supply chain attack surface. Legion needs two providers, not a hundred.

2. **Direct `anthropic` SDK without LangChain wrapper** — Call the Anthropic API directly. Rejected: would require a custom `BaseChatModel` adapter to integrate with LangGraph's `ToolNode` and `StateGraph`. `langchain-anthropic` already provides this adapter, is maintained by LangChain Inc in coordination with Anthropic, and stays current with API changes.

3. **OpenAI-compatible proxy for Claude** — Route Claude calls through an OpenAI-compatible proxy endpoint so `ChatOpenAI` handles both. Rejected: adds operational complexity (running a proxy), loses Anthropic-specific features (extended thinking, prompt caching), and adds a failure point. Direct SDK integration is simpler and more reliable.

4. **Single provider only** — Stick with `langchain-openai` and defer Anthropic support. Rejected: operator decision — model diversity is required for resilience and Legion should support both from B2 onwards.

## Consequences

- `agents/graph.py` can instantiate either `ChatOpenAI` or `ChatAnthropic` based on config. Both support `bind_tools()` for LangGraph integration.
- The `[agents]` optional group grows to: `langchain-openai>=0.3`, `langchain-core>=0.3`, `langgraph>=0.3,<1`, `langchain-anthropic>=0.3,<1`.
- `langchain-anthropic` pulls in the `anthropic` SDK (~3 transitive deps). The `anthropic` SDK is maintained by Anthropic with regular security patches.
- Model routing logic lives in `agents/graph.py` or a small factory in `agents/config.py`. No new files needed.
- Both providers confined to `agents/` layer only. Architecture test enforces this.
- Future: additional providers (Google, Mistral) follow the same pattern — add `langchain-<provider>` to the optional group with an ADR.

## References

- ADR-0016: LangGraph runtime dependency
- Decision 12: Single LangGraph agent for chat and event processing
- Sprint B2 build phases: `docs/sre/planning/build-phases.md`
- langchain-anthropic: https://github.com/langchain-ai/langchain/tree/master/libs/partners/anthropic
