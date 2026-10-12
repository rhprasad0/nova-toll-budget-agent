# Two-person TollChat user study

**Status:** plan, not yet run (drafted 2026-10-12).

Two participants cannot give success rates or generalize. This pilot has three
narrower jobs:

1. Test the asynchronous protocol before a 5–8 person study.
2. Compare real users with the golden-eval actor on identical task cards.
3. Find real wording and failure modes to turn into eval cases.

The actor profile and prompt stay unchanged. Changing them is an evaluator
contract change that needs a new combined calibration
([authoring guide](AUTHORING.md)); two people are not enough evidence for that.

## Research basis

- LLM-simulated users are more cooperative than people. They state every fact
  up front, rarely express uncertainty, change course quietly instead of
  pushing back, and inflate agent success
  ([Sim2Real gap, 2026](https://arxiv.org/abs/2603.11245);
  [Lost in Simulation, ACL 2026](https://aclanthology.org/2026.acl-long.2192.pdf);
  [realsim, 2026](https://arxiv.org/pdf/2605.02624)).
- In the τ-bench human study, users rather than the agent caused most failed
  human conversations, often by misreading task instructions (Lost in Simulation).
- Simulators rarely end a conversation; people often stop within a few turns
  ([Ivey et al., 2024](https://arxiv.org/pdf/2409.08330)).
- People refine what counts as a good answer while looking at answers
  ("criteria drift", [Shankar et al., 2024](https://arxiv.org/pdf/2404.12272)),
  so ask for expectations before each task.
- Unmoderated tasks must stand alone, say when to stop, avoid the interface's
  own wording, and be piloted
  ([NN/g](https://www.nngroup.com/articles/unmoderated-usability-testing/)).

## Before the study

- **Deployment:** confirm dev.tollchat.ai serves the 20-turn cap and
  refresh-restore from #697.
- **Rate limit:** development WAF blocks an IP after 10 POSTs to `/api/` within
  5 minutes (`v2/infra/environment.tf`). Each message is a POST, and so are New
  chat and a page load without a saved chat (`/api/reset`). One task uses about
  six, so the session leaves a 5-minute gap between tasks. A blocked page load
  leaves the chat disabled until reload. Participants on one network share the
  limit.
- **Linking:** traces carry no participant or session identifier, so give each
  participant a separate, recorded time window and match traces by time.
- **Traces:** check one development trace end to end for complete tool inputs
  and results after redaction and size limits; the pasted chat does not contain
  them. Traces expire after 7 days, so export them that week.
- **Clarity is optional for this pilot.** It always masks input boxes, but the
  default Balanced mode masks only numbers and email addresses, so sent
  messages and answers would be recorded as page text. If installed, use Strict
  mode or mask the transcript element (`data-clarity-mask="true"`) to record
  behavior only. Installing it means editing the pinned chat page and
  `privacy.txt` (both release-manifest inputs); deployed dev sends no CSP.
- **Consent** covers OpenAI, development traces, the form provider, Clarity if
  installed, and keeping copies of conversations privately beyond the 7-day
  trace retention.
- **Pilot** the whole form once yourself.

## Participants

Two people who differ: one daily toll commuter (knows "the 267" and exit
numbers) and one occasional driver, ideally in different age bands and not both
technical. Agent success differed by age and dialect in the τ-bench study.

## Session: about 30 minutes asynchronous, then a 10-minute call

The form (Google Forms sections or Tally) runs the session in place of a
moderator. Participants use their own device and paste each conversation into
the form.

| Minutes | Block | Detail |
| --- | --- | --- |
| 0–2 | Setup | Consent, participant code, device, roads they drive |
| 2–7 | **A: own trip** | No card: "Ask about a toll trip you make or might make." |
| 7–12 | Questions, then wait | Post-task questions; start the next task at least 5 minutes after the last message |
| 12–18 | **B: annual budget, facts missing** | Card below; tests unprompted detail and "not sure" answers |
| 18–23 | Questions, then wait | As above |
| 23–29 | **C: ambiguous place, then a follow-up** | Card below; tests direction inference and a later request |
| 29–31 | Questions and wrap-up | Overall trust, anything broken |
| +10 | **Transcript walkthrough call**, within a day | Review the pasted chats together: "What were you thinking here?" Focus on withheld facts, ignored questions and stopping points. This replaces think-aloud and catches card misreads. |

Both participants get the same cards; give one B then C and the other C then B.

**Every task:**

- Before: "What do you expect to find out?"
- Instruction: "Start a new chat. Stop when you have your answer, or when you
  would give up in real life. If TollChat says it is unavailable, wait
  5 minutes and reload the page."
- After: paste the conversation; got what you needed (yes / partly / no);
  trust 1–5; what you would ask next; anything confusing.

## Task cards

Card rules:

- Show places as map pins or landmarks, never catalog names or a sample prompt.
- Use a synthetic salary band; never collect real income.
- Do not prescribe tone or style.
- Leave some facts undecided so the participant must answer, guess or say so.
- Keep B and C completable within 5 user turns. The app allows 20, but cases
  use `actor.max_turns = 5`; a longer human conversation still shows behavior
  but cannot become a reference under the current contract.

Draft cards. Both routes use catalog points, and neither route pair appears in
the active training or shadow fixtures; the host operator checks holdout pairs
with `eval.corpus validate --holdout`.

- **B (Dulles Toll Road, fixed schedule):** You are moving near the
  Wiehle–Reston East Metro station, and your office is near the Spring Hill
  Metro station in Tysons. Salary band $85–95k. You would drive in most
  weekdays; you have not decided about Fridays. Find out whether the tolls
  would be affordable. The office landmark sits between Exit 16 (Route 7) and
  Exit 17 (Spring Hill Rd); either is a reasonable resolution.
- **C (I-495 Express Lanes, dynamic):** You have a meeting at an office off
  Jones Branch Drive in Tysons, driving from near Braddock Road in Annandale.
  Find out what the toll is right now. The catalog has five Jones Branch Drive
  points; the trip implies northbound. *Next form section, shown after the
  answer:* "Ask what the drive back would cost right now."

Task A may fall outside coverage; the catalog has I-66 only inside the
Beltway, for example. An unsupported-route answer is still useful data.

## Simulator comparison

- Running the actor on a card requires the card to be a case. Training (50) and
  shadow (10) have fixed workflow and coverage counts, so each card replaces an
  existing case of the same kind and family in a new corpus version.
- The actor writes replies only; the opening is the authored case prompt. Compare
  humans with the actor from the second user turn on. Human openings are
  compared with author wording instead.
- Run the golden actor for 3 trials per card to see its spread. Three trials
  need Ryan's explicit instruction and an authorized budget.
- `golden_actor_check.py` is a whole-split validity check, not a human
  comparison: it replays the first passing reference for every case and lets
  the actor write every turn after the opening. Use it to confirm the new cases
  are actor-valid.
- Do not use `simulated.py`. Its live actor is a different profile (3 turns,
  "brief, practical") and answers a different question.

Comparison sheet, one per card (P1, P2, actor trials 1–3), rows from the
Sim2Real behavior dimensions:

| Dimension | Record | Research expects the actor to be |
| --- | --- | --- |
| Communication style | Length, politeness, typos, **place-name wording** | More polite, more uniform |
| Information pattern | Facts volunteered beyond what was asked, after the opening | Volunteers more |
| Clarification behavior | Full, partial, "not sure" or ignored | Never unsure |
| Error reaction | Pushes back, corrects, or moves on quietly | Changes course quietly |
| Ending | Who stopped and why (answered, gave up, cap) | Rarely quits |
| Rating | Participant success and trust vs. the Outcome judge | More positive |

**Decision rule:**

- Both participants differ from all three actor trials in the same direction:
  record a candidate actor gap in the journal and test it in the 5–8 person
  study.
- One participant differs, or they split: note it; no action.
- The walkthrough shows a misread card: label that conversation actor-invalid
  and rewrite the card before a larger study.

## Using the conversations in evals

By default the human conversations stay private. AGENTS.md keeps transcripts
out of commits unless Ryan explicitly approves publishing them.

Without publishing participant words:

1. **Failures become small synthetic regressions.** Note the first failure in
   each conversation; write a minimal synthetic case for each failure mode.
2. **Real wording becomes paraphrased variants** in authored cases, especially
   place names for endpoint resolution.
3. **Findings feed the actor-gap list** from the comparison sheet.

With Ryan's approval and participant consent, an accepted conversation can
become a real-user reference. The corpus code requires:

- One case per conversation, because each participant's calls differ.
- A case `prompt` equal to the verbatim opening; a paraphrase fails the
  `initial_prompt` check.
- Fixtures built from the trace's tool results, with every `evaluated_at` equal
  to the case `frozen_time`. Normalize call times and say so in the provenance;
  annual fixtures also need the unrounded synthetic distance.
- A passing reference for every case; a failed conversation becomes a negative
  reference beside an authored passing one.
- A swap into the fixed split counts and a new corpus version.
- A separately authorized combined calibration before the judges see these
  references; a new corpus version does not trigger one.

Holdout is not an option: these cards are public in this plan.

## Data handling

- Form exports, traces, transcripts and comparison sheets stay in ignored
  `v2/eval/private/`.
- Results get a short entry on that week's [journal](EXPERIMENT_JOURNAL.md) page.

## Out of scope

- Actor profile or prompt changes.
- Success rates or statistical claims.
- A turn-by-turn human–actor replay tool.
- Attention checks; they guard against low-effort crowd workers, not two
  recruited participants.
