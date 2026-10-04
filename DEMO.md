# Locus · 2-minute demo guide

The goal: in 120 seconds, prove the four things the challenge asks for — **automated
extraction from the corpus**, **correct legal jurisdiction**, **honest "unknown"**, and
**every answer traced to the sentence** — and make it look effortless.

Every click below was rehearsed on the live site (2026-10-04). Not legal advice.

---

## The story in one line

> "Housing law is a stack: state law, city law, dates, exemptions. **Locus** picks any building,
> works out which laws apply today, and shows you the exact sentence each answer comes from.
> When the data can't tell, it says *unknown* — it never guesses."

Three beats, each answering a judge's question:

| Beat | Judge's question | What proves it |
|---|---|---|
| 1. A building | "Does it actually work, and can I trust it?" | Superseded + conflict rows, the highlighted sentence |
| 2. The hard cases | "Did you handle the traps in the data?" | Mailing city ≠ legal city; *unknown* resolves live |
| 3. The machine | "Is it really automated and tested?" | Live extraction + quote check; T1–T5 all pass |

---

## 15 minutes before: setup checklist

Do these in order. Tick each one.

- [ ] **Wake the API** (it sleeps on the free plan; the first call takes 30–60 s):
      open <https://rental-law-navigator-api.onrender.com/health> → you see `"status":"ok"`.
- [ ] **Browser tab 1:** <https://rental-law-navigator.vercel.app>, full screen (F11), zoom
      100 %. Footer must **not** say "Offline data" (if it does, the API is still waking: reload in 30 s).
- [ ] **Browser tab 2:** <https://rental-law-navigator.vercel.app/changes> (scrolled to top).
- [ ] **Terminal** (big font, 20 pt+, dark theme), in the scratch copy — see
      [Terminal setup](#terminal-setup). Type the command but **do not press Enter**:
      ```
      python -m navigator extract --docs D001 --no-cache; python -m navigator verify
      ```
- [ ] Do Not Disturb on; close Slack, mail and other notifications.
- [ ] Phone hotspot ready as backup internet.
- [ ] Backup video of this exact run recorded and open in a player (see [Plan B](#plan-b)).
- [ ] Practice the two searches once so the browser remembers them:
      `1733 N Cherokee` and `227 Cypress`.

**Screen layout:** browser full screen; switch to the terminal with Alt+Tab. Two people is
ideal: one **driver** (clicks) and one **speaker** (talks). If you are alone, keep your
hands on the mouse and talk to the judges, not to the screen.

---

## The run of show (120 s)

Bold = what you click or type. Quotes = what you say. Keep moving: if something loads
slowly, keep talking — never wait in silence.

### 0:00 – 0:12 · Hook + start the machine

| Do | Say |
|---|---|
| Terminal is showing. **Press Enter** on the prepared command. | "Rules here aren't typed in by us. I've just started our extractor live on the Berkeley algorithmic-pricing ordinance — straight from the corpus text. We'll come back to it." |
| **Alt+Tab** to the browser (globe + intro card). | "This is Locus. Pick any building — see which housing laws apply, traced to the sentence." |

### 0:12 – 0:45 · Beat 1: one building, fully explained

| Do | Say | Screen shows |
|---|---|---|
| Type **`1733 N Cherokee`** in the search box, click the result. | "A 40-unit building in Hollywood." | Camera flies in, orbits; state and city layers rise over the roof. |
| Point at the two chips above the roof. | "Two layers of law: Los Angeles and California." | `Los Angeles · 21 rules` / `California · 45 rules` |
| Point at the first row, **"How much can my rent go up?"** | "The California rent cap is *superseded* here — the city's rent stabilization ordinance governs, and Locus says so." | `Applies` (city) + orange `Superseded: State rule steps aside` |
| Point at the red row, **"Can I be evicted without a reason?"** | "Where two laws disagree, we don't pick a winner. It's flagged for human review." | `Two laws disagree. A court would decide.` + `Conflict` |
| **Click the citation** on the right of the rent row (`City of Los Angeles Rent Stabilization Ordinance`). | "And every answer opens the official text — this is the exact sentence, with the date we retrieved it and what we could and couldn't check." | Source drawer: highlighted sentence, *Retrieved*, *Reasoning boundary* |
| **Esc** to close. | | |

### 0:45 – 1:08 · Beat 2: the traps in the data

| Do | Say | Screen shows |
|---|---|---|
| Type **`227 Cypress`**, click the result. | "This one's mailing address says San Ysidro. Legally, it's in the City of San Diego — we resolve that with the Census Geocoder, never the postal city." | `Mailing city: San Ysidro · Legal city: San Diego` |
| Point at the dashed **Unknown** box at the top. | "The public record has no year built. So instead of guessing, Locus says *unknown* — and names the missing fact." | `certificate of occupancy date (5), year built (5), …` |
| In **Year built**, type **`1995`**, click **Check again**. | "If you know it, type it in…" | |
| Point at the box again (≈5 s). | "…and ten answers are decided on the spot." | `year built` and `certificate of occupancy` disappear from the box |

### 1:08 – 1:28 · Beat 3a: time and the official tests

| Do | Say | Screen shows |
|---|---|---|
| Click the **Rent-setting software** filter (top). Drag the **date slider** from 2025 into **2026**. | "Laws change over time. Drag the date: California's new algorithmic-pricing law switches on, January 1, 2026." | Beacons recolor as the date crosses 2026-01-01 |
| **Ctrl+2** (Change tests tab). | "All five official change tests from the organizers' test file run automatically — every check passes." | `T1 … PASS 250/250`; scroll once to show T2–T5 |

### 1:28 – 1:45 · Beat 3b: back to the machine

| Do | Say | Screen shows |
|---|---|---|
| **Alt+Tab** to the terminal (extraction finished long ago). | "There's the extractor: the model read the ordinance and proposed rules. Then the verify gate checked every quote word-for-word against the source. Anything not found is rejected — the model can't invent law." | `D001-c001: … candidate(s)` then `… 0 rejected` |
| (optional, only if ahead of time) | "This ordinance is one of the guide's open questions: outside sources give two different effective dates. The text itself only shows it passed to print, so Locus records it as *pending*, not law — dates only ever come from the source text." | |

### 1:45 – 2:00 · Close

| Do | Say |
|---|---|
| **Alt+Tab** to tab 1. Click **ES** (bottom right), then **EN**. | "Tenant and owner views, English and Spanish." |
| Point at the footer. | "Every screen: the as-of date, the source, and *not legal advice*. Locus — every building, every law, traced to the sentence. Thank you." |

**Stop talking at 2:00 even if you skipped something.** Finishing on time beats one more
feature.

---

## Numbers you may quote

Only quote numbers from the generated eval (golden rule 14). Before the demo, read the
**Results** block in [README.md](README.md) (or `scores/eval_latest.txt`) and use those. As
generated on 2026-10-04:

- rules extracted, **every quote found verbatim** in its source (grounding 100 %);
- **all sample addresses** covered;
- change tests **T1–T5: 10 pass, 0 fail**;
- determinism: two full reruns are **byte-identical**.

Say them only if a judge asks "how do you know it's right?" — the demo itself is the proof.

---

## Judge Q&A (have one-sentence answers ready)

| They ask | You answer |
|---|---|
| "Couldn't the LLM hallucinate a law?" | "It can propose, but it can't store: every rule's quote must be found word-for-word in the source document, or it's rejected and logged." |
| "Is there an LLM when I click?" | "No. The model runs only at build time. Clicks hit precomputed JSON and a deterministic engine with unit tests." |
| "How do you handle missing data?" | "Fail closed: *unknown*, with the missing fact named. Never 'does not apply' when we're not sure." |
| "How did you get the legal city?" | "Census Geocoder places and county subdivisions — Dorchester resolves to Boston, San Ysidro to San Diego." |
| "What about laws that aren't passed yet?" | "Enacted, not-yet-effective, pending and failed are kept separate. Pending bills never count as law; the struck Massachusetts ballot question never produces a rent cap." |
| "How would this scale to a new city?" | "Add its official pages and its Census place, rerun the pipeline. No code changes." |
| "Is it reproducible?" | "Yes: LLM calls are cached by document hash and prompt version; two full reruns are byte-identical." |
| "Can a landlord use it to dodge rules?" | "Owner-facing text describes obligations only; we never generate ways around a rule. And it's not legal advice." |
| "What doesn't it do?" | "It can't check facts the public data lacks — owner type, tenancy length, rent amount. It lists those on every answer." |

---

## Terminal setup

Run the extraction demo in a **scratch copy**, so the live repo and its outputs never
change during the demo. Once, beforehand (PowerShell):

```powershell
git clone C:\Users\syedw\Downloads\Hack_Nation\Hack-Nation C:\Users\syedw\locus-demo
Copy-Item C:\Users\syedw\Downloads\Hack_Nation\Hack-Nation\.env C:\Users\syedw\locus-demo\
cd C:\Users\syedw\locus-demo
python -m navigator extract --docs D001 --no-cache; python -m navigator verify   # rehearse once
```

- Run it from inside `locus-demo` (so `python -m navigator` uses that copy).
- Needs `ANTHROPIC_API_KEY` in `.env` and a few cents of credit; it took ~22 s (extract) +
  ~9 s (verify) in rehearsal.
- `rerun-live` is for a **new** official page; it correctly refuses a document that is
  already in the corpus, so use the `extract --docs D001 --no-cache` command for the demo.

---

## Plan B

| If… | Then… |
|---|---|
| The footer says "Offline data" | Keep going: lookups, citations, the slider and the change tests all work on the bundled data. Skip "type 1995" (it needs the API) and say "with the API awake, typing a fact recomputes live." |
| The map stays blank / Wi-Fi drops | Switch to the phone hotspot; if still blank, play the backup video and narrate it with the same script. |
| The extraction errors (no credit, no network) | Say "here's the same run from rehearsal" and show the saved terminal output or the `Add a new law` panel, then move on. Never debug on stage. |
| You fall behind at 1:30 | Skip Beat 3a's slider; go straight to the terminal, then close. |

Record the backup video with Win+Alt+R (Xbox Game Bar) during your final rehearsal.

---

## Rehearse it three times

1. **Slow run** with this page open, checking every click lands.
2. **Timed run** with a stopwatch; cut words, not beats, until it fits 1:55.
3. **Dress run** exactly as on stage (full screen, big terminal font), and record it — that
   recording is your Plan B video.
