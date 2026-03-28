import json
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).parent / "data"


class DataStore:
    def __init__(self):
        self.contracts: dict = self._load("contracts.json")
        self.workers: dict = self._load("workers.json")
        self.work_history: dict = self._load("work_history.json")
        self.parts_catalog: dict = self._load("parts_catalog.json")
        self.work_queue: dict = self._load("work_queue.json")
        self.example_conversations: dict = self._load("example_conversations.json")

        # Build lookup indexes
        self._workers_by_id: dict[str, dict] = {
            w["worker_id"]: w for w in self.workers["workers"]
        }
        self._customers_by_id: dict[str, dict] = {
            c["customer_id"]: c for c in self.contracts["customers"]
        }
        self._parts_by_id: dict[str, dict] = {
            p["part_id"]: p for p in self.parts_catalog["parts"]
        }

    def _load(self, filename: str) -> dict:
        path = DATA_DIR / filename
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_worker(self, worker_id: str) -> dict | None:
        return self._workers_by_id.get(worker_id)

    def get_customer(self, customer_id: str) -> dict | None:
        return self._customers_by_id.get(customer_id)

    def get_work_history_for_customer(self, customer_id: str) -> list[dict]:
        return [
            r for r in self.work_history["work_records"]
            if r["customer_id"] == customer_id
        ]

    def get_upcoming_jobs_for_worker(self, worker_id: str) -> list[dict]:
        return [
            j for j in self.work_queue["work_queue"]
            if j["assigned_worker_id"] == worker_id
        ]

    def get_part(self, part_id: str) -> dict | None:
        return self._parts_by_id.get(part_id)

    def as_context_dict(self) -> dict[str, Any]:
        """Return all data as a single dict for embedding in the system prompt."""
        return {
            "contracts": self.contracts,
            "workers": self.workers,
            "work_history": self.work_history,
            "parts_catalog": self.parts_catalog,
            "work_queue": self.work_queue,
            "example_conversations": self.example_conversations,
        }


# Singleton
_store: DataStore | None = None


def get_store() -> DataStore:
    global _store
    if _store is None:
        _store = DataStore()
    return _store
