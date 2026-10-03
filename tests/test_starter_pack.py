"""The starter pack is read-only input. These checks fail if anyone edits it."""
import hashlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STARTER = ROOT / "data" / "starter"
CHECKSUMS = ROOT / "data" / "STARTER_CHECKSUMS.sha256"


def _recorded() -> dict[str, str]:
    out = {}
    for line in CHECKSUMS.read_text(encoding="utf-8").splitlines():
        digest, rel = line.split("  ", 1)
        out[rel] = digest
    return out


@pytest.mark.smoke
def test_starter_pack_unchanged():
    recorded = _recorded()
    on_disk = {
        p.relative_to(STARTER).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in STARTER.rglob("*")
        if p.is_file()
    }
    assert set(on_disk) == set(recorded), "files added to or removed from data/starter"
    changed = [rel for rel, d in on_disk.items() if recorded[rel] != d]
    assert not changed, f"starter files modified: {changed}"


@pytest.mark.smoke
def test_starter_pack_has_expected_inputs():
    # Counts from docs/CONTRACT.md 1; a mismatch means the wrong pack was unpacked.
    assert len(list((STARTER / "corpus" / "text").glob("D*.txt"))) == 54
    for rel in (
        "corpus/corpus_manifest.csv",
        "corpus/links_only.csv",
        "data/sample_addresses.csv",
        "schema/rule_record.schema.json",
        "schema/sample_rule_record.json",
        "dev/change_tests.json",
        "submission_templates/rules.json",
        "submission_templates/lookups.json",
        "submission_templates/changes.json",
    ):
        assert (STARTER / rel).is_file(), rel
