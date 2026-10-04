"""Deterministic guards for plain-language answers (CLAUDE.md golden rules 7, 9, 11).

Every check returns a list of failure reasons; an empty list means the sentence passes.
A sentence with any failure is dropped (null) and the UI shows the quote instead.
No law facts live here: only English/Spanish wording patterns.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

MAX_WORDS = 20

# ------------------------------------------------------------------ numbers

_UNITS_EN = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19,
}
_TENS_EN = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
            "seventy": 70, "eighty": 80, "ninety": 90}
_BIG_EN = {"hundred": 100, "thousand": 1000}
_WORDS_ES = {
    "cero": 0, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
    "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13,
    "catorce": 14, "quince": 15, "dieciséis": 16, "diecisiete": 17, "dieciocho": 18,
    "diecinueve": 19, "veinte": 20, "treinta": 30, "cuarenta": 40, "cincuenta": 50,
    "sesenta": 60, "setenta": 70, "ochenta": 80, "noventa": 90, "cien": 100, "ciento": 100,
    "mil": 1000,
}
MONTHS_EN = ["january", "february", "march", "april", "may", "june", "july", "august",
             "september", "october", "november", "december"]
MONTHS_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
             "septiembre", "octubre", "noviembre", "diciembre"]

_DIGITS = re.compile(r"(\$\s?)?(\d[\d,]*(?:\.\d+)?)(?:st|nd|rd|th)?(\s?%|\s+per\s?cent|\s+por\s+ciento|\s+dollars)?",
                     re.IGNORECASE)
_WORD = re.compile(r"[a-záéíóúñü]+(?:-[a-záéíóúñü]+)?", re.IGNORECASE)


def _norm(num: str) -> str | None:
    try:
        d = Decimal(num.replace(",", ""))
    except InvalidOperation:
        return None
    d = d.normalize()
    return format(d, "f")


def _word_value(token: str, lang: str) -> int | None:
    t = token.lower()
    if lang == "es":
        return _WORDS_ES.get(t)
    if "-" in t:
        a, _, b = t.partition("-")
        if a in _TENS_EN and b in _UNITS_EN and _UNITS_EN[b] < 10:
            return _TENS_EN[a] + _UNITS_EN[b]
        # e.g. "one-half", "two-thirds": the leading number word still counts
        return _word_value(a, lang) if a != t else None
    return _UNITS_EN.get(t, _TENS_EN.get(t, _BIG_EN.get(t)))


def numbers(text: str, lang: str = "en") -> list[tuple[str, str]]:
    """[(normalized value, kind)] for every number in `text`; kind is 'percent', 'dollar'
    or 'plain'. Spelled-out numbers count as numbers (golden rule 7)."""
    out: list[tuple[str, str]] = []
    for m in _DIGITS.finditer(text):
        value = _norm(m.group(2).rstrip(",."))
        if value is None:
            continue
        suffix = re.sub(r"\s+", " ", (m.group(3) or "").strip().lower())
        if suffix in ("%", "percent", "per cent", "por ciento"):
            kind = "percent"
        elif m.group(1) or suffix == "dollars":
            kind = "dollar"
        else:
            kind = "plain"
        out.append((value, kind))
    words = list(_WORD.finditer(text))
    for i, m in enumerate(words):
        v = _word_value(m.group(0), lang)
        if v is None:
            continue
        if (lang == "es" and m.group(0).lower() == "ciento" and i
                and words[i - 1].group(0).lower() == "por"):
            continue  # "por ciento" is the percent sign, not the number 100
        rest = text[m.end():m.end() + 14].lower()
        if rest.lstrip().startswith(("percent", "per cent", "por ciento")) or rest.startswith("%"):
            kind = "percent"
        elif rest.lstrip().startswith(("dollar", "dólar")):
            kind = "dollar"
        else:
            kind = "plain"
        out.append((str(v), kind))
    return out


def _months(text: str, lang: str) -> list[int]:
    """Month indexes (0-11) named in text. English "may" counts only before a digit."""
    names = MONTHS_ES if lang == "es" else MONTHS_EN
    found = []
    for i, name in enumerate(names):
        pat = rf"\b{name}\b" + (r"(?=\s+\d)" if name == "may" else "")
        if re.search(pat, text, re.IGNORECASE):
            found.append(i)
    return found


def number_guard(sentence: str, quote: str, lang: str = "en") -> list[str]:
    """Every number, percentage, dollar amount and month name in `sentence` must appear
    in `quote` (the quote is always English source text)."""
    reasons: list[str] = []
    q_nums = numbers(quote, "en")
    q_values = {v for v, _ in q_nums}
    q_typed = set(q_nums)
    for value, kind in numbers(sentence, lang):
        if value not in q_values:
            reasons.append(f"number_not_in_quote:{value}")
        elif kind in ("percent", "dollar") and (value, kind) not in q_typed:
            reasons.append(f"{kind}_not_in_quote:{value}")
    q_months = set(_months(quote, "en"))
    for m in _months(sentence, lang):
        if m not in q_months:
            reasons.append(f"month_not_in_quote:{MONTHS_EN[m]}")
    return sorted(set(reasons))


# ------------------------------------------------------------------ evasion

_EVASION_EN = [
    r"\bavoid\w*", r"\bget(?:ting)? around\b", r"\bgo(?:ing)? around\b", r"\bloophole", r"\bwork-?arounds?\b",
    r"\bwork around\b", r"\bcircumvent", r"\bevad\w*", r"\bevasion", r"\bsidestep", r"\bbypass",
    r"\bdodg\w*", r"\bskirt\w*", r"\bescape\w*", r"\bexempt yourself", r"\bqualif\w* for (?:an? )?exempt",
    r"\b(?:to|can|could) (?:be|become|stay|remain) exempt", r"\bget (?:an? )?exemption",
    r"\bexempt\w*\s+(?:if|when|by|as long as|provided|so long as)\b",
    r"\b(?:if|when|by|so that|as long as)\b[^.;]*\bexempt", r"\bnot apply (?:to you )?if\b",
]
_EVASION_ES = [
    r"\bevit\w*", r"\beludi\w*", r"\bevadi\w*", r"\bevasi\w*", r"\blaguna", r"\bresquicio",
    r"\bsortear", r"\bburlar", r"\bdarle la vuelta", r"\bsaltarse", r"\bexent\w*\s+(?:si|cuando)\b",
    r"\b(?:si|cuando|para)\b[^.;]*\bexen", r"\bcalificar para (?:una )?exenci",
]
_EXEMPT_ANY = {"en": r"\bexempt\w*|\bexception", "es": r"\bexen\w*|\bexcepci"}


def evasion_guard(sentence: str, role: str, lang: str = "en") -> list[str]:
    """Drop wording that helps anyone avoid or qualify out of a rule (golden rule 11).
    Owner text may not mention exemptions at all: it describes obligations only."""
    pats = _EVASION_ES if lang == "es" else _EVASION_EN
    reasons = [f"evasion_wording:{m.group(0).strip().lower()}"
               for p in pats for m in [re.search(p, sentence, re.IGNORECASE)] if m]
    if role == "owner":
        m = re.search(_EXEMPT_ANY[lang], sentence, re.IGNORECASE)
        if m:
            reasons.append(f"owner_mentions_exemption:{m.group(0).lower()}")
    return sorted(set(reasons))


# ------------------------------------------------------------------ form

_YOU = {"en": r"\b(?:you|your|yours|you're|you've|you'll)\b",
        "es": r"\b(?:usted|ustedes|su|sus|le|les)\b"}
_LEADINS = ("this rule", "this law", "this section", "this provision", "according to",
            "in summary", "note:", "the law says", "the rule says", "esta regla", "esta ley",
            "según", "en resumen")
_OWNER_DUTY = {
    "en": r"\b(?:must|may not|may only|cannot|can't|can not|can only|have to|has to|need to|"
          r"required|requires?|prohibit\w*|not allowed|barred|bars?|bans?|banned|unlawful|"
          r"limited|limits?|no more than|at most|up to|only|would (?:have to|need to|require|"
          r"bar|ban|prohibit|limit|make it unlawful))\b",
    "es": r"\b(?:debe\w*|deberá\w*|no puede\w*|no podrá\w*|solo|sólo|tiene que|tendrá que|"
          r"tendría que|obligad\w*|prohib\w*|requier\w*|exig\w*|límite|limit\w*|no más de|"
          r"como máximo|hasta|ilegal)\b",
}
_STATUS_MARKERS = {
    "pending": {
        "en": r"\b(?:proposed|proposal|pending|bill|would|if (?:passed|enacted|adopted|approved)|"
              r"not (?:yet )?law|not in effect)\b",
        "es": r"\b(?:propuest\w*|pendiente|proyecto|si se aprueba|aún no|todavía no|"
              r"no es ley|podría|requeriría|prohibiría|exigiría|limitaría|establecería|permitiría|"
              r"haría|tendría|debería|impediría|obligaría|crearía)\b",
    },
    "not_yet_effective": {
        "en": r"\b(?:once|starting|will|takes effect|take effect|not yet|not in effect yet|"
              r"upcoming|beginning|when it takes effect)\b",
        "es": r"\b(?:una vez|a partir|entrará|entre en vigor|aún no|todavía no|cuando|"
              r"comenzará|\w+rá)\b",
    },
    "failed": {
        "en": r"\b(?:failed|rejected|not law|did not pass|was not (?:adopted|approved|enacted))\b",
        "es": r"\b(?:fracas\w*|rechaz\w*|no es ley|no se aprob\w*|no fue aprobad\w*)\b",
    },
}
# pending / not-yet-effective / failed text must not read as current law
_PRESENT_LAW = {"en": r"\b(?:is now in effect|currently|now requires|is the law|is in effect)\b",
                "es": r"\b(?:ya está en vigor|actualmente|está vigente)\b"}


def form_guard(sentence: str, role: str, status: str, lang: str = "en") -> list[str]:
    reasons: list[str] = []
    s = sentence.strip()
    if not s:
        return ["empty"]
    if "\n" in s:
        reasons.append("multiple_lines")
    n_words = len(s.split())
    if n_words > MAX_WORDS:
        reasons.append(f"too_long:{n_words}_words")
    body = s.rstrip(".!?")
    if re.search(r"[.!?;]\s+\S", body):
        reasons.append("more_than_one_sentence")
    if not re.search(_YOU[lang], s, re.IGNORECASE):
        reasons.append("no_you")
    if s.lower().lstrip("¿¡\"' ").startswith(_LEADINS):
        reasons.append("does_not_start_with_answer")
    if role == "owner" and not re.search(_OWNER_DUTY[lang], s, re.IGNORECASE):
        reasons.append("owner_not_obligation_wording")
    if status in _STATUS_MARKERS:
        if not re.search(_STATUS_MARKERS[status][lang], s, re.IGNORECASE):
            reasons.append(f"status_wording_missing:{status}")
        if re.search(_PRESENT_LAW[lang], s, re.IGNORECASE):
            reasons.append(f"phrased_as_in_force:{status}")
    elif status != "in_force":
        reasons.append(f"unknown_status:{status}")
    return reasons


def check(sentence: str | None, *, role: str, status: str, quote: str,
          lang: str = "en") -> list[str]:
    """All guards for one sentence. None (model returned nothing) is a failure."""
    if sentence is None or not str(sentence).strip():
        return ["no_answer"]
    return (form_guard(sentence, role, status, lang)
            + number_guard(sentence, quote, lang)
            + evasion_guard(sentence, role, lang))
