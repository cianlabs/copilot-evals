"""Offline contract checks for the incident triage module in runbook-copilot.

Run with RUNBOOK_COPILOT_PATH=/path/to/runbook-copilot python -m unittest test_incident_triage_contract.py
"""
import os
import sys
import unittest
from pathlib import Path

path = os.environ.get("RUNBOOK_COPILOT_PATH")
if path:
    sys.path.insert(0, str(Path(path).resolve()))
else:
    sys.path.insert(0, str((Path(__file__).resolve().parent.parent / "runbook-copilot").resolve()))

class IncidentContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from incident_triage import triage
        except ImportError as exc:
            raise unittest.SkipTest("Set RUNBOOK_COPILOT_PATH to a checkout containing incident_triage.py") from exc
        cls.triage = staticmethod(triage)

    def test_no_evidence_means_no_confirmed_cause(self):
        result = self.triage({"incident_id": "E-1", "symptom": "reconstruction unavailable", "impact": "blocked"})
        self.assertEqual(len(result["hypotheses"]), 3)
        self.assertIsNone(result["confirmed_root_cause"])
        self.assertTrue(all(h["status"] == "unverified" for h in result["hypotheses"]))

    def test_every_evidence_reference_exists(self):
        incident = {"incident_id": "E-2", "symptom": "reconstruction failed", "impact": "blocked", "evidence": [{"id": "log1", "source": "worker.log", "observation": "worker exception"}]}
        result = self.triage(incident)
        ids = {e["id"] for e in result["incident"]["evidence"]}
        for hypothesis in result["hypotheses"]:
            self.assertTrue(set(hypothesis["supporting_evidence_ids"]) <= ids)

    def test_simulation_only(self):
        result = self.triage({"incident_id": "E-3", "symptom": "failure", "impact": "blocked"})
        self.assertEqual(result["action_mode"], "simulation_only")

if __name__ == "__main__":
    unittest.main()
