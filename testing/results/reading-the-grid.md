# Reading the Big-Ass Grid: A Field Guide to Our RAG Bake-Off

So I built a spreadsheet with about 150 rows of benchmark results, opened it up, and my honest first reaction was: nobody is going to read this. It's a wall of codenames (`hybrid_raw_hnsw`, `nb0_k=10`, `A:sentence_aware+facts`) and numbers. It looks like the output of a robot having a stroke.

But there's a real story buried in there, and once you know the three things each row is telling you, it reads like a map. Let me hand you the map. (If you're a junior dev who just got told to "look at the RAG numbers," this one's for you.)

## What a row actually is

Every row is one **recipe** run against one **dataset**, graded on the exact same questions by the exact same judge. That's the whole point. Change one thing at a time, keep everything else nailed down, and the differences mean something.

Three columns do the heavy lifting:

- **`system`** is *who* made the row. `stele-highN` is us, on the big confident runs (250 questions). `mem0-local` and `letta-archival` are two competitors. And `PARAMETRIC-FLOOR` is the most important row nobody talks about. That's the model answering with *no memory at all*.
- **`lane`** is *the recipe.* This is the scary-looking part, and it's really just three decisions glued together: how you **slice** the document (the chunker), how you **pick** the relevant pieces for a question (retrieval), and how you **format** those pieces for the model (packing). So `hybrid_raw_hnsw` reads as: pick chunks with hybrid search, hand them over raw, using the fast vector index. That's it.
- **`jscore`** and **`~tokens`** are *the scoreboard.* jscore is "what fraction of answers were right" (higher is better). Tokens is "how much context did we shove at the model" (lower is cheaper and faster). Every interesting fight in this grid is one of those two trying to win without wrecking the other.

That's the decoder ring. Now let's walk the actual numbers.

## Rule #1: always read the floor first

Here's the deal. Before you get excited about any score, look at `PARAMETRIC-FLOOR`. On our conversation dataset it's **0.00**. On the factoid ones it's 0.02 and 0.04. Translation: the model knows basically *nothing* about these questions on its own. So when a system scores 0.84, that 0.84 is real retrieval work, not the model quietly cheating off its training data.

This is the step everyone skips, and it's how half the RAG benchmarks on the internet fool themselves. Measure what the model already knew, then subtract it. Always.

## The conversation dataset (LoCoMo): not close

This one's a blowout. Long, rambling chat histories ("when did Caroline meet up with her friends?") where you have to find the needle.

- stele, whole conversation fed in: **0.84**
- stele, retrieved raw chunks: **0.70**
- Letta: **0.56**
- Mem0: **0.11**
- old keyword-only retrieval: **0.05** (basically the floor)

Two things jump out. One, that `keyword` row sitting at 0.05 is why hybrid search is now our default. Pure keyword matching is a trap on conversational text. Two, look at Mem0 at 0.11: it's the most *compressed* system in the bunch (it boils everything down to tidy little facts), and it's also the least accurate. Compression threw away the detail the answer needed.

## The factoid datasets (HotpotQA, CovidQA): efficiency matters

Short documents, fact-style questions. Everyone does better here, so now the fight is about *tokens*, not just accuracy. And this is where the grid taught us something embarrassing.

On HotpotQA, Letta scored 0.92 at ~500 tokens, and we scored about the same but using *more* context. Annoying. So we dug into a knob called the **neighbor window**. By default we wrap every retrieved chunk with its neighbors for extra context. Great on a long document. Total waste on a short one, where it just feeds the model the same paragraph twice. Turn it off (`nb0_k=10`) and stele hits **0.94 at 498 tokens**: same budget as Letta, better answers. The gap was self-inflicted. (Sorry, past me.)

CovidQA tells the same story: stele 0.78, Letta 0.74, Mem0 0.14, floor 0.04.

## What the grid actually proved

1. **Raw chunks beat every kind of summarizing.** On conversation: raw 0.70, "facts" packing 0.64, "digest" 0.60, the fancy enriched version 0.54. Every time you compress to save tokens, you pay for it in accuracy.
2. **Match the recipe to the document.** Small doc that fits the budget? Just feed the whole thing. Big doc? Retrieve, and let chunks bring their neighbors. One default does not fit all.
3. **The unglamorous knobs win.** Nobody swapped in a bigger model anywhere in this grid. Every gain came from chunking, retrieval mode, and how many chunks you pass. In AI Land the hard problem is still data engineering, not model selection.

So that's the map. Next time someone drops a 150-row benchmark grid on you, don't panic. Find the floor, find the `system` and `lane` columns, and ask the only two questions that matter: *is it right, and what did it cost?*

Now go read your own grid. I bet the floor's higher than you think.
