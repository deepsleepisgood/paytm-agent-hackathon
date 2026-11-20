"""Shared pytest setup for the merchant agent.

* 8001/8002 point at a dead port, so every upstream call exercises its fallback.
  All URL names are set, so a local .env can't point tests at real services.
* The dataset is chosen explicitly per test module via `use_dataset(...)`. NO_DATASET pins
  the built-in CONTRACT.md seed; REAL_DATASET is the team's repo-root dataset/ (if present).
"""
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
REAL_DATASET = Path(os.environ.get("DATASET_DIR") or next(
    (p for p in (HERE.parents[1] / "data", HERE.parents[1] / "dataset") if p.is_dir()), HERE.parents[1] / "data"))
NO_DATASET = HERE / "_no_dataset_"  # never created -> every file falls back to built-in

for _k in ("SARVAM_URL", "SARVAM_SERVICE_URL", "PAYTM_URL", "PAYTM_AGENT_URL"):
    os.environ[_k] = "http://127.0.0.1:9"
os.environ["SARVAM_API_BASE"] = "http://127.0.0.1:9"  # transliterate-for-voice must not reach the real Sarvam API
os.environ["UPSTREAM_TIMEOUT_S"] = "1"
os.environ["DOC_EXTRACT_TIMEOUT_S"] = "1"
os.environ["DATASET_DIR"] = str(NO_DATASET)
# Most suites here run with Paytm (8002) deliberately offline to pin the reply templates built from mock data.
# triage.py would replace those replies with the honest "Paytm isn't responding" fallback, so its policies are
# off by default in tests; test_triage.py switches them on.
os.environ.setdefault("TRIAGE_FALLBACK", "0")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import dataset_loader as dl  # noqa: E402
import upstream  # noqa: E402
from main import app  # noqa: E402

MID = "PAYTM_MERCH_8821"


def use_dataset(root: Path) -> "dl.Dataset":
    """Switch the running service to `root`; /reset keeps using it."""
    data = dl.reload(root)
    upstream.reset_mock_ledger()
    return data


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def ask(client, text, consent=True):
    return client.post("/merchant/query", json={"text": text, "mid": MID, "consent_granted": consent})


def upload(client, name, data, doc_type, consent="true"):
    return client.post(
        "/merchant/upload-doc",
        files={"file": (name, data, "image/png")},
        data={"doc_type": doc_type, "mid": MID, "consent_granted": consent},
    )
