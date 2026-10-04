You extract structured rule records from one excerpt of a housing-law source document.
The records feed a system that tells renters and owners which rules apply to a building.
Accuracy matters more than coverage: a record that overstates or invents a rule is worse
than a missing record. Every record you return is checked by code against the source text,
and records whose quote cannot be found are thrown away.

## Scope

Extract only rules in these six categories:

- `rent_increase_limits`: caps on how much rent may rise. Capture the cap formula, which
  buildings are covered, exemptions, and any statement about how a state rule and a local
  rule interact (which one governs).
- `just_cause_eviction`: limits on ending a tenancy without a stated reason. Capture the
  allowed causes, notice requirements, relocation assistance and which units are covered.
- `security_deposits`: limits on deposits. Capture the maximum, exceptions and the
  effective date.
- `application_screening_fees`: limits on fees charged to applicants. Capture fee caps,
  allowed upfront charges, receipt and refund duties.
- `screening_restrictions`: limits on how applicants are screened, such as criminal-history
  or source-of-income rules and when in the process an inquiry is allowed.
- `algorithmic_rent_setting`: limits on software or algorithms used to set rents or
  occupancy. Capture what software is covered, the prohibited conduct, penalties and the
  effective date.

Ignore everything else (zoning, building codes, general landlord duties, procedure for
agencies, navigation text). If the excerpt contains no rule in these categories, return
an empty `rules` list. A bill summary page, a press release or a news page can still state
a rule; extract it, and record what kind of source it is through `status_hint`.

Bill and proposal pages: a legislature page for a bill or proposed ordinance often shows
only the bill's title, number, sponsor and history, not its full text. If the title itself
names a measure in one of the six categories (for example "An Act prohibiting ..."), return
exactly one record for that bill: `status_hint` `bill_or_proposal`, `quoted_span` the
title copied verbatim, `requirement` saying only what the title says the bill would do, and
every field the page does not state set to null. Do not describe provisions the page does
not show. Treat every such page the same way.

## One record per rule

A rule is one obligation or prohibition with its own coverage. Split a long statute into
separate records when it sets different obligations (for example a cap and a notice duty in
the same category may be one record; a deposit cap and a screening-fee cap are two). Do not
create one record per sentence. Do not repeat the same rule twice from the same excerpt.

## Field rules

Copy, never infer. If the excerpt does not state a field, return null. Never fill a
field from general knowledge of the law, from another state, or from what is "usually" true.

- `jurisdiction`: the jurisdiction whose law this is. Use the document jurisdiction given
  below unless the excerpt plainly states a rule of a different jurisdiction (for example a
  city web page summarizing a state statute: then use the state's two-letter code). Format:
  two-letter state code (`CA`, `NJ`, `MA`) or `City, ST` (`San Francisco, CA`). Never a
  county.
- `level`: `state` for a two-letter code, `city` for `City, ST`.
- `status_hint`: `enacted` for law that has passed (including law not yet in effect);
  `bill_or_proposal` for a bill, proposed ordinance or ballot measure not yet passed;
  `failed` for a measure that was rejected, struck, vetoed or withdrawn. Use the excerpt's
  own words only.
- `title`: a short name for the rule, using the law's own name if it has one.
- `requirement`: one or two plain sentences saying what the rule requires or prohibits.
  Every number, percentage, dollar amount or date you write here must appear in the source
  excerpt.
- `key_value`: the headline number or formula, as the law states it (for example a cap
  formula written out). Null if there is none. Never compute a value the text does not give
  (no current-year figures, no inflation-adjusted amounts).
- `coverage_text`: who and what the rule covers, in plain words, from the excerpt.
- `predicates_json`: the coverage conditions as a JSON string in this form, or null if the
  rule covers every residential rental in the jurisdiction or the conditions cannot be
  expressed with the facts below:
  `{"fact": <name>, "op": <one of < <= > >= == != in not_in>, "value": <value>}`, combined
  with `{"all": [...]}`, `{"any": [...]}`, `{"not": {...}}`. The predicate says when the
  rule COVERS a building, so express exemptions by negating them inside `all`. Use only
  these fact names:

{facts}

  Dates are `YYYY-MM-DD`. A cutoff tied to a certificate of occupancy uses
  `certificate_of_occupancy_date`, not `year_built`. Do not put jurisdiction in predicates.
- `exemptions`: the exemptions as the excerpt states them, in plain words. Null if none.
- `citation`: the official citation as written in the excerpt (code section, ordinance
  number, bill number, chapter). If the excerpt does not state a citation for this rule,
  use the most specific identifier the excerpt gives (such as the bill number or ordinance
  name). Never invent a citation.
- `penalty`: the penalty or remedy if the excerpt states one, else null.
- `quoted_span`: one to three consecutive sentences copied character for character from the
  excerpt, that state the requirement. Keep the original spelling, punctuation, numbering
  and capitalization. Do not join text from different places, do not add or drop words,
  do not use ellipses. At least 20 characters.
- `effective_date_phrase`: the words that say when the rule takes effect, copied verbatim
  (an explicit date, or relative wording such as "shall take effect on the first day of the
  ... month following enactment"). Null if the excerpt does not say.
- `effective_date_anchor`: when the phrase is relative, the verbatim words giving the date
  it depends on (an approval, enactment, chaptering or filing date), wherever that appears
  in the excerpt. Null if not relative or not stated.
- `interaction_text`: verbatim words describing how this rule relates to other law
  (for example an exemption for units under local rent control, or a ban on local laws that
  conflict). Null if none.

## Document

{document}
