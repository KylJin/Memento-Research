"""End-to-end agentic test for the memento asset tool.

Runs two consecutive tasks through a real LangGraph react agent — same
agent loop OMC's BaseAgentRunner uses (create_react_agent + LLM tool
calling) — and verifies the agent autonomously decides to call store
on task A and recall on task B, then surfaces the recalled facts in
its task B answer.

Verifies:
  1. agent issues a `store` tool call during task A
  2. session JSON appears on disk afterward
  3. agent issues a `recall` tool call during task B
  4. final answer mentions the verbatim facts from task A
  5. cross-employee isolation: a second employee on the same run sees
     none of the first employee's stored facts

Usage:
    OPENROUTER_API_KEY=sk-... \
    OPENROUTER_BASE_URL=https://app.ppapi.ai/v1 \
    MEMENTO_MODEL=gemini-3-flash-preview \
    AGENT_MODEL=gemini-3-flash-preview \
    python scripts/test_memento_agent.py [--fresh]
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from onemancompany.core.vessel import _current_vessel


TMP_ROOT = REPO_ROOT / ".tmp_memento_agent"
TEST_EMPLOYEES_DIR = TMP_ROOT / "employees"
EMP_PRIMARY = "AGENT-E2E"
EMP_OTHER = "AGENT-E2E-OTHER"


def _prep(fresh: bool) -> None:
    if fresh and TMP_ROOT.exists():
        shutil.rmtree(TMP_ROOT)
    TEST_EMPLOYEES_DIR.mkdir(parents=True, exist_ok=True)
    (TEST_EMPLOYEES_DIR / EMP_PRIMARY).mkdir(exist_ok=True)
    (TEST_EMPLOYEES_DIR / EMP_OTHER).mkdir(exist_ok=True)


def _patch_employees_dir() -> None:
    import onemancompany.core.config as cfg
    cfg.EMPLOYEES_DIR = TEST_EMPLOYEES_DIR
    import company.assets.tools.memento.memento as memento_mod
    memento_mod.EMPLOYEES_DIR = TEST_EMPLOYEES_DIR


def _build_agent():
    """Build a LangGraph react agent wired to store + recall."""
    from langchain_openai import ChatOpenAI
    from langgraph.prebuilt import create_react_agent

    from company.assets.tools.memento.memento import recall, store

    llm = ChatOpenAI(
        model=os.environ.get("AGENT_MODEL", "gemini-3-flash-preview"),
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url=os.environ.get("OPENROUTER_BASE_URL", "https://app.ppapi.ai/v1"),
        temperature=0.2,
        max_retries=3,
        timeout=180.0,
    )
    return create_react_agent(model=llm, tools=[store, recall])


SYSTEM_PROMPT = """You are an engineer with persistent long-term memory.

You have two tools available:
- recall(query): search prior session summaries before tackling a new
  task; call this FIRST when a task references prior context, customer
  names, or "what did we decide about X".
- store(turns): persist a finished session into memory at the END of
  a task that produced facts, decisions, customer-specific configs,
  or important constants. Pass the full conversation as turns of
  {role: 'user'|'assistant', content: '...'}.

Rules:
- For factual recall questions, call recall FIRST, then answer using
  the returned context. Do NOT answer from prior knowledge if recall
  returns relevant context.
- For tasks that capture a fact ("remember", "document", "we decided"),
  call store BEFORE giving your final answer.
- Always include verbatim values (URLs, port numbers, names) in your
  store turns so they survive into recall context."""


def _run_task(agent, employee_id: str, user_message: str) -> dict:
    """Run one task as the given employee. Return dict with text + tool_calls."""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

    vessel = SimpleNamespace(employee_id=employee_id)
    token = _current_vessel.set(vessel)
    try:
        result = agent.invoke({
            "messages": [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=user_message),
            ]
        }, config={"recursion_limit": 25})
    finally:
        _current_vessel.reset(token)

    tool_calls = []
    final_text = ""
    for msg in result["messages"]:
        if isinstance(msg, AIMessage):
            tcs = getattr(msg, "tool_calls", []) or []
            for tc in tcs:
                tool_calls.append({"name": tc.get("name", ""), "args": tc.get("args", {})})
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            if content:
                final_text = content
    return {"messages": result["messages"], "tool_calls": tool_calls, "final": final_text}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh", action="store_true")
    args = parser.parse_args()

    if not os.environ.get("OPENROUTER_API_KEY"):
        print("OPENROUTER_API_KEY not set", file=sys.stderr)
        return 2

    _prep(fresh=args.fresh)
    _patch_employees_dir()

    agent = _build_agent()

    print("== Task A (store): document Acme onboarding ==")
    task_a_msg = (
        "Customer Acme uses self-hosted SSO via SAML 2.0. Their IdP URL is "
        "sso.acme.example. Session timeout is 4 hours. SP-initiated only. "
        "No SCIM. Document this onboarding info and remember it for future "
        "questions about the Acme account."
    )
    t0 = time.time()
    a = _run_task(agent, EMP_PRIMARY, task_a_msg)
    print(f"  elapsed: {time.time() - t0:.1f}s")
    print(f"  tool_calls: {[tc['name'] for tc in a['tool_calls']]}")
    print(f"  final: {a['final'][:200]}")

    a_called_store = any(tc["name"] == "store" for tc in a["tool_calls"])
    sessions_dir = TEST_EMPLOYEES_DIR / EMP_PRIMARY / "memory" / "sessions"
    a_disk = list(sessions_dir.glob("*.json")) if sessions_dir.exists() else []

    print("\n== Task B (recall): what auth does Acme use? ==")
    task_b_msg = (
        "What authentication method does customer Acme use, and what is "
        "their IdP URL? Use your memory to answer accurately."
    )
    t0 = time.time()
    b = _run_task(agent, EMP_PRIMARY, task_b_msg)
    print(f"  elapsed: {time.time() - t0:.1f}s")
    print(f"  tool_calls: {[tc['name'] for tc in b['tool_calls']]}")
    print(f"  final: {b['final'][:400]}")

    b_called_recall = any(tc["name"] == "recall" for tc in b["tool_calls"])
    final_lower = (b["final"] or "").lower()
    answer_has_saml = "saml" in final_lower
    answer_has_idp = "sso.acme.example" in final_lower

    print("\n== Task C (isolation): EMP-OTHER asks the same Acme question ==")
    c = _run_task(agent, EMP_OTHER, task_b_msg)
    print(f"  tool_calls: {[tc['name'] for tc in c['tool_calls']]}")
    print(f"  final: {c['final'][:300]}")
    other_leaked = "sso.acme.example" in (c["final"] or "").lower()

    print("\n=== Summary ===")
    checks = {
        "task_A_called_store": a_called_store,
        "task_A_session_on_disk": len(a_disk) >= 1,
        "task_B_called_recall": b_called_recall,
        "task_B_answer_mentions_saml": answer_has_saml,
        "task_B_answer_quotes_idp_url": answer_has_idp,
        "task_C_other_employee_did_not_leak": not other_leaked,
    }
    for k, v in checks.items():
        sym = "PASS" if v else "FAIL"
        print(f"  [{sym}] {k}")
    overall = all(checks.values())
    print(f"\nOverall: {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
