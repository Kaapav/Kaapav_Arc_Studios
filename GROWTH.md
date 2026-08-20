# Going viral & building a loyal fanbase — AI Creative Explorer

The pipeline now bakes most of this in automatically (via the `brand` and `script`
sections of `config.yaml`). This doc explains *why*, so you can steer it.

## The two jobs of every video

1. **Get discovered (viral):** win the first 3 seconds and hold retention.
2. **Keep them (loyal):** feel like the same recognizable channel every time.

Most creators only do #1 and wonder why nobody subscribes. Doing both is what turns
views into a fanbase.

## Virality — what the pipeline enforces now

- **Hook in 3 seconds.** `script.viral_mode` forces a scroll-stopping opener (bold claim /
  "you're doing X wrong" / open-loop question). This is the single biggest lever on a Short.
- **Tension → payoff.** The script escalates curiosity, then delivers something genuinely
  useful or surprising. No "in this video" throat-clearing.
- **Loop ending.** `script.loop_ending` makes the last line call back to the hook so the
  Short loops seamlessly — re-watches massively boost the algorithm.
- **Tight length.** `target_words: 120` (~45s). Higher % completion > longer video.
- **Burned captions + fast pace.** Already on (`captions: true`, voice `rate: +10%`).
  ~85% of Shorts are watched on mute — captions are non-negotiable.

## Loyalty — what the pipeline enforces now

- **Consistent persona.** `brand.persona` gives every script the same voice and attitude.
  People subscribe to a *character*, not to clips.
- **Recurring series.** `brand.series` frames each video as an episode ("I Tried It So You
  Don't Have To", "AI Tool of the Day"…). Series create appointment-viewing and make your
  catalog feel intentional, not random.
- **Signature sign-off.** `brand.signoff` ends every video the same way — a small ritual
  fans start to expect and repeat in comments.
- **Catchphrase opener.** `brand.catchphrase` gives you a recognizable in-joke.

## What you still do by hand (10 min/day, and it's what makes it work)

1. **Pin a comment** with a question — this seeds the comment section and signals the algorithm.
2. **Reply to the first ~10 comments** in the first hour. Early engagement = distribution.
   This is the #1 thing pure-automation channels skip, and it's why they stay small.
3. **Approve before public.** Skim the script for accuracy and vibe (see MONETIZATION.md).
4. **Ride trends.** When a new AI tool blows up, add it to the TOP of `topics.txt` that day —
   timeliness is free reach. The queue is just a fallback; you can always jump the line.

## Posting rhythm

- **1 excellent Short/day** beats 5 rushed ones. Consistency trains both the algorithm and
  your audience to expect you.
- Post around when your audience is active (check YouTube Studio → Analytics → When your
  viewers are online). Adjust the cron time in `.github/workflows/daily.yml` to match.
- Every ~7–10 Shorts, publish one longer 3–8 min explainer (`video.format: long`). Long-form
  builds watch-hours (needed for monetization) and deeper fan connection.

## The 30-day starting plan

- **Week 1:** post daily on `private`/`unlisted`, watch your own videos critically, fix voice
  and pacing. Lock your persona and series.
- **Week 2:** go public. Reply to every comment. Note which hooks/series get the most views.
- **Week 3–4:** double down on the top-performing series. Kill formats that flop. Ask your
  audience what to test next — involving them is how casual viewers become fans.

## The metrics that actually matter (in YouTube Studio)

- **Retention / average % viewed** — the master metric for Shorts. Aim to keep the graph high
  and flat; fix wherever it dips (usually a weak hook or a slow middle).
- **Returning viewers** — the real measure of a fanbase forming.
- **Subscribers per video** — is each video converting watchers into fans?
- Ignore vanity view counts in isolation; retention + returning viewers predict the channel's future.
