---
name: editorial-review
description: Editorial review for AI Thinking Lab pages and LinkedIn posts. Use before publishing any page, experiment write-up or post, or when asked to "review", "edit", "make it clearer", "check for gaps" or "make it shorter". Runs reviewer personas, a gap hunt, a common-sense pass and a veteran-editor read, then fixes what they find.
---

# Editorial review: AI Thinking Lab

Every rule here came from a real problem someone found on this site. Run the whole process before anything is published. Work with `ai-thinking-lab-style` (design and evidence rules); this skill is about what the words say and whether a first-time reader gets it.

## 1. The process (in this order)

1. **Read it all yourself, in the browser.** Not the HTML, the rendered page, top to bottom. Count visible words (skip collapsed sections, code, SVG) and check the read-time claim at about 230 words per minute.
2. **Reviewer personas, in parallel** (agents if available). Give each the rendered screenshots and the files, ask for quoted problems and concrete fixes, under ~400 words:
   - **Non-technical reader** (a nurse, a teacher). "After 20 seconds, what is this? What confused you?"
   - **Recruiter** screening on a phone in 30 seconds. "Would you click? What hurts credibility?"
   - **Engineer who checks claims** against the code, the results and the cited paper. "What's wrong, overstated, or not what was tested?"
   - **AI-writing detector.** "Which lines sound machine-written? Quote them with a human rewrite."
3. **Gap hunt** (one agent, read-only). Look for anything that doesn't match (a) how real systems usually work, (b) what the code and results actually show, (c) other parts of the site.
4. **Common-sense pass.** A first-time visitor: what makes them go "huh?" Labels that mean nothing, things in the wrong order, repetition, small grey text, no way back.
5. **Veteran-editor read.** Every word. Subheading, read time, pronouns, verbs, defined terms, sentence length.
6. **Fix, rebuild, re-run the site checker, look again.** Send the harshest reviewer the new version once ("second pass") and fix what's left.
7. Write down any new lesson in this file.

## 2. Accuracy beats everything

- **The example must match what the code does.** Read the mechanism first. Experiment 001's code takes a permission away (a yes/no flag goes to no); it never creates a duplicate. So the story is "a manager cancels an approved credit", not "a credit given twice".
- **Prefer examples where real systems don't already protect you.** Refunds were dropped because payment providers already block over-refunds and repeat requests; internal tools like store credit often don't.
- **Never claim what wasn't tested** (real concurrency, a real AI model, other databases, memory across conversations). Turn it into an honest open question instead.
- **A count is not a rate.** "1 of 6" when only one situation tests the timing is not "1 in 6 credits go wrong".
- **Every number keeps its condition and denominator:** "1,611 of 9,000, with the cancellation landing within milliseconds, on one laptop, SQLite".
- **Say what the paper studies and what is your own extension.** Never imply the authors were involved.
- **If a situation only fails because a safeguard was removed on purpose, say so.**
- **When a follow-up changes the lesson, update every place the lesson appears** (page, homepage, posts, share cards). Experiment 001: "check again at the moment you act" became "one locked step" after the stress test.

## 3. Words a first-time reader understands

- **No vague action words.** Never "check" on its own: say who does what to which thing. "The agent looks up the customer's record to see whether the credit is still approved." "The final lookup and the save happen as one locked database step." ("Check" is fine for "I check the results".)
- **No unclear "it".** "Still let it through" → "still let the wrong credit through".
- **One name per thing, everywhere.** Experiment 001: approach (never way or method), look up, save, approved, wrong credit.
- **Define a term before using it.** "At a glance" must make sense on its own; no "Part 2", "locked step" or approach names it hasn't explained.
- **Lead with what was found, not the process.** Then what didn't work, as plainly.
- **Lessons are concrete, in three moves:** what goes wrong, what fixes it, an everyday comparison ("like a shop confirming your coupon at the till, not at the door").
- **Lead with the topic the reader came for.** Experiment 001 is about memory, so lesson 1 is "An AI agent's memory is a hint, not the truth."
- **No machine cadence:** no slogans or aphorisms, no "X, not Y" constructions, no rhetorical triples, no filler openers, no asides like "Good.", no lettered section labels.

## 4. Structure and length

- **The homepage is about the habit**, not one experiment. Experiments go in the log; findings live on their pages.
- **One experiment = one entry.** Follow-ups are Part 2, Part 3 inside it.
- **The subheading is a hook**, never a repeat of "At a glance". Example: "An AI agent looked up the right answer and still made the wrong move."
- **Say each point once in "At a glance" and once in its full section.** Never a third time. One limitations section, one scope line.
- **Tell readers where to look before a big table** ("look at situation 6, the highlighted row"), and highlight it.
- **Explain columns that sound alike** in one line under the table. That line often holds the key insight.
- **List the situations before the results.**
- **Bold lead-ins that act as headlines go on their own line,** in the headline font.
- **Aim for a 5-minute read.** Keep the main points visible; put background, full grids, code, traces and run commands in collapsible sections. Nothing true gets deleted.
- **The read-time claim must be true** (visible words ÷ ~230).
- **End every page with a way back** ("← Back to all experiments").

## 5. LinkedIn posts

- **The hook is the first two lines.** That's all anyone sees before "…see more". Good: "An AI agent looked up the right answer… and still made the wrong move." / "I read a lot about AI. I almost never test any of it."
- **One idea per post.** Short lines, white space, numbers with denominators.
- **Habit post about 100 words; experiment post about 200.**
- **Links go in the first comment**, with "Link in the first comment" in the post. LinkedIn tends to show posts with outside links to fewer people.
- **Attach one image:** a homepage screenshot for the habit post, the comic strip for an experiment post.
- **End with a real question** to invite comments.
- **Keep one line of honesty:** small test, made-up data, no real AI model, which paper inspired it.
- **Every number must match the website.** If one changes, change both.
- **Timing:** Tuesday to Thursday morning. Reply in the first hour; don't edit during it. Run the link through the LinkedIn Post Inspector first.
- **A trusted human reads it before posting** (it was the author's sister here). Ask: do the first two lines make you click? Is anything confusing? Does it sound like me?

## 6. Checklist before publishing

- [ ] Example matches the code; every claim was tested or is an open question
- [ ] Numbers match results files (`python docs/check_site.py` passes) and posts
- [ ] No vague verbs, no unclear "it", one name per thing
- [ ] Subheading hooks; "At a glance" stands alone; no point said three times
- [ ] Read time is true; main points visible; detail collapsible
- [ ] Lessons are concrete and lead with the topic
- [ ] Phone (390px), tablet and desktop, light and dark; no sideways scroll
- [ ] Share cards and post images updated if wording or numbers changed
- [ ] Reviewer personas + gap hunt + editor read done; second pass on the harshest reviewer
