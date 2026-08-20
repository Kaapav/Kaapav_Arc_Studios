# Content safety — how AI Creative Explorer protects itself

One bad video can strike or demonetize the entire channel, so safety runs at
**three layers**, and nothing flagged can go public without your explicit sign-off.

## Layer 1 — safe by construction (script writer)

The LLM prompt hard-codes safety rules into every script: family/advertiser-friendly
language, no dangerous instructions, no hate or harassment, no fake medical/financial
claims, no invented statistics, and no passing off AI voices as real people or
impersonating public figures. Cheapest fix is the content that never gets written.

## Layer 2 — automated screening (src/safety.py)

Before render/upload, every script (topic + title + narration) is screened:

- **High-precision rules** aimed at *intent*, not mentions. The channel legitimately
  discusses deepfakes, voice cloning, and scam-detection — mentioning those is fine.
  The rules target instructing/promoting harm: explicit sexual content, self-harm
  encouragement, violence incitement, weapon/drug manufacture how-tos, slur-based
  hate, get-rich scams, and real-person impersonation.
- **Profanity check** (advertiser-friendliness).
- **Your own `custom_blocklist`** in config.yaml (brands, topics you never want).
- **OpenAI moderation model** (when `OPENAI_API_KEY` is set) — a nuanced classifier
  that catches what keywords miss. Free to call, so leave it on.

What happens on a flag is `safety.on_fail`:

| Mode | Behavior |
|------|----------|
| `hold` (default) | Video still renders and uploads **private**, but `review.py` refuses to publish it without `--force`. A false positive costs you 30 seconds, never a good video. |
| `block` | The video is skipped entirely. |

## Layer 3 — you (review.py)

Every video uploads as a **private draft** and enters the review queue. Publishing is
always a human decision:

```
python review.py list           # see drafts + safety verdicts
python review.py approve <id>   # publish one
python review.py approve-safe   # publish all SAFE pending drafts at once
python review.py reject <id>    # decline (stays private forever)
```

Held items tell you exactly which category flagged them. Watch the video, judge for
yourself, then `approve <id> --force` only if it's genuinely fine.

## YouTube's AI disclosure

This pipeline produces realistic synthetic narration, so when you publish, toggle
**"Altered or synthetic content"** in YouTube Studio. It has *zero* effect on reach or
revenue — the penalty is only for not disclosing. The pipeline also appends an
"AI-generated" note to every description (`safety.append_ai_disclosure`) because
honesty with viewers builds the loyal fanbase you're after.

## Honest limits

- Keyword rules are narrow by design; the moderation API adds nuance, but **no filter
  is perfect**. The review step exists because a human eye is the real last line.
- The safety gate checks the *script*, not the stock footage. Pexels media is curated
  and generally safe, but glance at the final video before approving.
- Facts: LLMs can hallucinate. The prompt demands hedging on uncertain claims, but
  spot-check anything surprising before you publish it — wrong info erodes exactly
  the trust a fanbase is built on.
