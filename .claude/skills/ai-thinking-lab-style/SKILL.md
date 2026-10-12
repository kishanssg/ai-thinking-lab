---
name: ai-thinking-lab-style
description: Design language, writing rules and evidence rules for the AI Thinking Lab site (docs/). Use whenever adding an experiment, writing or editing any page copy, changing styles, making LinkedIn preview images, or reviewing the site before publishing.
---

# AI Thinking Lab: style and rules

For the review process (personas, gap hunt, editor read, LinkedIn posts), use the `editorial-review` skill too.

AI Thinking Lab is a habit: **read a paper, ask one question, test it, share what happened.** The site documents that habit. Every rule below exists because a reviewer (or the author) caught a real problem. Follow them unless the author says otherwise.

## 1. What the site is

- The **homepage is about the habit**, not about one experiment. It has: the habit headline, the four steps, the log of experiments (one-line findings), "Lessons so far", and About. Results tables live on experiment pages, not the homepage.
- Each **experiment page** is a feature article: headline, deck, byline, "For engineers" one-liner, "At a glance" box, story, the methods, results, a comic strip for the key moment, follow-ups, what I learned, what I don't know yet, what this test is not, try it yourself, footer with citation and AI credit.
- Byline is **kishanssg** unless the author gives a real name.

## 2. Writing rules

**Voice:** plain words a non-engineer understands. Short sentences. First person ("I tested..."). Explain things the way you would to a smart friend.

**Do**
- Lead with the finding, not the process.
- Use everyday words in the main text ("wrong credit", "check while giving"); put technical terms once near the top for engineers ("TOCTOU", "write transaction") and in "For engineers" sections that open on click.
- Say what didn't work, as plainly as what did.
- State the condition behind every number ("within a few milliseconds, on one laptop, SQLite").
- Give every number its denominator ("1 of 6", "1,611 of 9,000").
- Never use a vague action word on its own. Say who does what to which thing: not "check first" but "the agent looks up the customer's record first"; not "the check and the action" but "the final lookup and the save". Experiment 001's words: **look up** (read the record to see if the credit is still approved), **save** (write the credit to the database), **one locked database step** (nothing can change the record between the lookup and the save). "Check" is fine only for checking results or the automatic site check.
- Keep the AI-assistance credit to one line: "Built with help from AI tools (ChatGPT, OpenAI Codex, Claude Code). I choose the questions and check the results."
- Say once, plainly, what kind of test it is: "I tested the safety net around an AI agent, not the AI itself. A simple rule plays the agent."

**Don't**
- Slogans and aphorisms ("A check is a snapshot, not a guarantee"), clever fragment headings, rhetorical triples ("no threads, no sleeps, no timing luck"), "X, not Y" constructions, filler openers ("Agents increasingly..."), asides like "Good."
- Lettered or numbered section kickers (A, B, C...), symmetric card grids, mono micro-labels.
- Repeating the same disclaimer in several places. One limitations section, one scope line.
- Calling a single situation a rate ("1 of 6" when only one situation tests timing).
- Claims the code did not test (concurrency, a real model, other databases).
- Overselling: "proves", "guarantees", "solves". Zero failures is an observation, not proof.

**Common sense for first-time readers**
- One name per thing across the whole site (Experiment 001: "approach", not way/method; "saved"; "approved").
- Never use a term before the page has explained it (At a glance must make sense on its own).
- Say each point once in At a glance and once in its full section. No third repeat.
- Tell readers where to look before a big table or grid ("look at situation 6, the highlighted row").
- Bold lead-ins that act as headlines go on their own line, in the headline font.
- Explain any two columns that sound alike, in one line under the table.
- End every page with a clear way back ("Back to all experiments").

**Examples must match what the code actually does.** Before using a story, check the mechanism in the code:
- Experiment 001 revokes a permission (a yes/no flag goes from yes to no). The story is therefore *a manager cancels an approved $20 store credit just after the agent checks it*, not "given twice".
- Prefer examples where real systems don't already protect you. Refunds were rejected because payment providers already block over-refunds and repeated requests; internal tools like store credit often don't.
- If a situation only fails because the test removed a safeguard on purpose, say so on the page.
- Keep the code's names in the same words as the story (Experiment 001 uses customer / credit / approved). If you rename code, re-run it and confirm the logical results are identical before saving.

**Paper attribution:** say what the paper studies and what is my own extension. Never imply the authors were involved. Don't reproduce text from the paper.

## 3. Design language

**Theme:** a calm newspaper. Comic style only inside the comic strip.

- **Fonts** (in `docs/assets/site.css`):
  - Body and UI: `Calibri, Carlito, "Segoe UI", "Helvetica Neue", Arial, sans-serif`.
  - Headlines, masthead, captions: `"Playfair Display", Georgia, serif`, weight 900, with `font-variant-numeric: lining-nums` (otherwise "1" looks like "I").
  - Speech bubbles only: `"Comic Neue", "Comic Sans MS"`.
  - Monospace only for real code and traces.
  - Fonts load from Google Fonts with local fallbacks; no other external requests.
- **Colours** (CSS variables, light and dark): paper `#f4f0e6`, ink `#161616`, muted `#5c5a55`, rules `#d3ccbc`, accent blue `#1d5592` (good/correct), red `#b3261e` (bad/section labels), amber hatch for "refused a fair one", caption yellow `#ffe066`. Colour never carries meaning alone; every coloured cell also has a text label.
- **Masthead:** three columns (tagline left, "AI Thinking Lab" centre, date right), a 4px double rule under it, small-caps nav.
- **Sections:** serif H2 with a 3px rule above. Thin column rules between side-by-side blocks. Drop cap on the first story paragraph. Boxes ("At a glance", result boxes) use a 2px ink border with a solid offset shadow.
- **Results:** segment squares (one square per task) plus the number; the outcome matrix uses five outcomes: done correctly (blue), said no correctly (outline), stopped at the moment of acting (dashed blue), wrong action (red), refused a fair one (amber hatch).
- **Comic strip:** inline SVG line art (robot agent, person, record clipboard labelled "#42", notes labelled "MEMORY" / "OLD ANSWER", stamps). Captions are "Earlier", "Step 1...", not clock times. Show who causes the change. Speech bubbles are real HTML text with `sr-only` speaker names. Add a caption saying what was simulated ("step 2 is slotted in on purpose; no real AI").
- **Layout:** reading column ~41rem, wide figures ~66rem, 16px+ side gutter. Tables stack into cards below 640px. No horizontal page scroll at 390, 768 or 1440px.
- **No:** gradients, glow, glassmorphism, animation, emojis, decorative charts, fake terminals.

## 4. Evidence rules (non-negotiable)

- Never edit experiment code, fixtures or saved results to make the site look better.
- **One experiment = one folder, one page, one row in the log.** A follow-up to an experiment goes inside it as a part: `experiments/001-memory-reliability/part-2-stress-test/`. The page shows it as "Part 2", never as a separate experiment number.
- Every number shown on a page must come from a results file:
  - Summary metrics: `<span class="metric" data-approach="A" data-metric="invalid_commits" data-value="3/6">` with a visible value and one `<i class="on">` per counted task.
  - Matrix cells: `data-scenario`, `data-approach`, `data-recommended`, `data-committed`, and an outcome class.
  - Traces: `<pre data-trace="scenario/approach">` with the exact recorded events.
  - Part totals: `data-exp="part2" data-approach="E" data-value="1611/9000"` (summed from that part's results file).
- Run `python docs/check_site.py` before every commit. It verifies numbers, segments, cell styles, traces and links, and runs in CI. If you add a new kind of number, extend the checker.
- The Experiment 001 page was generated once from the results files; it is now edited by hand. When editing, keep every data attribute intact and re-run the checker.

## 5. Before publishing (checklist)

1. `python -m unittest discover -s experiments/<folder> -p "test_*.py"` passes for every experiment.
2. `python docs/check_site.py` passes.
3. Preview: `python -m http.server 8000 --directory docs`, check 1440, 768 and 390px, light and dark, no sideways scroll, no console errors.
4. Ask 3 reviewers (or reviewer agents): a non-technical reader, a recruiter, an engineer who checks claims against the code and the paper. Then run one "gap hunt": anything that doesn't match how real systems work, what the code tested, or the rest of the site.
5. LinkedIn cards (`docs/assets/og-*.png`, 1200x630): lead with the habit (homepage) or the strongest honest number with its condition (experiment).
6. Commit on a branch; merge to `main` to publish (GitHub Pages serves `docs/`).

## 6. Adding a new experiment

1. New folder `experiments/00N-name/` with code, tests, fixtures, `results/`, README, methodology, findings, attribution. Later parts go in `part-2-.../` inside it, with their own tests and a CI step.
2. New page `docs/experiments/00N-name/index.html` following the structure in section 1.
3. Add a row to the homepage log (one-line finding) and, if earned, a line to "Lessons so far" citing the experiment numbers.
4. Extend `docs/check_site.py` so the new page's numbers are verified.
5. Run the checklist in section 5.
