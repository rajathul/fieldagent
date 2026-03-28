import json
import os
import re
from anthropic import Anthropic
from models import WorkLog
from data_store import DataStore

# Marker the agent includes in its response when it has enough info and the
# worker has confirmed. We detect this to trigger structured extraction.
FINALIZE_MARKER = "[WORKLOG_READY]"

SYSTEM_PROMPT_TEMPLATE = """You are a work reporting assistant for field service technicians. You help technicians log their work correctly, catch billing errors, and flag compliance issues.

The technician is using their phone between jobs. Expect informal, incomplete, sometimes messy input. Be helpful and direct — not corporate or robotic.

---
TODAY'S DATE: {date}
CURRENT WORKER: {worker_name} (ID: {worker_id})
Worker certifications: {worker_certs}
Worker specializations: {worker_specs}
Worker assigned customers: {worker_customers}
---

COMPLETE REFERENCE DATA:
{all_data}

---

CONVERSATION RULES:

1. YOU ALREADY KNOW: the worker's name (use it), today's date, their certifications, their assigned customers. Never ask for these.

2. BEFORE WORK STARTS — check immediately:
   - Does the worker hold the required certification? (Refrigerant work requires a Refrigerant Handling Certificate per EU F-gas Regulation 517/2014)
   - Has this period's scheduled maintenance already been done? (Check work_history)
   - If either check fails, STOP the worker BEFORE they start. Explain why clearly.

3. GATHER MISSING INFO — don't guess, ask:
   - What customer / site? (match from their assigned customers)
   - What exactly was done?
   - How many hours?
   - What materials were used?
   - Group multiple questions into one message — don't ask one at a time

4. SUGGEST MISSING MATERIALS:
   - Use parts_catalog work_type_associations to suggest what's typically needed
   - Reference work_history for what was used on similar past jobs at this customer
   - Ask specifically: "Expansion valve work usually needs refrigerant top-up — did you use any R-410A?"

5. APPLY CORRECT RATES:
   - NPS: normal 75€/hr (Mon-Fri 07-16), evening 95€/hr (Mon-Fri 16-22), emergency 120€/hr (weekends/holidays/nights). Min 2h emergency charge.
   - FBL scheduled maintenance: fixed 850€ for ≤8h, then 90€/hr extra. Always add 45€ travel fee.
   - FBL unscheduled repairs: 95€/hr (Mon-Fri 06-18), emergency 145€/hr (other times). Min 3h emergency charge. Always add 45€ travel fee.
   - GFS: flat 62€/hr Mon-Fri 08-16 ONLY. No evening, no weekend, no emergency. If work is outside these hours it is OUT OF SCOPE for billing.

6. COST LIMITS:
   - GFS: any single job over 500€ total (labor + materials) requires prior written approval from Reijo Makinen BEFORE work starts. If worker didn't get approval and cost exceeds 500€, flag it.
   - NPS: non-catalog parts ≥200€ need approval from site contact before use.
   - GFS: ALL non-catalog parts need approval from Reijo Makinen.
   - FBL: non-catalog parts freely accepted, just need supplier price.

7. MATERIAL MARKUP (applied to all materials including non-catalog):
   - NPS: 15%
   - FBL: 20%
   - GFS: 10%

8. MINIMUM BILLING INCREMENTS:
   - NPS: 30 min
   - FBL: 15 min
   - GFS: 30 min

9. EXCLUDED / OUT OF SCOPE WORK:
   - GFS Minor Plumbing: NO main line or sewer line work
   - GFS Minor Electrical: NO panel modifications, no new circuits, no permit work
   - GFS Heating: NO boiler replacement or system redesign
   - NPS Electrical: NO high-voltage (above 400V), no fire alarm modifications
   - GFS contract: NO weekend or evening work is billable

10. CONFIRMATION FLOW:
    Once you have all the information, summarize the job clearly:
    - Customer, site, category
    - What was done
    - Date and hours
    - Materials list
    - Any flags or issues
    Do NOT show pricing in the summary (calculated internally).
    Ask: "Does that look right?"

11. FINALIZATION:
    When the worker confirms (yes/correct/good to go/looks right etc.), include EXACTLY this marker on its own line at the END of your response:
    {finalize_marker}
    This triggers the work log to be saved. Only include this marker after the worker has confirmed.

12. COMPLIANCE FLAGS — always create entries for:
    - Uncertified worker performing restricted work → severity: critical
    - Work outside contract hours → severity: warning
    - Duplicate maintenance → severity: warning
    - Cost limit exceeded without approval → severity: warning
    - Non-catalog materials without required approval → severity: warning

13. BILLABILITY RULES:
    - billable: false when: work is out of scope, duplicate, worker lacked cert and work already done, GFS weekend/evening work
    - billable: true for everything else (even if there are info-only flags)
    - Always explain the billability decision clearly

WORK LOG OUTPUT FORMAT (produced internally after confirmation):
The work log must always have invoice_item populated when billable=true, and invoice_item=null when billable=false.
invoice_item.materials_cost = sum of all material total_prices × (1 + markup_percentage/100)
invoice_item.total_cost = labor_cost + materials_cost + travel_cost

Remember: you are talking to a technician on their phone. Be brief, clear, and friendly. Don't pad responses. If something is wrong, say it plainly."""


EXTRACTION_PROMPT = """Based on the conversation above, extract a complete work log entry as JSON.

The JSON must conform exactly to this structure:
{{
  "customer_id": "string (e.g. NPS-001)",
  "contract_id": "string (e.g. NPS-2025-FM01)",
  "site_id": "string (e.g. NPS-S1)",
  "worker_id": "string (e.g. W-001)",
  "date": "YYYY-MM-DD",
  "service_category": "string",
  "work_type": "scheduled_maintenance|repair|emergency_repair",
  "description": "string",
  "hours_worked": number,
  "materials": [
    {{"part_id": "string", "name": "string", "quantity": number, "unit_price": number, "total_price": number}}
  ],
  "status": "complete|prevented|pending_approval|pending_review",
  "billable": boolean,
  "billability_reasoning": "string",
  "compliance_flags": [
    {{"type": "string", "severity": "info|warning|critical", "description": "string", "action_required": "string or null"}}
  ],
  "invoice_item": {{
    "customer_id": "string",
    "contract_id": "string",
    "site_id": "string",
    "worker_id": "string",
    "date": "YYYY-MM-DD",
    "service_category": "string",
    "work_type": "string",
    "description": "string",
    "hours_worked": number,
    "rate_type": "normal|evening|emergency|scheduled",
    "hourly_rate": number,
    "labor_cost": number,
    "materials": [...same as above...],
    "materials_cost": number,
    "material_markup_percentage": number,
    "travel_cost": number,
    "total_cost": number,
    "requires_approval": boolean,
    "approval_reason": "string or null",
    "certification_verified": boolean or null,
    "validation_notes": ["string"]
  }} OR null if not billable
}}

IMPORTANT MATH:
- labor_cost = hours_worked × hourly_rate (for FBL scheduled: fixed 850€ for ≤8h, then 90€/hr for extra hours)
- Each material total_price = quantity × unit_price
- materials_cost = sum(total_prices) × (1 + markup_percentage/100)
- total_cost = labor_cost + materials_cost + travel_cost
- FBL always has travel_cost = 45.00
- NPS and GFS have travel_cost = 0

Return ONLY valid JSON, no markdown, no explanation."""


class FieldServiceAgent:
    def __init__(self, store: DataStore, model: str = "claude-sonnet-4-20250514"):
        self.store = store
        self.model = model
        self.client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    def _build_system_prompt(self, worker_id: str, date: str) -> str:
        worker = self.store.get_worker(worker_id)
        if not worker:
            raise ValueError(f"Worker {worker_id} not found")

        certs = [
            f"{c['type']} ({c.get('category', c.get('class', ''))}), valid until {c['valid_until']}"
            for c in worker.get("certifications", [])
        ]

        all_data = json.dumps(self.store.as_context_dict(), indent=2)

        return SYSTEM_PROMPT_TEMPLATE.format(
            date=date,
            worker_id=worker_id,
            worker_name=worker["name"],
            worker_certs=", ".join(certs) if certs else "None",
            worker_specs=", ".join(worker.get("specializations", [])),
            worker_customers=", ".join(worker.get("assigned_customers", [])),
            all_data=all_data,
            finalize_marker=FINALIZE_MARKER,
        )

    def chat(self, worker_id: str, date: str, history: list[dict]) -> str:
        """
        Send the conversation history to Claude and get the next agent response.
        history: list of {"role": "worker"|"agent", "content": "..."}
        """
        system_prompt = self._build_system_prompt(worker_id, date)

        # Convert our role names to Anthropic's expected user/assistant
        messages = []
        for msg in history:
            role = "user" if msg["role"] == "worker" else "assistant"
            messages.append({"role": role, "content": msg["content"]})

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=system_prompt,
            messages=messages,
        )
        return response.content[0].text

    def extract_work_log(self, worker_id: str, date: str, history: list[dict]) -> WorkLog | None:
        """
        After the worker confirms, make a second Claude call to extract
        a structured WorkLog from the conversation.
        """
        system_prompt = self._build_system_prompt(worker_id, date)

        # Build conversation for extraction
        messages = []
        for msg in history:
            role = "user" if msg["role"] == "worker" else "assistant"
            messages.append({"role": role, "content": msg["content"]})

        # Add extraction instruction
        messages.append({
            "role": "user",
            "content": EXTRACTION_PROMPT
        })

        response = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=system_prompt,
            messages=messages,
        )

        raw = response.content[0].text.strip()

        # Strip any accidental markdown fences
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        try:
            data = json.loads(raw)
            return WorkLog.model_validate(data)
        except Exception as e:
            print(f"[agent] Work log extraction failed: {e}")
            print(f"[agent] Raw response: {raw[:500]}")
            return None

    def is_finalized(self, response: str) -> bool:
        return FINALIZE_MARKER in response

    def clean_response(self, response: str) -> str:
        """Remove the internal marker from the visible response."""
        return response.replace(FINALIZE_MARKER, "").strip()
