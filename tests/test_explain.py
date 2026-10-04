"""Plain-language layer: deterministic guards and the summaries stage with a fake LLM.

No network, no real model. Quotes here are synthetic placeholders, not law text.
"""
import json

import pytest

from navigator.explain import guards, plain

pytestmark = pytest.mark.smoke

QUOTE = ("The landlord may not increase the rent by more than 5 percent in any 12-month "
         "period, and must return the deposit within twenty-one days after March 1, 2030.")


def _check(sentence, role="tenant", status="in_force", quote=QUOTE, lang="en"):
    return guards.check(sentence, role=role, status=status, quote=quote, lang=lang)


# ------------------------------------------------------------------ number guard


def test_number_not_in_quote_is_dropped():
    reasons = _check("Your rent can rise at most 10% in any 12-month period, you should know.")
    assert "number_not_in_quote:10" in reasons


def test_quote_supported_percentage_passes():
    assert _check("Your rent can rise no more than 5% in any 12-month period.") == []
    assert _check("Your rent can rise no more than 5 percent in a year, you should know.") == []


def test_percent_must_be_a_percent_in_the_quote():
    # 12 appears in the quote, but not as a percentage
    assert "percent_not_in_quote:12" in _check("Your rent can rise at most 12% per year.")


def test_dollar_amount_not_in_quote_is_dropped():
    assert "number_not_in_quote:500" in _check("Your deposit is capped at $500, you should know.")


def test_spelled_numbers_and_dates_checked():
    assert _check("You get your deposit back within twenty-one days after March 1, 2030.") == []
    assert _check("You get your deposit back within 21 days.") == []
    bad = _check("You get your deposit back within thirty days after June 1, 2030.")
    assert "number_not_in_quote:30" in bad
    assert "month_not_in_quote:june" in bad


def test_modal_may_is_not_a_month():
    assert guards.number_guard("You may not raise the rent.", "No months here at all.") == []


# ------------------------------------------------------------------ evasion guard


@pytest.mark.parametrize("sentence", [
    "You can avoid the cap by renting the unit as a short-term stay.",
    "You can get around the limit with a new lease, you know.",
    "Your best loophole is a new lease.",
    "You can exempt yourself by filing a form.",
    "Your unit is exempt if you register it with the city.",
    "To qualify for an exemption, you must register.",
])
def test_evasion_wording_is_dropped(sentence):
    assert any(r.startswith("evasion_wording") for r in _check(sentence, role="tenant"))


def test_owner_text_may_not_mention_exemptions():
    reasons = _check("You must cap rent increases unless your unit is exempt.", role="owner")
    assert any(r.startswith("owner_mentions_exemption") for r in reasons)


def test_owner_text_must_state_an_obligation():
    assert "owner_not_obligation_wording" in _check("You are a landlord.", role="owner")
    assert _check("You may not raise the rent more than 5% in any 12-month period.",
                  role="owner") == []


# ------------------------------------------------------------------ form guard


def test_too_long_sentence_is_dropped():
    long = ("You " + "really " * 20 + "must return the deposit.")
    assert any(r.startswith("too_long") for r in _check(long))


def test_must_say_you_and_be_one_sentence():
    assert "no_you" in _check("The landlord must return the deposit.")
    assert "more_than_one_sentence" in _check("You get your deposit back. Your landlord must pay.")
    assert "does_not_start_with_answer" in _check("This rule says you get your deposit back.")
    assert _check(None) == ["no_answer"]


@pytest.mark.parametrize("status,ok,bad", [
    ("pending", "If passed, this proposed bill would bar your landlord from raising rent.",
     "Your landlord may not raise your rent."),
    ("not_yet_effective", "Once it takes effect, your landlord may not use pricing software.",
     "Your landlord may not use pricing software."),
    ("failed", "This measure failed and is not law, so your rent is not capped by it.",
     "Your rent is capped."),
])
def test_status_wording(status, ok, bad):
    assert _check(ok, status=status) == []
    assert f"status_wording_missing:{status}" in _check(bad, status=status)


def test_pending_cannot_read_as_current_law():
    reasons = _check("This proposed bill is now in effect for your rent.", status="pending")
    assert "phrased_as_in_force:pending" in reasons


def test_percent_spellings():
    assert guards.numbers("five per cent", "en") == [("5", "percent")]
    assert guards.numbers("5 percent", "en") == [("5", "percent")]
    assert guards.numbers("cinco por ciento", "es") == [("5", "percent")]


def test_spanish_guards():
    assert _check("Su renta no puede subir más del 5% en 12 meses.", lang="es") == []
    assert "number_not_in_quote:10" in _check("Su renta no puede subir más del 10%.", lang="es")
    assert any(r.startswith("evasion_wording")
               for r in _check("Usted puede evitar el límite.", lang="es"))
    assert "no_you" in _check("La renta no puede subir más del 5%.", lang="es")


# ------------------------------------------------------------------ stage with fake LLM


class FakeLLM:
    model = "fake-model"

    def __init__(self, answers):
        self.answers = answers  # label -> response dict
        self.calls = []

    def __call__(self, *, system, user, schema, key_parts, label):
        self.calls.append({"label": label, "key_parts": key_parts, "user": user})
        if label not in self.answers:
            raise RuntimeError("no fake answer")
        return {"data": self.answers[label], "cached": False, "model": self.model}


def _rule(rid, status="in_force", quote=QUOTE):
    return {"team_rule_id": rid, "jurisdiction": "XX", "level": "state",
            "category": "rent_increase_limits", "status": status, "title": "test rule",
            "requirement": "test requirement", "key_value": None, "coverage_conditions": None,
            "quoted_span": quote, "exemptions": "placeholder exemption text",
            "source_doc_id": "D000"}


@pytest.fixture
def no_audit(monkeypatch):
    logged = []
    monkeypatch.setattr(plain.audit, "log", lambda *a, **k: logged.append((a, k)))
    return logged


def test_run_writes_summaries_with_guards(tmp_path, no_audit):
    rules = [_rule("r-0001"), _rule("r-0002", status="pending"), _rule("r-0003"),
             _rule("r-0004", status="failed")]
    (tmp_path / "rules.json").write_text(json.dumps({"as_of": "2030-01-01", "rules": rules}))
    fake = FakeLLM({
        "r-0001-en": {"answer_tenant": "Your rent can rise at most 5% in any 12-month period.",
                      "answer_owner": "You may not raise rent more than 7% a year."},
        "r-0001-es": {"answer_tenant_es": "Su renta puede subir como máximo 5% en 12 meses.",
                      "answer_owner_es": "should not be used"},
        "r-0002-en": {"answer_tenant": "Your landlord may not raise your rent.",
                      "answer_owner": "If passed, this proposed bill would bar you from raising rent."},
        "r-0002-es": {"answer_tenant_es": None,
                      "answer_owner_es": "Si se aprueba, este proyecto le prohibiría subir la renta 9%."},
        # r-0003: LLM error -> both dropped
    })
    out = tmp_path / "summaries.json"
    doc = plain.run(caller=fake, rules_path=tmp_path / "rules.json", out_path=out, workers=1)

    written = json.loads(out.read_text(encoding="utf-8"))
    assert written == doc
    assert set(doc) == {"generated_at", "prompt_version", "model", "disclaimer", "summaries"}
    assert doc["disclaimer"] == "Not legal advice."
    assert doc["prompt_version"] == plain.PROMPT_VERSION
    s = doc["summaries"]

    r1 = s["r-0001"]
    assert r1["answer_tenant"].startswith("Your rent")
    assert r1["answer_owner"] is None
    assert "owner: number_not_in_quote:7" in r1["dropped"]
    assert r1["answer_tenant_es"].startswith("Su renta")
    assert "answer_owner_es" not in r1  # English owner answer was dropped, so no translation
    assert r1["source_quote_sha"] == plain.sha256(QUOTE)

    r2 = s["r-0002"]
    assert r2["answer_tenant"] is None
    assert "tenant: status_wording_missing:pending" in r2["dropped"]
    assert r2["answer_owner"].startswith("If passed")
    assert "answer_owner_es" not in r2
    assert any(d.startswith("owner_es: number_not_in_quote:9") for d in r2["dropped"])

    r3 = s["r-0003"]
    assert r3["answer_tenant"] is None and r3["answer_owner"] is None
    assert any(d.startswith("llm_error") for d in r3["dropped"])

    r4 = s["r-0004"]
    assert r4["answer_tenant"] is None and r4["answer_owner"] is None
    assert not any(c["label"].startswith("r-0004") for c in fake.calls)

    # the model never sees exemptions; cache key carries the rule content sha
    en_call = next(c for c in fake.calls if c["label"] == "r-0001-en")
    assert "placeholder exemption text" not in en_call["user"]
    assert en_call["key_parts"]["task"] == "en" and len(en_call["key_parts"]["rule_sha"]) == 64
    assert any(a[1] == "summary_partial" for a, _ in no_audit)


def test_rule_sha_changes_with_quote(no_audit):
    fake = FakeLLM({})
    plain.summarize_rule(_rule("r-0001"), fake, spanish=False)
    plain.summarize_rule(_rule("r-0001", quote=QUOTE + " Extra words."), fake, spanish=False)
    shas = {c["key_parts"]["rule_sha"] for c in fake.calls}
    assert len(shas) == 2


def test_repair_is_rechecked_and_never_used_for_evasion(no_audit):
    fake = FakeLLM({
        "r-0001-en": {"answer_tenant": "You " + "really " * 20 + "get a capped rent.",
                      "answer_owner": "You can avoid the cap with a new lease."},
        # repair fixes the length but sneaks in an unsupported number: still dropped
        "r-0001-en-repair": {"answer_tenant": "Your rent can rise at most 9% a year.",
                             "answer_owner": "unused"},
        "r-0002-en": {"answer_tenant": "You " + "really " * 20 + "get a capped rent.",
                      "answer_owner": "You must not raise rent more than 5% in any 12-month period."},
        "r-0002-en-repair": {"answer_tenant": "Your rent can rise at most 5% in any 12-month period.",
                             "answer_owner": "You must not raise rent more than 5% in any 12-month period."},
    })
    r1 = plain.summarize_rule(_rule("r-0001"), fake, spanish=False)
    assert r1["answer_tenant"] is None and r1["answer_owner"] is None
    assert "tenant: number_not_in_quote:9" in r1["dropped"]
    assert any(d.startswith("owner: evasion_wording") for d in r1["dropped"])
    repair = next(c for c in fake.calls if c["label"] == "r-0001-en-repair")
    assert "answer_owner" not in repair["user"].split("## Failed checks")[1]  # evasion not repaired

    r2 = plain.summarize_rule(_rule("r-0002"), fake, spanish=False)
    assert r2["answer_tenant"] == "Your rent can rise at most 5% in any 12-month period."
    assert r2["dropped"] == []


def test_prompt_file_has_all_sections():
    p = plain.prompts()
    assert "answer_tenant" in p["en"] and "answer_owner_es" in p["es"]
    assert p["repair"].startswith("## Repair")
    assert len(plain.prompt_sha()) == 64
