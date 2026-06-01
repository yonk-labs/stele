# What Actually Moves RAG Accuracy (And What I Spent A Week Measuring Wrong)

So one question broke my brain for a week.

It was a LoCoMo question: *"When did Caroline meet up with her friends, family, and mentors?"* And our memory layer kept whiffing on it. Simple question. The answer was sitting right there in the conversation. And retrieval just... missed it.

Here's the thing about a single failing question: it's a thread, and if you pull it, you find out half of what you believed about your system was a small-sample illusion. I pulled it. What came out was a cross-corpus, multi-system benchmark, a pile of retracted conclusions, and a genuinely useful answer to "how should you actually configure retrieval." Let me walk you through it, including the parts where I was wrong. Especially those parts.

## Three theories, all dead

When q07 failed, I had theories. I love a theory.

**Theory one: the chunks are too big, the answer's getting diluted.** Reasonable! I went to shrink the chunk size. My colleague pushed back: "vector search caught this at 1000 words, so size is fine, it's the hybrid fusion." So we measured it. Turns out the answer chunk had a perfectly healthy cosine similarity (0.60). It was findable. It just wasn't *top-ranked*. Size wasn't the bug.

**Theory two: the vector index is broken.** The approximate-nearest-neighbor search ranked the answer differently than exact cosine, so obviously HNSW was hurting us. Measured it. Even *perfect* brute-force cosine put the answer at rank 39 of 66. The query (friends, family, mentors, meeting up) is just semantically diffuse across a life-chat. No metric saves you. Index wasn't the bug.

**Theory three: it's the punctuation in the keyword query.** And this one was *real*: our FTS query was literally searching for `"friends,"` with the comma glued on, plus stopwords like "when" and "with" letting every chunk match. A genuine bug. I fixed it. It changed q07's result by exactly zero, because the hybrid path didn't even use that code.

Three theories. Three measurements. Three corpses. The actual fixes were unglamorous: strip stopwords from keyword queries, and a *one-line* bug where hybrid search was returning 500-character snippets instead of full chunks. That snippet bug, by the way, had been quietly inflating a "cascade beats baseline" result by feeding it 3× more context. **A correctness bug will impersonate an architecture win every single time.** Audit the bytes that actually reach the model before you believe any retrieval comparison.

## Then I scaled it up and watched my conclusions die

Once the fixes were in, I ran the real thing: stele's retrieval against three domains, conversational memory (LoCoMo), multi-hop factoid (HotpotQA), and biomedical QA (CovidQA), plus the obvious competitors, Mem0 and Letta. Same answerer, same judge, same corpora. Apples to apples for once.

First pass: 40 questions per corpus. I got a clean story. Facts-packing (summarize the retrieved chunks into a digest, append date-resolved facts) looked like a temporal specialist. It won on LoCoMo. I wrote it up. Felt good.

Then someone asked the question that matters: *"Did you run the full benchmark, or just small tests?"*

Small tests. Forty questions out of fifteen hundred. Two and a half percent, capped at ten questions per conversation, only four of ten conversations. So I ran it properly: 250 questions, stratified across all conversations.

**Facts-packing flipped.** At n=40 it beat raw chunks 0.75 to 0.68. At n=250 it *lost*, 0.636 to 0.704. The whole "digest is the buy path" thesis I'd been carrying for weeks? A sampling artifact. Gone.

And it wasn't alone. The exact-vs-HNSW comparison I'd just reported as "they're identical, HNSW is fine"? Turned out both stores shared the same database table, so I'd accidentally measured the same index twice. Retracted. The Mem0 numbers swinging between 0.14 and 0.83 depending on a faiss path bug? Found it, fixed it, the real number was lower and noisier. The worry that factoid scores were just the model answering from pretraining? I built a no-context baseline to check: the floor was 0.00 on LoCoMo, 0.02 on HotpotQA. The scores were real. Concern disproved by the thing concerns are supposed to be disproved by: a measurement.

Look, this is the actual job. Not having theories. Anyone can have theories. The job is building the control that kills your favorite theory before you ship it as a finding.

## What survived

Here's what held up under proper N, across all three domains:

**Reduction loses to raw.** Every flavor of "compress the content to save tokens" (Mem0's LLM-extracted memories, our consolidation chunker, query-time digests, the kitchen-sink digest-mix) all tied or lost to just feeding the raw retrieved chunks. On conversational memory: raw 0.70, facts 0.64, digest 0.60, the fancy "enhanced" substrate 0.54. Compression throws away the exact detail the answer needs, wherever you do it. The most-compressed system in the bake-off (Mem0, 26 to 462 tokens of atomic facts) was also the least accurate (0.11 to 0.44). The three systems literally line up on a monotonic accuracy-versus-tokens curve: more retained context, more accuracy. There's no free lunch in there.

**The old keyword default was a catastrophe.** 0.05 to 0.35 depending on corpus, versus 0.70 to 0.94 for hybrid. If you're still doing pure keyword retrieval over a chunk store, that's the single biggest, cheapest fix available to you.

**Document size is the variable nobody routes on.** When the document is small enough to fit your context budget (most factoid corpora), just feed the whole thing. Retrieval *adds* tokens and latency for zero accuracy gain. We were burning tokens retrieving and re-assembling chunks of a document that was 900 tokens to begin with.

And the one I'm a little embarrassed about: **we were duplicating content.** Letta hit our accuracy at half our tokens on factoid, and I wanted to know how. Answer: it wasn't smarter. Our `neighbor_window` setting wraps every retrieved chunk with its neighbors. Great for adding context in a long document, pure waste in a short one, where it just feeds the same text two or three times. Turn it off on small docs and stele matches Letta's ~500-token efficiency *and beats its accuracy* (0.944 vs 0.92). The "competitive gap" was self-inflicted.

## The payoff: presets, not a single default

This is where it gets practical, because the whole point was never a leaderboard. It's that **accuracy, tokens, and latency are a three-way trade, and the right point on that triangle depends on what you're doing.** So you don't ship one default. You ship a few honest ones:

- **Balanced** (the default): hybrid retrieval, neighbor context on, ~10 chunks. Good everywhere: 0.70 on conversation, 0.94 on factoid.
- **Max accuracy**: feed the whole doc when it fits, otherwise pull more chunks. Costs tokens and time; buys the ceiling.
- **Token-min / fast**: neighbor context off, fewer chunks. On factoid this is *strictly better*: 0.944 at 498 tokens, faster answers, less spend. On long conversation you pay a few accuracy points for the savings.
- **The routing rule that sits above all of them**: small doc, feed it whole; big doc, retrieve.

None of this is a model choice. Nobody swapped a 70B for a 405B. It's chunking strategy, retrieval mode, how many chunks, and whether you're duplicating context. The unglamorous data-engineering layer that I've been saying for twenty years is where the hard problems actually live. In AI Land the hard problem is *still* not model selection. It's the pipeline.

## Why this should bug you

If you're benchmarking agent memory right now (and a lot of people are, loudly), here's what this week taught me, and what I'd bet most published comparisons get wrong:

Your small-N run is lying to you. Forty questions feels like a benchmark and behaves like a coin flip; the margins that look like findings are noise, and the one that flips when you 6× the sample size was never real. Cross-vendor numbers are almost never apples-to-apples (different embedder, different judge, different retrieval-k, different answer model), and the moment I held those constant, half the "X beats Y" headlines collapsed into "X and Y use different embedders." And a correctness bug in your harness will cosplay as a brilliant result until you check the bytes.

We have the receipts now: every lane, every corpus, accuracy and tokens and latency, with the parametric floor measured and the wrong turns documented. That's the part I actually care about. Not that stele won (it did, on the axes that matter and reproducibly). That we can *show our work*, including the work where we were wrong.

So here's my challenge to you, and I mean it: before you trust your own RAG numbers, run the no-context baseline, 6× your sample, and diff the bytes that reach the model. If your conclusions survive all three, *now* you've got something. If they don't, better you find out than your users.

(Sorry, not sorry. Go re-run your benchmark.)
