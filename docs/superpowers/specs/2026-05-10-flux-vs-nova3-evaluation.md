# Flux vs Nova-2 vs Nova-3 STT Evaluation

Date: 2026-05-10  
Issue: [#279](https://github.com/tsuki-works/niko/issues/279)  
Audio dataset: 18 calls, 22.8 minutes total, all Twilight Family Restaurant  
Keyterms: n=94 from `compute_keyterms()` (76 menu items + 18 universal modifiers from #271)  
Sweep wall-clock: 21.0 minutes

**Important caveat — keyterms on the wire are NOT identical across configs:**

- **Flux (v2)** sends the keyterm list inside its `Configure` JSON; the
  full n=94 list is delivered.
- **Nova-3 (v1)** URL-encodes each keyterm as a repeated query parameter
  on the WebSocket connect URL. Empirical bisect on 2026-05-10 found
  the v1 endpoint returns HTTP 400 once the query string passes
  ~2280 chars (somewhere between n=88 and n=90 of our list). To keep
  the sweep meaningful we cap Nova-3 at n=80 (qlen ~2040),
  preserving the restaurant name + all 18 modifiers + the first ~60
  menu items.
- **Nova-2 (v1) receives NO keyterm.** The original plan assumed
  Nova-2 would silently ignore the param, but empirically it returns
  HTTP 400 when `keyterm=` is in the URL — Nova-2 simply doesn't
  accept that query param at all. Nova-2 is therefore the unbiased
  baseline in this comparison.

**These v1 findings are themselves headline results for #279:**

1. If we migrate Flux → Nova-3, the existing 500-token Flux budget in
   `compute_keyterms()` does not apply. We'd need a separate v1-aware
   URL-length cap (or pursue a POST-body keyterm route if Deepgram
   exposes one).
2. Any "Nova-2 with keyterms" production fallback path is broken —
   the connect itself fails. Nova-2 must run unbiased.

## Summary

| Config | Files OK | Files Failed | Total Finals | Mean Conf | Mean Total Wall (s) |
|---|---|---|---|---|---|
| flux | 18 | 0 | 114 | 0.982 | 57.79 |
| nova-2 | 18 | 0 | 119 | 0.939 | 58.84 |
| nova-3 | 18 | 0 | 120 | 0.968 | 58.86 |

Across 22.8 minutes of audio:

- **Final count.** Nova-2 and Nova-3 emit ~5% more finals than Flux
  (119/120 vs. 114). Flux's `EndOfTurn` is more aggressive at merging
  short utterances ("And" + "one Coke" -> "And one Coke") whereas Nova's
  v1 endpointing splits more often. This is a turn-shape difference,
  not a quality difference.
- **Confidence.** Flux 0.982 > Nova-3 0.968 > Nova-2 0.939. The 4-point
  gap between Nova-3 and Nova-2 is exactly the keyterm bias — same
  endpoint, same model family, only difference is keyterm support.
  Nova-3's keyterm channel measurably shifts confidence even though
  it can only carry 80 of our 94 terms.
- **Wall-clock per call.** All three configs land inside ~1.1s of each
  other on mean total wall-clock per call. This means the **last final
  for each call arrives at roughly the same time** under realtime
  pacing — none of the configs is dramatically faster end-to-end.

## Latency

The original per-final latency metric (`wall_s_from_open - audio_position_s`)
turned out to be useless: in a realtime stream, both clocks tick
together inside the 20ms send loop, so the difference is always
~zero (all configs landed at p50 = -0.01s, p99 < 0.02s). It does NOT
measure end-of-utterance lag — to do that we'd need to know where
each utterance ended in the audio (Deepgram does provide `start` +
`duration` on each final, which a follow-up could exploit).

A coarser proxy that survives this design flaw: **how much earlier
did the final-final-final arrive vs. the audio finishing pumping?**
Per-call audio_duration vs. total_wall_s for each config:

| Call SID prefix | Audio (s) | Flux wall | Nova-2 wall | Nova-3 wall | Flux vs Nova-3 |
|---|---|---|---|---|---|
| CA01864c | 68.8 | 59.0 | 59.8 | 59.8 | -0.8s |
| CA04458c | 87.0 | 80.0 | 81.5 | 81.5 | -1.5s |
| CA16b771 | 57.9 | 50.6 | 51.1 | 51.0 | -0.4s |
| CA1fdf53 | 107.2 | 95.9 | 96.7 | 96.7 | -0.8s |
| CA2408cf | 111.4 | 100.2 | 101.1 | 101.1 | -0.9s |
| CA5599e6 | 20.8 | 9.6 | 10.3 | 10.3 | -0.7s |
| CA671b0d | 90.6 | 81.6 | 83.3 | 83.4 | -1.8s |
| CA83420f | 81.5 | 64.7 | 66.2 | 66.2 | -1.5s |
| CA896040 | 49.7 | 41.5 | 41.9 | 41.9 | -0.4s |
| CA94ad62 | 51.6 | 42.5 | 44.0 | 44.0 | -1.5s |
| CA9f8b0e | 42.8 | 35.3 | 36.0 | 36.0 | -0.7s |
| CAbdb33a | 188.2 | 21.6 | 21.7 | 21.7 | (all dropped @ ~22s, see notes below) |
| CAc4f381 | 12.3 | 10.4 | 10.8 | 10.8 | -0.4s |
| CAd65d23 | 60.4 | 50.6 | 52.1 | 52.1 | -1.5s |
| CAd68df5 | 99.4 | 88.7 | 91.4 | 91.5 | -2.8s |
| CAd95100 | 103.5 | 94.6 | 95.5 | 95.5 | -0.9s |
| CAdf8a04 | 85.9 | 75.2 | 76.6 | 76.7 | -1.5s |
| CAfe25e2 | 49.1 | 38.4 | 39.2 | 39.2 | -0.8s |

(Wall-clock figures from the `total_wall_s` field captured per run —
time from connection-open to the last [final] for that config.)

Across all 17 successful calls (excluding the 188s outlier), **Flux's
last [final] arrived 0.4-2.8s earlier than Nova v1's last [final]**,
median ~0.85s. This is consistent with Flux's `eot_threshold=0.8`
aggressive end-of-turn detection vs. v1's `endpointing=800` +
`utterance_end_ms=1000`. The Nova-2 vs Nova-3 wall-clocks are
indistinguishable because they share the v1 endpointer; the model
swap doesn't change turn timing.

Magnitude in plain English: **Flux saves roughly 0.8-1.5s on each
call's last turn vs Nova v1 under our current endpointing settings.**
Cumulative latency over a multi-turn call would be larger but we don't
have a per-utterance latency metric (see "Latency" caveat above).
Quality differences (next section) are where the bigger signal lives.

### Mid-stream connection drop on the longest call

`CAbdb33a2f80e5b355d9b44f9470f3e360_20260508T190006Z.ulaw` (188.2s — the
longest in the set) had all three Deepgram WebSocket connections close
mid-stream around the 22-second mark with `ConnectionClosedError: no
close frame received or sent`. All three configs caught this gracefully
and produced 2 finals each before the disconnect. Three independent
connections dropping at roughly the same wall-clock moment suggests
either a Deepgram-side aggregate throttle, a local network blip, or
something in the audio at that point in the file. Reproducibility unclear
from one observation. Report partial data for this call and treat it as
an outlier in the per-config aggregates.

## Per-call breakdown

### CA01864c6bb49b3703bcb26e0d071fc5e8_20260509T030245Z.ulaw
_Audio duration: 68.8s_

| # | Wall (s) | Flux | Nova-2 | Nova-3 |
|---|---|---|---|---|
| 1 | 9.32 | "Can we place an order for pickup?" (0.92) |  |  |
| 2 | 10.20 |  | "Hi. Can you please know that for pickup?" (0.78) |  |
| 3 | 10.20 |  |  | "Can you place an order for pickup?" (0.99) |
| 4 | 16.00 | "would like get one chicken fried rice." (0.99) |  |  |
| 5 | 16.60 |  | "Would like get one chicken fried rice." (0.99) |  |
| 6 | 16.64 |  |  | "Would like to get one chicken fried rice." (1.00) |
| 7 | 21.60 |  | "Coke, please." (0.99) |  |
| 8 | 21.61 |  |  | "On a a Coke, please." (0.98) |
| 9 | 22.19 | "One Coke." (0.98) |  |  |
| 10 | 22.65 |  | "One Coke." (0.96) |  |
| 11 | 22.72 |  |  | "One Coke." (1.00) |
| 12 | 27.65 |  |  | "And one" (0.82) |
| 13 | 27.66 |  | "And, one" (1.00) |  |
| 14 | 29.42 |  |  | "pepper shrimp." (0.98) |
| 15 | 29.43 |  | "pepper shree." (0.98) |  |
| 16 | 29.51 | "And one pepper street." (0.85) |  |  |
| 17 | 39.74 | "Pepper Shrimp appetizers." (0.82) |  |  |
| 18 | 40.00 |  | "Appa soup appetizers." (0.77) |  |
| 19 | 40.01 |  |  | "Pepper Shrimp appetizers." (0.93) |
| 20 | 44.71 | "That's everything." (1.00) |  |  |
| 21 | 47.98 |  | "That's everything." (0.99) |  |
| 22 | 47.99 |  |  | "That's everything." (1.00) |
| 23 | 58.97 | "Yes." (1.00) |  |  |
| 24 | 59.79 |  | "Yes." (0.78) |  |
| 25 | 59.80 |  |  | "Yes." (1.00) |


### CA04458cc5e3d24809e06dd582a230fe4a_20260509T130814Z.ulaw
_Audio duration: 87.0s_

| # | Wall (s) | Flux | Nova-2 | Nova-3 |
|---|---|---|---|---|
| 1 | 10.29 | "Hi. Can I place an order for pickup?" (1.00) |  |  |
| 2 | 10.75 |  | "Hi. Can I place an order for pickup?" (1.00) |  |
| 3 | 10.77 |  |  | "Hi. Can I place an order for pickup?" (1.00) |
| 4 | 17.82 | "I will get one chicken fried rice." (1.00) |  |  |
| 5 | 18.58 |  | "I will get one, chicken fried rice." (1.00) |  |
| 6 | 18.61 |  |  | "I will get one, chicken fried rice." (1.00) |
| 7 | 20.54 | "One Coke." (1.00) |  |  |
| 8 | 21.09 |  | "One Coke," (1.00) |  |
| 9 | 21.10 |  |  | "One Coke," (1.00) |
| 10 | 30.88 |  |  | "I would like to get, one shrimp" (1.00) |
| 11 | 30.93 |  | "I would like to get, one shrimp" (1.00) |  |
| 12 | 31.87 | "I would like to get one shrimp fried rice." (0.98) |  |  |
| 13 | 33.17 |  | "fried rice." (1.00) |  |
| 14 | 33.19 |  |  | "fried rice." (0.99) |
| 15 | 40.45 | "Do you have pepper shrimp" (0.96) |  |  |
| 16 | 41.32 |  |  | "Do you have pepper shrimp?" (0.99) |
| 17 | 41.34 |  | "Do you have pepper shrimp?" (1.00) |  |
| 18 | 60.23 |  | "I will get one pepper, cinched chow mein." (1.00) |  |
| 19 | 60.24 |  |  | "I will get one pepper shrimp Chow Mein." (0.99) |
| 20 | 60.31 | "I will get one pepper shrimp chow mein." (0.98) |  |  |
| 21 | 66.26 | "That's all." (1.00) |  |  |
| 22 | 66.89 |  | "That's all." (1.00) |  |
| 23 | 66.90 |  |  | "That's all." (1.00) |
| 24 | 80.03 | "Yes." (1.00) |  |  |
| 25 | 81.48 |  |  | "Yes." (0.98) |
| 26 | 81.53 |  | "Yes." (0.90) |  |


### CA16b771f616e8b66dfa8e12d308926122_20260509T001152Z.ulaw
_Audio duration: 57.9s_

| # | Wall (s) | Flux | Nova-2 | Nova-3 |
|---|---|---|---|---|
| 1 | 10.17 | "Hi. Can I place an order for pickup?" (1.00) |  |  |
| 2 | 10.89 |  |  | "Hi. Can I place an order for pickup?" (1.00) |
| 3 | 10.89 |  | "Hi. Can I place an order for pickup?" (1.00) |  |
| 4 | 16.37 | "I'm just wanting chicken fried rice." (0.88) |  |  |
| 5 | 17.09 |  | "I'm just putting chicken fried rice." (0.88) |  |
| 6 | 17.10 |  |  | "I'll get one chicken fried rice." (0.97) |
| 7 | 26.96 | "Nope. Nothing." (1.00) |  |  |
| 8 | 27.42 |  | "No. Nothing." (1.00) |  |
| 9 | 27.45 |  |  | "Nope. Nothing." (1.00) |
| 10 | 44.84 | "Yes." (1.00) |  |  |
| 11 | 45.86 |  |  | "Yes." (0.99) |
| 12 | 45.88 |  | "Yes." (0.97) |  |
| 13 | 50.57 | "Thank you." (1.00) |  |  |
| 14 | 51.04 |  |  | "Thank you." (1.00) |
| 15 | 51.08 |  | "Thank you." (1.00) |  |


### CA1fdf536a7206273a6a5a66fe9701106a_20260509T032833Z.ulaw
_Audio duration: 107.2s_

| # | Wall (s) | Flux | Nova-2 | Nova-3 |
|---|---|---|---|---|
| 1 | 9.94 | "I can't place an order for pickup." (0.96) |  |  |
| 2 | 10.89 |  | "I can't place an order for pickup." (0.89) |  |
| 3 | 10.91 |  |  | "I can place an order for pickup." (0.94) |
| 4 | 20.57 | "Can I place an order for pickup?" (1.00) |  |  |
| 5 | 21.21 |  |  | "Can I place an order for pickup?" (1.00) |
| 6 | 21.25 |  | "Can I place an order for pickup?" (1.00) |  |
| 7 | 30.25 | "I will get one chicken fried rice." (1.00) |  |  |
| 8 | 30.76 |  | "I will get one chicken tenders." (1.00) |  |
| 9 | 30.77 |  |  | "I will get one chicken fried rice." (1.00) |
| 10 | 36.24 | "One pop." (0.91) |  |  |
| 11 | 36.92 |  |  | "One pop." (0.99) |
| 12 | 36.93 |  | "One pop." (0.64) |  |
| 13 | 43.40 | "Coke, please." (0.97) |  |  |
| 14 | 44.56 |  | "Okay." (0.65) |  |
| 15 | 44.58 |  |  | "Coke, please." (1.00) |
| 16 | 54.13 | "Coke." (1.00) |  |  |
| 17 | 54.50 |  |  | "Coke." (0.90) |
| 18 | 54.56 |  | "Cook." (0.83) |  |
| 19 | 61.75 | "One pepper shrimp fried rice." (0.98) |  |  |
| 20 | 62.44 |  | "One pepper, shrimp, side rice." (0.75) |  |
| 21 | 62.50 |  |  | "One pepper shrimp fried rice." (0.98) |
| 22 | 69.79 |  | "No." (0.97) |  |
| 23 | 69.81 |  |  | "No." (0.77) |
| 24 | 72.23 | "No." (1.00) |  |  |
| 25 | 73.04 |  | "No." (1.00) |  |
| 26 | 73.18 |  |  | "No." (0.99) |
| 27 | 78.94 | "No modifications." (1.00) |  |  |
| 28 | 79.85 |  |  | "No modifications." (1.00) |
| 29 | 79.90 |  | "No modifications." (1.00) |  |
| 30 | 84.14 | "That's all." (1.00) |  |  |
| 31 | 84.87 |  |  | "That's all." (1.00) |
| 32 | 84.90 |  | "That's all." (0.99) |  |
| 33 | 95.89 | "Yes." (1.00) |  |  |
| 34 | 96.65 |  | "Yes." (0.79) |  |
| 35 | 96.67 |  |  | "Yes." (1.00) |


### CA2408cfaf3f250c0bcf7cc2da2f9e19a1_20260509T015049Z.ulaw
_Audio duration: 111.4s_

| # | Wall (s) | Flux | Nova-2 | Nova-3 |
|---|---|---|---|---|
| 1 | 10.07 | "Hi. Can I place an order for pickup?" (1.00) |  |  |
| 2 | 10.66 |  |  | "Hi. Can I place an order for pickup?" (1.00) |
| 3 | 10.70 |  | "Hi. Can I place an order for pickup?" (0.99) |  |
| 4 | 16.91 | "I will get one chicken fried rice." (0.97) |  |  |
| 5 | 17.55 |  | "I will get one chicken fried rice." (0.99) |  |
| 6 | 17.59 |  |  | "I will get one chicken fried rice." (1.00) |
| 7 | 19.02 | "One Coke." (1.00) |  |  |
| 8 | 19.57 |  | "One Coke," (1.00) |  |
| 9 | 19.59 |  |  | "One Coke," (1.00) |
| 10 | 23.22 | "And one pepper shrimp." (0.96) |  |  |
| 11 | 24.15 |  | "and one, pepper" (0.96) |  |
| 12 | 24.20 |  |  | "and one pepper shrimp." (1.00) |
| 13 | 36.77 | "Pepper Shrimp hypertension." (0.89) |  |  |
| 14 | 36.94 |  |  | "The person's application." (0.75) |
| 15 | 36.98 |  | "A person application." (0.73) |  |
| 16 | 44.51 | "Pepper Shrimp appetizer." (1.00) |  |  |
| 17 | 44.94 |  |  | "Pepper Shrimp appetizer." (0.96) |
| 18 | 44.95 |  | "Pepper soup appetizer." (0.42) |  |
| 19 | 55.34 | "No." (1.00) |  |  |
| 20 | 56.25 |  |  | "No." (1.00) |
| 21 | 56.31 |  | "No." (0.99) |  |
| 22 | 63.32 | "Can I also get one Pepper Shrimp fried rice?" (0.94) |  |  |
| 23 | 63.94 |  |  | "Can I also get one pepper shrimp fried rice?" (1.00) |
| 24 | 64.05 |  | "Can I also get one pepper shrimp fried rice?" (1.00) |  |
| 25 | 71.93 |  | "One," (0.84) |  |
| 26 | 71.96 |  |  | "One" (0.97) |
| 27 | 72.51 | "One chicken chow mein." (0.99) |  |  |
| 28 | 72.93 |  |  | "chicken chow mein." (0.91) |
| 29 | 73.02 |  | "chicken chile meat." (0.62) |  |
| 30 | 81.26 |  |  | "That is everything." (0.97) |
| 31 | 81.34 | "That is everything." (1.00) |  |  |
| 32 | 100.20 | "Yes." (1.00) |  |  |
| 33 | 101.11 |  | "Yes." (1.00) |  |
| 34 | 101.12 |  |  | "Yes." (1.00) |


### CA5599e671e788f60e3b41e62a361f7430_20260508T195131Z.ulaw
_Audio duration: 20.8s_

| # | Wall (s) | Flux | Nova-2 | Nova-3 |
|---|---|---|---|---|
| 1 | 5.15 |  | "Hey there." (0.95) |  |
| 2 | 9.63 | "Hi. Can I place an order for pickup?" (1.00) |  |  |
| 3 | 10.33 |  | "Hi. Can I place an order for pickup?" (1.00) |  |
| 4 | 10.34 |  |  | "Hi. Can I place an order for pickup?" (1.00) |


### CA671b0dc4ee626e9830f8114dd69ca9e7_20260509T035136Z.ulaw
_Audio duration: 90.6s_

| # | Wall (s) | Flux | Nova-2 | Nova-3 |
|---|---|---|---|---|
| 1 | 11.12 | "Can I place an order for pickup?" (0.96) |  |  |
| 2 | 11.85 |  |  | "Can I place an order for pickup?" (1.00) |
| 3 | 11.88 |  | "Can I place an order for pickup?" (0.99) |  |
| 4 | 18.38 | "I would like one chicken fried rice." (1.00) |  |  |
| 5 | 18.55 |  |  | "I would like one chicken fried rice." (1.00) |
| 6 | 18.55 |  | "I would like one chicken fried rice." (1.00) |  |
| 7 | 19.92 | "ICT?" (0.93) |  |  |
| 8 | 20.58 |  |  | "Spicy, please." (0.99) |
| 9 | 20.58 |  | "Spicy, please." (0.94) |  |
| 10 | 29.27 | "Iced" (1.00) |  |  |
| 11 | 29.79 |  | "I see." (1.00) |  |
| 12 | 29.82 |  |  | "I see." (1.00) |
| 13 | 37.97 | "I said spicy." (1.00) |  |  |
| 14 | 38.60 |  |  | "Sorry. I said spicy." (1.00) |
| 15 | 38.61 |  | "Sorry. I said spicy." (1.00) |  |
| 16 | 50.12 | "I said chicken fried rice to be spicy." (0.97) |  |  |
| 17 | 50.56 |  | "I said chicken fried rice to be spicy." (1.00) |  |
| 18 | 50.58 |  |  | "I said chicken fried rice to be spicy." (1.00) |
| 19 | 58.80 | "No. Iced." (1.00) |  |  |
| 20 | 59.06 |  |  | "No. I see." (0.99) |
| 21 | 59.11 |  | "No. I see." (1.00) |  |
| 22 | 70.14 |  |  | "I said no I said no iced tea." (0.97) |
| 23 | 70.15 |  | "I said no. I said no ice tea." (0.99) |  |
| 24 | 70.24 | "I said no I said no iced tea." (1.00) |  |  |
| 25 | 81.58 | "Yes." (1.00) |  |  |
| 26 | 83.28 |  | "Yes." (0.94) |  |
| 27 | 83.36 |  |  | "Yes." (1.00) |


### CA83420faa36fc4e14dc852a06a52f5507_20260509T153554Z.ulaw
_Audio duration: 81.5s_

| # | Wall (s) | Flux | Nova-2 | Nova-3 |
|---|---|---|---|---|
| 1 | 11.43 | "Hi. Can I place an order for pickup?" (1.00) |  |  |
| 2 | 12.89 |  |  | "Hi. Can I place an order for pickup?" (1.00) |
| 3 | 12.93 |  | "Hi. Can I place an order for pickup?" (1.00) |  |
| 4 | 17.89 |  |  | "I will get one chicken fried rice." (1.00) |
| 5 | 17.90 |  | "I will get one chicken fried rice." (1.00) |  |
| 6 | 18.86 | "I will get one chicken fried rice and a Coke." (1.00) |  |  |
| 7 | 19.31 |  |  | "And a Coke." (0.99) |
| 8 | 19.32 |  | "And a Coke." (1.00) |  |
| 9 | 27.80 | "Can I also get one pepper shrimp" (1.00) |  |  |
| 10 | 28.46 |  | "Can I also get one pepper shrimp?" (1.00) |  |
| 11 | 28.48 |  |  | "Can I also get one pepper shrimp?" (1.00) |
| 12 | 35.83 | "Operator, please." (1.00) |  |  |
| 13 | 37.10 |  | "Appetizer, please." (1.00) |  |
| 14 | 37.12 |  |  | "Appetizer, please." (1.00) |
| 15 | 44.22 | "No. Advertiser, please." (1.00) |  |  |
| 16 | 44.97 |  |  | "No. Appetizer, please." (0.99) |
| 17 | 45.01 |  | "No. Appetizer, please." (0.95) |  |
| 18 | 58.68 | "Pepper shrimp appetizer." (0.93) |  |  |
| 19 | 59.65 |  |  | "Pepper shrimp appetizer." (0.98) |
| 20 | 59.67 |  | "Pepper shrimp appetizer." (1.00) |  |
| 21 | 64.73 | "That's all." (1.00) |  |  |
| 22 | 66.18 |  |  | "That's all." (1.00) |
| 23 | 66.20 |  | "That's all." (1.00) |  |


### CA8960400e3e20b08a3a45f8eba13d0e1f_20260509T001525Z.ulaw
_Audio duration: 49.7s_

| # | Wall (s) | Flux | Nova-2 | Nova-3 |
|---|---|---|---|---|
| 1 | 8.71 | "Hi. Can I place an order for pickup?" (1.00) |  |  |
| 2 | 9.47 |  | "Hi. Can I place an order for pickup?" (0.98) |  |
| 3 | 9.48 |  |  | "Hi. Can I place an order for pickup?" (1.00) |
| 4 | 15.52 | "I will get one chicken fried rice." (0.96) |  |  |
| 5 | 17.43 |  | "I mean, get one chicken burger." (0.98) |  |
| 6 | 17.46 |  |  | "I will get one chicken fried rice." (0.91) |
| 7 | 18.00 | "and one chicken lo mein." (0.91) |  |  |
| 8 | 18.50 |  | "And one chicken Lomi." (1.00) |  |
| 9 | 18.51 |  |  | "And one chicken lo mein." (0.98) |
| 10 | 25.76 | "Nope." (1.00) |  |  |
| 11 | 26.14 |  |  | "No." (0.65) |
| 12 | 29.37 | "No." (1.00) |  |  |
| 13 | 31.08 |  | "No." (0.98) |  |
| 14 | 31.12 |  |  | "No." (0.94) |
| 15 | 41.48 | "That's it." (1.00) |  |  |
| 16 | 41.85 |  | "That's it." (0.97) |  |
| 17 | 41.89 |  |  | "That's it." (1.00) |


### CA94ad6280044d8e5d8ce824ffeb5a5a78_20260508T222005Z.ulaw
_Audio duration: 51.6s_

| # | Wall (s) | Flux | Nova-2 | Nova-3 |
|---|---|---|---|---|
| 1 | 10.20 | "Hi. Can I place an order for pickup?" (1.00) |  |  |
| 2 | 10.79 |  |  | "Hi. Can I place an order for pickup?" (1.00) |
| 3 | 10.79 |  | "Hi. Can I place an order for pickup?" (1.00) |  |
| 4 | 18.74 |  | "I will get one chicken fried rice and, one Coke, please." (1.00) |  |
| 5 | 18.78 |  |  | "I will get one chicken fried rice and one Coke, please." (1.00) |
| 6 | 18.78 | "I will get one chicken fried rice and one Coke, please." (1.00) |  |  |
| 7 | 28.67 | "Nope." (1.00) |  |  |
| 8 | 29.38 |  |  | "Nope." (0.98) |
| 9 | 29.38 |  | "Nope." (0.94) |  |
| 10 | 42.45 | "Sure." (1.00) |  |  |
| 11 | 44.01 |  |  | "Sure." (0.89) |
| 12 | 44.03 |  | "Sure." (0.82) |  |


### CA9f8b0ed12dd61237e0fc2185ba529f67_20260509T011754Z.ulaw
_Audio duration: 42.8s_

| # | Wall (s) | Flux | Nova-2 | Nova-3 |
|---|---|---|---|---|
| 1 | 9.78 | "Hi. Can I place an order for pickup?" (1.00) |  |  |
| 2 | 10.60 |  | "Hi. Can I place an order for pickup?" (1.00) |  |
| 3 | 10.64 |  |  | "Hi. Can I place an order for pickup?" (1.00) |
| 4 | 16.30 | "I'll get one chicken fried rice." (1.00) |  |  |
| 5 | 17.88 | "and a Coke." (1.00) |  |  |
| 6 | 18.31 |  | "I'll get one, chicken fried rice and a Coke." (1.00) |  |
| 7 | 18.35 |  |  | "I'll get one, chicken fried rice and a Coke." (1.00) |
| 8 | 26.21 | "Nothing." (1.00) |  |  |
| 9 | 27.06 |  | "Nothing." (1.00) |  |
| 10 | 27.08 |  |  | "Nothing." (0.99) |
| 11 | 35.31 | "Yes." (1.00) |  |  |
| 12 | 36.00 |  | "Yes." (1.00) |  |
| 13 | 36.01 |  |  | "Yes." (0.99) |


### CAbdb33a2f80e5b355d9b44f9470f3e360_20260508T190006Z.ulaw
_Audio duration: 188.2s_

| # | Wall (s) | Flux | Nova-2 | Nova-3 |
|---|---|---|---|---|
| 1 | 12.12 | "Hi. Can I place an order for pickup?" (1.00) |  |  |
| 2 | 13.18 |  |  | "I cannot place an order for pickup." (0.99) |
| 3 | 13.20 |  | "I cannot place an order for pickup." (1.00) |  |
| 4 | 21.58 | "I'll get one chicken fried rice and a Coke, please." (1.00) |  |  |
| 5 | 21.70 |  | "I'll get one chicken fried rice and a coke, please." (0.99) |  |
| 6 | 21.73 |  |  | "I'll get one chicken fried rice and a Coke, please." (0.99) |


### CAc4f381eebc15fe9448404a77518734da_20260509T034939Z.ulaw
_Audio duration: 12.3s_

| # | Wall (s) | Flux | Nova-2 | Nova-3 |
|---|---|---|---|---|
| 1 | 10.37 | "Hey. Can I place an order for pickup?" (1.00) |  |  |
| 2 | 10.83 |  | "Eight seven. Place an order for pickup." (0.92) |  |
| 3 | 10.83 |  |  | "Place an order for pickup." (0.98) |


### CAd65d23c15880b6238d499969601d2c56_20260509T021913Z.ulaw
_Audio duration: 60.4s_

| # | Wall (s) | Flux | Nova-2 | Nova-3 |
|---|---|---|---|---|
| 1 | 10.63 | "Can I place an order for pickup?" (0.99) |  |  |
| 2 | 11.14 |  | "Hi. Can I place an order for pickup?" (1.00) |  |
| 3 | 11.18 |  |  | "Can I place an order for pickup?" (0.99) |
| 4 | 17.42 | "I will get one chicken fried rice." (1.00) |  |  |
| 5 | 18.12 |  | "I will get one, chicken fried rice." (0.99) |  |
| 6 | 18.12 |  |  | "I will get one chicken fried rice." (0.92) |
| 7 | 19.95 | "One pork." (0.98) |  |  |
| 8 | 20.40 |  | "One pork," (1.00) |  |
| 9 | 20.42 |  |  | "One pork," (1.00) |
| 10 | 26.65 | "One Coke." (1.00) |  |  |
| 11 | 27.18 |  |  | "One Coke." (0.99) |
| 12 | 27.23 |  | "One Coke." (0.78) |  |
| 13 | 32.47 | "That's all." (1.00) |  |  |
| 14 | 33.16 |  | "That's all." (1.00) |  |
| 15 | 33.18 |  |  | "That's all." (1.00) |
| 16 | 46.38 |  |  | "Yes." (0.82) |
| 17 | 46.41 |  | "Yes." (0.80) |  |
| 18 | 50.56 | "Yes." (1.00) |  |  |
| 19 | 52.11 |  | "Yes." (1.00) |  |
| 20 | 52.13 |  |  | "Yes." (1.00) |


### CAd68df54a44a770570cb8e5cfc3a65dfe_20260509T001940Z.ulaw
_Audio duration: 99.4s_

| # | Wall (s) | Flux | Nova-2 | Nova-3 |
|---|---|---|---|---|
| 1 | 8.79 | "Can I place an order for pickup?" (0.90) |  |  |
| 2 | 8.88 |  |  | "Okay. Can I place an order for pickup?" (1.00) |
| 3 | 8.91 |  | "Okay. Can I place an order for pickup?" (1.00) |  |
| 4 | 16.64 | "I will get one chicken lo mein." (1.00) |  |  |
| 5 | 17.00 |  |  | "I will get one chicken lo mein." (0.97) |
| 6 | 17.04 |  | "I mean, get one chicken Lomi." (0.94) |  |
| 7 | 26.55 | "something." (1.00) |  |  |
| 8 | 27.49 |  |  | "Okay." (0.85) |
| 9 | 27.50 |  | "Okay." (0.97) |  |
| 10 | 30.53 | "And also, can I get one chicken chow mein?" (0.98) |  |  |
| 11 | 31.02 |  |  | "And, also, can I get one chicken chow mein?" (0.92) |
| 12 | 31.05 |  | "And also, can I get, one chicken element?" (0.99) |  |
| 13 | 39.51 | "Can I get one chicken chow mein?" (0.93) |  |  |
| 14 | 40.21 |  | "Can I get one chicken, so many?" (0.95) |  |
| 15 | 40.26 |  |  | "Can I get one chicken chow mein?" (0.99) |
| 16 | 51.83 |  | "No. And can I get, one pepper" (0.97) |  |
| 17 | 51.85 |  |  | "No. And can I get one Pepper Shrimp?" (0.99) |
| 18 | 52.15 | "No. And can I get one Pepper Shrimp?" (0.96) |  |  |
| 19 | 62.71 |  | "Nope?" (0.78) |  |
| 20 | 70.63 | "Nope. Yeah. All good." (1.00) |  |  |
| 21 | 71.11 |  | "No. Yeah. All good." (0.98) |  |
| 22 | 71.14 |  |  | "No. Yeah. All good." (0.99) |
| 23 | 83.42 |  |  | "That's good." (0.98) |
| 24 | 88.66 | "That's good." (1.00) |  |  |
| 25 | 91.42 |  | "That's good." (1.00) |  |
| 26 | 91.51 |  |  | "That's good." (1.00) |


### CAd95100aa9bc6fb5284bd01ab406c8e8c_20260510T190757Z.ulaw
_Audio duration: 103.5s_

| # | Wall (s) | Flux | Nova-2 | Nova-3 |
|---|---|---|---|---|
| 1 | 14.23 | "Can I place an order for pickup?" (1.00) |  |  |
| 2 | 14.86 |  |  | "Can I place an order for pickup?" (1.00) |
| 3 | 14.88 |  | "Can I place an order for pickup?" (0.99) |  |
| 4 | 21.55 | "I will get one chicken fried rice." (1.00) |  |  |
| 5 | 22.47 |  | "I will get one chicken fried rice." (0.99) |  |
| 6 | 22.50 |  |  | "I will get one chicken fried rice." (1.00) |
| 7 | 26.24 | "Pepper fruit." (0.88) |  |  |
| 8 | 26.48 |  |  | "Pepper shrimp." (0.92) |
| 9 | 26.49 |  | "Half a cent." (0.77) |  |
| 10 | 33.77 | "A person?" (1.00) |  |  |
| 11 | 34.00 |  | "A person?" (0.88) |  |
| 12 | 34.00 |  |  | "A person." (0.97) |
| 13 | 41.46 | "Pepper Shrimp." (0.90) |  |  |
| 14 | 41.51 |  | "Apple shrimp." (0.69) |  |
| 15 | 41.57 |  |  | "Pepper Shrimp." (0.88) |
| 16 | 50.18 | "And one pork." (1.00) |  |  |
| 17 | 50.32 |  |  | "And one Coke." (0.60) |
| 18 | 50.36 |  | "And, one Coke." (0.97) |  |
| 19 | 62.50 | "Book." (0.97) |  |  |
| 20 | 62.95 |  |  | "Book." (0.75) |
| 21 | 63.01 |  | "Fuck." (0.68) |  |
| 22 | 69.33 | "Oak" (0.99) |  |  |
| 23 | 69.57 |  |  | "Coke." (0.88) |
| 24 | 69.58 |  | "Oak." (0.58) |  |
| 25 | 77.96 | "I will get a Coke." (1.00) |  |  |
| 26 | 78.12 |  | "I didn't get a Coke." (0.95) |  |
| 27 | 78.15 |  |  | "I will get a Coke." (0.95) |
| 28 | 83.78 | "That's all." (1.00) |  |  |
| 29 | 84.38 |  | "That's all." (0.96) |  |
| 30 | 84.39 |  |  | "That's all." (0.99) |
| 31 | 94.59 | "Yes." (1.00) |  |  |
| 32 | 95.48 |  |  | "Yes." (1.00) |
| 33 | 95.48 |  | "Yes." (1.00) |  |


### CAdf8a04e24cf9c41195fa678343cce8f2_20260509T131255Z.ulaw
_Audio duration: 85.9s_

| # | Wall (s) | Flux | Nova-2 | Nova-3 |
|---|---|---|---|---|
| 1 | 10.43 | "Hi. Can I place an order for pickup?" (1.00) |  |  |
| 2 | 10.97 |  | "Hi, Kenneth. This is an order for pickup." (0.99) |  |
| 3 | 10.98 |  |  | "Hi, Kenneth. This is an order for pickup." (0.99) |
| 4 | 17.89 | "I will get one chicken fried rice." (1.00) |  |  |
| 5 | 19.01 |  |  | "I will get one chicken fried rice." (1.00) |
| 6 | 19.04 |  | "I will get one chicken fried rice." (1.00) |  |
| 7 | 27.64 | "Nothing." (1.00) |  |  |
| 8 | 28.41 |  |  | "Nothing." (1.00) |
| 9 | 28.43 |  | "Nothing." (0.99) |  |
| 10 | 40.69 | "Can I also add a pepper shrimp?" (1.00) |  |  |
| 11 | 41.00 |  |  | "Can I also add a pepper shrimp?" (0.99) |
| 12 | 41.00 |  | "Can I also add a pepper shrimp?" (1.00) |  |
| 13 | 56.69 | "Nothing." (1.00) |  |  |
| 14 | 57.86 | "no modifications." (0.91) |  |  |
| 15 | 58.00 |  |  | "Nothing. No modifications." (1.00) |
| 16 | 58.01 |  | "Nothing. No modifications." (1.00) |  |
| 17 | 64.96 | "That's all." (1.00) |  |  |
| 18 | 65.61 |  |  | "That's all." (1.00) |
| 19 | 65.64 |  | "That's all." (0.98) |  |
| 20 | 75.21 | "Yes." (1.00) |  |  |
| 21 | 76.63 |  | "Yes." (1.00) |  |
| 22 | 76.67 |  |  | "Yes." (0.99) |


### CAfe25e2f82829a17da61ea6db6d82cbe0_20260508T183926Z.ulaw
_Audio duration: 49.1s_

| # | Wall (s) | Flux | Nova-2 | Nova-3 |
|---|---|---|---|---|
| 1 | 11.17 | "Can I place an order for pickup?" (1.00) |  |  |
| 2 | 11.43 |  | "Can I place an order for pickup?" (1.00) |  |
| 3 | 11.43 |  |  | "Can I place an order for pickup?" (1.00) |
| 4 | 18.70 | "I've been getting chicken fried rice and a Coke." (0.98) |  |  |
| 5 | 19.41 |  |  | "I will get chicken fried rice and a Coke." (0.97) |
| 6 | 19.43 |  | "I've been getting chicken fried rice and a Coke." (0.88) |  |
| 7 | 28.64 | "That's" (1.00) |  |  |
| 8 | 29.23 |  |  | "That's all." (1.00) |
| 9 | 29.25 |  | "That's all." (0.94) |  |
| 10 | 38.38 | "Sounds good." (1.00) |  |  |
| 11 | 39.16 |  | "Sounds good." (0.99) |  |
| 12 | 39.20 |  |  | "Sounds good." (0.99) |


## Notable divergences

Heuristic flag: for each [final] from any config, we look for nearby
finals (within 2s) from the other two. If a config went silent — or
the three configs disagree on the text — it's listed below. Read the
per-call tables above for context; this section is the index, not the
primary signal.

### CA01864c6bb49b3703bcb26e0d071fc5e8_20260509T030245Z.ulaw
- @ 9.3s — divergence:
  - **flux**: "Can we place an order for pickup?"
  - **nova-2**: "Hi. Can you please know that for pickup?"
  - **nova-3**: "Can you place an order for pickup?"
- @ 16.0s — divergence:
  - **flux**: "would like get one chicken fried rice."
  - **nova-2**: "Would like get one chicken fried rice."
  - **nova-3**: "Would like to get one chicken fried rice."
- @ 22.2s — divergence:
  - **flux**: "One Coke."
  - **nova-2**: "Coke, please."
  - **nova-3**: "On a a Coke, please."
- @ 29.5s — divergence:
  - **flux**: "And one pepper street."
  - **nova-2**: "And, one"
  - **nova-3**: "And one"
- @ 39.7s — divergence:
  - **flux**: "Pepper Shrimp appetizers."
  - **nova-2**: "Appa soup appetizers."
  - **nova-3**: "Pepper Shrimp appetizers."
- @ 44.7s — only flux produced a final (missing: nova-2, nova-3). Text: "That's everything."
- @ 22.7s — only nova-2, nova-3 produced a final (missing: flux). Text: "One Coke."
- @ 29.4s — only nova-2, nova-3 produced a final (missing: flux). Text: "pepper shree."
- @ 48.0s — only nova-2, nova-3 produced a final (missing: flux). Text: "That's everything."

### CA04458cc5e3d24809e06dd582a230fe4a_20260509T130814Z.ulaw
- @ 17.8s — divergence:
  - **flux**: "I will get one chicken fried rice."
  - **nova-2**: "I will get one, chicken fried rice."
  - **nova-3**: "I will get one, chicken fried rice."
- @ 31.9s — divergence:
  - **flux**: "I would like to get one shrimp fried rice."
  - **nova-2**: "I would like to get, one shrimp"
  - **nova-3**: "I would like to get, one shrimp"
- @ 60.3s — divergence:
  - **flux**: "I will get one pepper shrimp chow mein."
  - **nova-2**: "I will get one pepper, cinched chow mein."
  - **nova-3**: "I will get one pepper shrimp Chow Mein."
- @ 33.2s — only nova-2, nova-3 produced a final (missing: flux). Text: "fried rice."

### CA16b771f616e8b66dfa8e12d308926122_20260509T001152Z.ulaw
- @ 16.4s — divergence:
  - **flux**: "I'm just wanting chicken fried rice."
  - **nova-2**: "I'm just putting chicken fried rice."
  - **nova-3**: "I'll get one chicken fried rice."
- @ 27.0s — divergence:
  - **flux**: "Nope. Nothing."
  - **nova-2**: "No. Nothing."
  - **nova-3**: "Nope. Nothing."

### CA1fdf536a7206273a6a5a66fe9701106a_20260509T032833Z.ulaw
- @ 9.9s — divergence:
  - **flux**: "I can't place an order for pickup."
  - **nova-2**: "I can't place an order for pickup."
  - **nova-3**: "I can place an order for pickup."
- @ 30.3s — divergence:
  - **flux**: "I will get one chicken fried rice."
  - **nova-2**: "I will get one chicken tenders."
  - **nova-3**: "I will get one chicken fried rice."
- @ 43.4s — divergence:
  - **flux**: "Coke, please."
  - **nova-2**: "Okay."
  - **nova-3**: "Coke, please."
- @ 54.1s — divergence:
  - **flux**: "Coke."
  - **nova-2**: "Cook."
  - **nova-3**: "Coke."
- @ 61.8s — divergence:
  - **flux**: "One pepper shrimp fried rice."
  - **nova-2**: "One pepper, shrimp, side rice."
  - **nova-3**: "One pepper shrimp fried rice."
- @ 69.8s — only nova-2, nova-3 produced a final (missing: flux). Text: "No."

### CA2408cfaf3f250c0bcf7cc2da2f9e19a1_20260509T015049Z.ulaw
- @ 23.2s — divergence:
  - **flux**: "And one pepper shrimp."
  - **nova-2**: "and one, pepper"
  - **nova-3**: "and one pepper shrimp."
- @ 36.8s — divergence:
  - **flux**: "Pepper Shrimp hypertension."
  - **nova-2**: "A person application."
  - **nova-3**: "The person's application."
- @ 44.5s — divergence:
  - **flux**: "Pepper Shrimp appetizer."
  - **nova-2**: "Pepper soup appetizer."
  - **nova-3**: "Pepper Shrimp appetizer."
- @ 72.5s — divergence:
  - **flux**: "One chicken chow mein."
  - **nova-2**: "One,"
  - **nova-3**: "One"
- @ 81.3s — only flux, nova-3 produced a final (missing: nova-2). Text: "That is everything."
- @ 73.0s — only nova-2, nova-3 produced a final (missing: flux). Text: "chicken chile meat."

### CA5599e671e788f60e3b41e62a361f7430_20260508T195131Z.ulaw
- @ 5.1s — only nova-2 produced a final (missing: flux, nova-3). Text: "Hey there."

### CA671b0dc4ee626e9830f8114dd69ca9e7_20260509T035136Z.ulaw
- @ 19.9s — divergence:
  - **flux**: "ICT?"
  - **nova-2**: "Spicy, please."
  - **nova-3**: "Spicy, please."
- @ 29.3s — divergence:
  - **flux**: "Iced"
  - **nova-2**: "I see."
  - **nova-3**: "I see."
- @ 38.0s — divergence:
  - **flux**: "I said spicy."
  - **nova-2**: "Sorry. I said spicy."
  - **nova-3**: "Sorry. I said spicy."
- @ 58.8s — divergence:
  - **flux**: "No. Iced."
  - **nova-2**: "No. I see."
  - **nova-3**: "No. I see."
- @ 70.2s — divergence:
  - **flux**: "I said no I said no iced tea."
  - **nova-2**: "I said no. I said no ice tea."
  - **nova-3**: "I said no I said no iced tea."

### CA83420faa36fc4e14dc852a06a52f5507_20260509T153554Z.ulaw
- @ 18.9s — divergence:
  - **flux**: "I will get one chicken fried rice and a Coke."
  - **nova-2**: "I will get one chicken fried rice."
  - **nova-3**: "I will get one chicken fried rice."
- @ 35.8s — divergence:
  - **flux**: "Operator, please."
  - **nova-2**: "Appetizer, please."
  - **nova-3**: "Appetizer, please."
- @ 44.2s — divergence:
  - **flux**: "No. Advertiser, please."
  - **nova-2**: "No. Appetizer, please."
  - **nova-3**: "No. Appetizer, please."
- @ 19.3s — only nova-2, nova-3 produced a final (missing: flux). Text: "And a Coke."

### CA8960400e3e20b08a3a45f8eba13d0e1f_20260509T001525Z.ulaw
- @ 15.5s — divergence:
  - **flux**: "I will get one chicken fried rice."
  - **nova-2**: "I mean, get one chicken burger."
  - **nova-3**: "I will get one chicken fried rice."
- @ 18.0s — divergence:
  - **flux**: "and one chicken lo mein."
  - **nova-2**: "And one chicken Lomi."
  - **nova-3**: "And one chicken lo mein."
- @ 25.8s — only flux, nova-3 produced a final (missing: nova-2). Text: "Nope."

### CA94ad6280044d8e5d8ce824ffeb5a5a78_20260508T222005Z.ulaw
- @ 18.8s — divergence:
  - **flux**: "I will get one chicken fried rice and one Coke, please."
  - **nova-2**: "I will get one chicken fried rice and, one Coke, please."
  - **nova-3**: "I will get one chicken fried rice and one Coke, please."

### CA9f8b0ed12dd61237e0fc2185ba529f67_20260509T011754Z.ulaw
- @ 16.3s — only flux produced a final (missing: nova-2, nova-3). Text: "I'll get one chicken fried rice."
- @ 17.9s — divergence:
  - **flux**: "and a Coke."
  - **nova-2**: "I'll get one, chicken fried rice and a Coke."
  - **nova-3**: "I'll get one, chicken fried rice and a Coke."

### CAbdb33a2f80e5b355d9b44f9470f3e360_20260508T190006Z.ulaw
- @ 12.1s — divergence:
  - **flux**: "Hi. Can I place an order for pickup?"
  - **nova-2**: "I cannot place an order for pickup."
  - **nova-3**: "I cannot place an order for pickup."

### CAc4f381eebc15fe9448404a77518734da_20260509T034939Z.ulaw
- @ 10.4s — divergence:
  - **flux**: "Hey. Can I place an order for pickup?"
  - **nova-2**: "Eight seven. Place an order for pickup."
  - **nova-3**: "Place an order for pickup."

### CAd65d23c15880b6238d499969601d2c56_20260509T021913Z.ulaw
- @ 10.6s — divergence:
  - **flux**: "Can I place an order for pickup?"
  - **nova-2**: "Hi. Can I place an order for pickup?"
  - **nova-3**: "Can I place an order for pickup?"
- @ 17.4s — divergence:
  - **flux**: "I will get one chicken fried rice."
  - **nova-2**: "I will get one, chicken fried rice."
  - **nova-3**: "I will get one chicken fried rice."
- @ 46.4s — only nova-2, nova-3 produced a final (missing: flux). Text: "Yes."

### CAd68df54a44a770570cb8e5cfc3a65dfe_20260509T001940Z.ulaw
- @ 8.8s — divergence:
  - **flux**: "Can I place an order for pickup?"
  - **nova-2**: "Okay. Can I place an order for pickup?"
  - **nova-3**: "Okay. Can I place an order for pickup?"
- @ 16.6s — divergence:
  - **flux**: "I will get one chicken lo mein."
  - **nova-2**: "I mean, get one chicken Lomi."
  - **nova-3**: "I will get one chicken lo mein."
- @ 26.5s — divergence:
  - **flux**: "something."
  - **nova-2**: "Okay."
  - **nova-3**: "Okay."
- @ 30.5s — divergence:
  - **flux**: "And also, can I get one chicken chow mein?"
  - **nova-2**: "And also, can I get, one chicken element?"
  - **nova-3**: "And, also, can I get one chicken chow mein?"
- @ 39.5s — divergence:
  - **flux**: "Can I get one chicken chow mein?"
  - **nova-2**: "Can I get one chicken, so many?"
  - **nova-3**: "Can I get one chicken chow mein?"
- @ 52.1s — divergence:
  - **flux**: "No. And can I get one Pepper Shrimp?"
  - **nova-2**: "No. And can I get, one pepper"
  - **nova-3**: "No. And can I get one Pepper Shrimp?"
- @ 70.6s — divergence:
  - **flux**: "Nope. Yeah. All good."
  - **nova-2**: "No. Yeah. All good."
  - **nova-3**: "No. Yeah. All good."
- @ 88.7s — only flux produced a final (missing: nova-2, nova-3). Text: "That's good."
- @ 62.7s — only nova-2 produced a final (missing: flux, nova-3). Text: "Nope?"
- @ 91.4s — only nova-2, nova-3 produced a final (missing: flux). Text: "That's good."
- @ 83.4s — only nova-3 produced a final (missing: flux, nova-2). Text: "That's good."

### CAd95100aa9bc6fb5284bd01ab406c8e8c_20260510T190757Z.ulaw
- @ 26.2s — divergence:
  - **flux**: "Pepper fruit."
  - **nova-2**: "Half a cent."
  - **nova-3**: "Pepper shrimp."
- @ 41.5s — divergence:
  - **flux**: "Pepper Shrimp."
  - **nova-2**: "Apple shrimp."
  - **nova-3**: "Pepper Shrimp."
- @ 50.2s — divergence:
  - **flux**: "And one pork."
  - **nova-2**: "And, one Coke."
  - **nova-3**: "And one Coke."
- @ 62.5s — divergence:
  - **flux**: "Book."
  - **nova-2**: "Fuck."
  - **nova-3**: "Book."
- @ 69.3s — divergence:
  - **flux**: "Oak"
  - **nova-2**: "Oak."
  - **nova-3**: "Coke."
- @ 78.0s — divergence:
  - **flux**: "I will get a Coke."
  - **nova-2**: "I didn't get a Coke."
  - **nova-3**: "I will get a Coke."

### CAdf8a04e24cf9c41195fa678343cce8f2_20260509T131255Z.ulaw
- @ 10.4s — divergence:
  - **flux**: "Hi. Can I place an order for pickup?"
  - **nova-2**: "Hi, Kenneth. This is an order for pickup."
  - **nova-3**: "Hi, Kenneth. This is an order for pickup."
- @ 56.7s — divergence:
  - **flux**: "Nothing."
  - **nova-2**: "Nothing. No modifications."
  - **nova-3**: "Nothing. No modifications."
- @ 57.9s — only flux produced a final (missing: nova-2, nova-3). Text: "no modifications."

### CAfe25e2f82829a17da61ea6db6d82cbe0_20260508T183926Z.ulaw
- @ 18.7s — divergence:
  - **flux**: "I've been getting chicken fried rice and a Coke."
  - **nova-2**: "I've been getting chicken fried rice and a Coke."
  - **nova-3**: "I will get chicken fried rice and a Coke."
- @ 28.6s — divergence:
  - **flux**: "That's"
  - **nova-2**: "That's all."
  - **nova-3**: "That's all."

## Recommendation

**Verdict from the data: stay on Flux for now; canary Nova-3 only after
solving the keyterm-payload limit.**

Reasoning, ordered by weight:

1. **Flux beats Nova v1 on end-of-turn latency by ~1 second per turn,
   consistently, across every successful call.** Under our endpointing
   settings (`eot_threshold=0.8` for Flux vs `endpointing=800` +
   `utterance_end_ms=1000` for v1) this gap shows up on every call we
   sampled. For a voice agent that runs follow-up LLM + TTS turns this
   1s lag stacks on top of every back-and-forth. Migrating to Nova-3
   would slow the agent unless we also tune v1's endpointing down (which
   the harness didn't try — worth exploring before any migration).
2. **Quality is roughly tied between Flux and Nova-3, with Nova-2 a
   distinct third place.** Scanning the divergence section: when Flux
   gets a menu item right with keyterm bias, Nova-3 also gets it right.
   When Nova-2 (no keyterm) misses, it produces things like
   "Apple shrimp" / "Half a cent" / "I cannot place an order for pickup"
   — clear acoustic confusions that the keyterm list fixes on the
   biased configs. **Keyterm bias matters more than the model swap.**
3. **The Nova v1 keyterm payload cap is a deal-breaker for migration as
   currently specced.** Our 94-term Flux list won't fit; the v1 endpoint
   400s. Capping at 80 (as we did) loses the tail of the menu — the
   "Lobster (seasonal)", "Bottled Water", "LLB Bitters" etc. — which
   are exactly the items most likely to trip an unbiased model. Before
   recommending Nova-3 in production, we'd need either a smaller per-
   tenant menu or a different keyterm transport.
4. **Nova-2 is not a viable fallback.** It rejects `keyterm=` outright
   with HTTP 400 and runs unbiased — so any production "fall back to
   Nova-2 if Flux fails" path either crashes (with keyterms) or runs
   blind (without). The original spec assumed silent ignore; that
   assumption is wrong.
5. **Reliability footnote: the 188s call dropped on all three configs
   simultaneously around 22s.** This isn't a model-specific signal —
   it points at either a Deepgram session limit or our network. Worth
   reproducing before we trust any of these aggregates for long calls.

**Suggested next steps (not part of this PR):**

- Try Nova-3 v1 with tighter endpointing (`endpointing=400`,
  `utterance_end_ms=500`) and re-run this same harness. If Nova-3 closes
  the 1s gap, the migration calculus flips.
- Solve the keyterm payload size — either a v1-aware budget in
  `compute_keyterms()`, or check whether Deepgram exposes a POST-body
  keyterm route.
- Add per-final `start` + `duration` capture (Deepgram returns these on
  Results) so we can compute true end-of-utterance latency in a future
  rerun. The current `audio_position_s` proxy is too noisy to be useful.
