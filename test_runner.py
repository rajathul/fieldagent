"""
Automated test runner for all 10 scenarios in test_prompts.json.

Usage:
    python test_runner.py                  # run all tests
    python test_runner.py --id GS-01       # run single test
    python test_runner.py --save           # save conversation logs to output/
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from data_store import get_store
from database import init_db, create_session, get_session, save_message, get_messages, save_work_log
from agent import FieldServiceAgent

DATA_DIR = Path(__file__).parent / "data"
OUTPUT_DIR = Path(__file__).parent / "output"

SESSION_DATE = "2026-03-25"  # fixed date per test spec


def load_test_cases() -> list[dict]:
    with open(DATA_DIR / "test_prompts.json") as f:
        return json.load(f)["test_cases"]


def simulate_worker_response(agent_message: str, follow_up_hints: list[str], situation: str) -> str | None:
    """
    Decide how to respond to an agent follow-up question.
    Uses follow_up_hints when the question matches, otherwise derives from situation.
    Returns None if the agent is asking for confirmation (worker says yes).
    """
    msg_lower = agent_message.lower()

    # Detect confirmation request
    confirmation_phrases = [
        "does that look right", "look right?", "look correct?",
        "shall i log", "confirm", "good to go?", "correct?",
        "all good?", "is that right", "look good?",
    ]
    if any(p in msg_lower for p in confirmation_phrases):
        return "Yes, that looks right."

    # Check follow-up hints for relevant answers
    for hint in follow_up_hints:
        hint_lower = hint.lower()
        # Match hint to question topic
        if "solder" in hint_lower and ("solder" in msg_lower or "flux" in msg_lower):
            return hint
        if "approval" in hint_lower and ("approval" in msg_lower or "approved" in msg_lower):
            return hint
        if "pump" in hint_lower and "pump" in msg_lower:
            return hint
        if "material" in hint_lower and ("material" in msg_lower or "parts" in msg_lower):
            return hint
        if "saturday" in hint_lower and ("saturday" in msg_lower or "weekend" in msg_lower):
            return hint
        if "panel" in hint_lower and "panel" in msg_lower:
            return hint
        if "element" in hint_lower and "element" in msg_lower:
            return hint
        if "motor" in hint_lower and "motor" in msg_lower:
            return hint

    # Default: provide situation as context
    return f"To answer your question: {situation[:200]}"


def run_test(test_case: dict, agent: FieldServiceAgent, save: bool = False) -> dict:
    worker_id = test_case["worker_id"]
    test_id = test_case["id"]
    title = test_case["title"]

    print(f"\n{'='*60}")
    print(f"TEST {test_id}: {title} [{test_case['difficulty']}]")
    print(f"Worker: {test_case['worker_name']} ({worker_id})")
    print(f"{'='*60}")

    # Create session
    session_id = create_session(worker_id, SESSION_DATE)

    conversation_log = []
    work_log = None
    finalized = False
    max_turns = 8

    # First message
    current_message = test_case["initial_message"]
    follow_up_hints = test_case.get("follow_up_hints", [])
    situation = test_case["situation"]

    for turn in range(max_turns):
        print(f"\n[Worker] {current_message}")
        conversation_log.append({"role": "worker", "content": current_message})

        save_message(session_id, "worker", current_message)
        history = get_messages(session_id)

        raw_response = agent.chat(worker_id, SESSION_DATE, history)
        finalized = agent.is_finalized(raw_response)
        clean_response = agent.clean_response(raw_response)

        save_message(session_id, "agent", clean_response)
        conversation_log.append({"role": "agent", "content": clean_response})

        print(f"[Agent] {clean_response[:300]}{'...' if len(clean_response) > 300 else ''}")

        if finalized:
            full_history = get_messages(session_id)
            work_log = agent.extract_work_log(worker_id, SESSION_DATE, full_history)
            if work_log:
                save_work_log(session_id, work_log)
                print(f"\n✅ Work log extracted:")
                print(f"   Customer: {work_log.customer_id} | Site: {work_log.site_id}")
                print(f"   Status: {work_log.status} | Billable: {work_log.billable}")
                if work_log.invoice_item:
                    print(f"   Total cost: {work_log.invoice_item.total_cost:.2f} EUR")
                if work_log.compliance_flags:
                    for flag in work_log.compliance_flags:
                        print(f"   ⚠️  [{flag.severity.upper()}] {flag.description[:80]}")
            break

        # Generate worker's next response
        next_response = simulate_worker_response(clean_response, follow_up_hints, situation)
        if next_response is None:
            break
        current_message = next_response

        time.sleep(0.5)  # be gentle with the API

    if not finalized:
        print(f"\n⚠️  Test did not finalize within {max_turns} turns")

    result = {
        "scenario": f"{test_id}: {title}",
        "worker_id": worker_id,
        "date": SESSION_DATE,
        "difficulty": test_case["difficulty"],
        "finalized": finalized,
        "messages": conversation_log,
        "work_log": work_log.model_dump() if work_log else None,
    }

    if save:
        OUTPUT_DIR.mkdir(exist_ok=True)
        output_path = OUTPUT_DIR / f"{test_id}.json"
        with open(output_path, "w") as f:
            json.dump(result, f, indent=2)
        print(f"   Saved to {output_path}")

    return result


def print_summary(results: list[dict]):
    print(f"\n{'='*60}")
    print("TEST SUMMARY")
    print(f"{'='*60}")
    total = len(results)
    finalized = sum(1 for r in results if r["finalized"])
    has_log = sum(1 for r in results if r["work_log"])

    print(f"Total tests:    {total}")
    print(f"Finalized:      {finalized}/{total}")
    print(f"Work log saved: {has_log}/{total}")

    print(f"\n{'ID':<8} {'Difficulty':<10} {'Finalized':<12} {'Has Log':<10} Title")
    print("-" * 70)
    for r in results:
        fin = "✅" if r["finalized"] else "❌"
        log = "✅" if r["work_log"] else "❌"
        print(f"{r['scenario'][:6]:<8} {r['difficulty']:<10} {fin:<12} {log:<10} {r['scenario'][8:][:40]}")


def main():
    parser = argparse.ArgumentParser(description="Run field agent test scenarios")
    parser.add_argument("--id", help="Run a specific test case by ID (e.g. GS-01)")
    parser.add_argument("--save", action="store_true", help="Save conversation logs to output/")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set. Add it to .env or export it.")
        sys.exit(1)

    init_db()
    store = get_store()
    agent = FieldServiceAgent(store)
    test_cases = load_test_cases()

    if args.id:
        test_cases = [tc for tc in test_cases if tc["id"] == args.id]
        if not test_cases:
            print(f"Test case {args.id} not found")
            sys.exit(1)

    results = []
    for tc in test_cases:
        result = run_test(tc, agent, save=args.save)
        results.append(result)
        time.sleep(1)

    if len(results) > 1:
        print_summary(results)


if __name__ == "__main__":
    main()
