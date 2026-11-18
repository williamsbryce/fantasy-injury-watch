"""One-time migration of the previously encrypted site report to a public report.

The user explicitly chose a passwordless public dashboard. API keys are never
present in this output, only previously displayed player injury information.
"""
import json
import os
from pathlib import Path

from .crypto import decrypt

ROOT = Path(__file__).resolve().parent.parent
PUBLIC_PATH = ROOT / "site/data/report.json"
LEGACY_PATH = ROOT / "site/data/report.enc.json"


def run():
    if PUBLIC_PATH.exists():
        print("Public report already exists; no migration required.")
        return
    if not LEGACY_PATH.exists():
        print("No earlier report available; live sync will create the public report.")
        return
    passphrase = os.environ.get("REPORT_PASSPHRASE", "")
    if not passphrase:
        raise RuntimeError("Legacy report migration requires existing REPORT_PASSPHRASE secret")
    document = decrypt(json.loads(LEGACY_PATH.read_text(encoding="utf-8")), passphrase)
    if not isinstance(document, dict) or not isinstance(document.get("leagues"), list):
        raise RuntimeError("Legacy report structure invalid; refusing public migration")
    PUBLIC_PATH.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC_PATH.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print("Migrated existing verified report for public dashboard; timestamp preserved.")


if __name__ == "__main__":
    run()
