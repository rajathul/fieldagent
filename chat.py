"""
Interactive CLI for manually testing the agent.

Usage:
    python chat.py --worker W-001 --date 2026-03-25
    python chat.py --worker W-003          # uses today's date
"""
import argparse
import json
import os
import sys
from dotenv import load_dotenv

load_dotenv()

from data_store import get_store
from database import init_db, create_session, save_message, get_messages, save_work_log
from agent import FieldServiceAgent


def main():
    parser = argparse.ArgumentParser(description="Chat with the field service agent")
    parser.add_argument("--worker", required=True, help="Worker ID (e.g. W-001)")
    parser.add_argument("--date", default="2026-03-25", help="Session date YYYY-MM-DD")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set")
        sys.exit(1)

    init_db()
    store = get_store()
    worker = store.get_worker(args.worker)
    if not worker:
        print(f"Worker {args.worker} not found")
        sys.exit(1)

    agent = FieldServiceAgent(store)
    session_id = create_session(args.worker, args.date)

    print(f"\n{'='*50}")
    print(f"Field Service Agent")
    print(f"Worker: {worker['name']} ({args.worker})")
    print(f"Date:   {args.date}")
    print(f"Session: {session_id[:8]}...")
    print(f"Type 'quit' to exit")
    print(f"{'='*50}\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if user_input.lower() in ("quit", "exit", "q"):
            break
        if not user_input:
            continue

        save_message(session_id, "worker", user_input)
        history = get_messages(session_id)

        print("Agent: ", end="", flush=True)
        raw_response = agent.chat(args.worker, args.date, history)
        finalized = agent.is_finalized(raw_response)
        clean_response = agent.clean_response(raw_response)

        save_message(session_id, "agent", clean_response)
        print(clean_response)

        if finalized:
            print("\n[Extracting work log...]")
            full_history = get_messages(session_id)
            work_log = agent.extract_work_log(args.worker, args.date, full_history)
            if work_log:
                save_work_log(session_id, work_log)
                print("\n--- WORK LOG SAVED ---")
                print(f"Customer:   {work_log.customer_id} | Site: {work_log.site_id}")
                print(f"Status:     {work_log.status}")
                print(f"Billable:   {work_log.billable}")
                print(f"Reasoning:  {work_log.billability_reasoning}")
                if work_log.invoice_item:
                    inv = work_log.invoice_item
                    print(f"\nInvoice:")
                    print(f"  Labor:     {inv.labor_cost:.2f} EUR ({inv.hours_worked}h @ {inv.hourly_rate} {inv.rate_type})")
                    print(f"  Materials: {inv.materials_cost:.2f} EUR ({inv.material_markup_percentage}% markup)")
                    print(f"  Travel:    {inv.travel_cost:.2f} EUR")
                    print(f"  TOTAL:     {inv.total_cost:.2f} EUR")
                if work_log.compliance_flags:
                    print(f"\nCompliance flags:")
                    for flag in work_log.compliance_flags:
                        print(f"  [{flag.severity.upper()}] {flag.description}")
                print("\nFull JSON:")
                print(json.dumps(work_log.model_dump(), indent=2))
            print("----------------------\n")


if __name__ == "__main__":
    main()
