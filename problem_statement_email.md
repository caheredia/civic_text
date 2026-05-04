# CivicBand After Dark: The Extraction Problem
How do we get structured item and vote data out of the unstructured PDF text?

Today I'd like to do something different and document a problem I've been having for almost a year now, and how I've tried to solve it, and how it hasn't worked. My goal here is to see if there are solutions I haven't thought of, or if the problem is truly unworkable with the current constraints.

Here's the problem, in one sentence:

How do we get structured item and vote data out of the unstructured PDF text?

# Motivation

As of this writing, CivicBand is indexing 13 million pages of data. If that data were queryable, like SQL-query queryable, not just generally searchable, suddenly what we can do with CivicBand explodes:

Voting records for every official, aggregated across every committee they've served on.

A complete history of votes taken on housing rights, data center construction, water rights, rent control -- you name it, and we'd have it.

Trends on City Council throughput across any topic or bucket of topics.

And on and on and on.

The real shape of how municipal decisions are made suddenly snaps into focus like never before.

# Constraints

Here are the constraints:

1. It has to work reasonably well on the majority of documents. Every municipality has it's own format and structure, there's nothing like a common pattern within the OCR'd text

2. It has to run "quickly".

	- Right now, it takes the current tesseract-based pipeline about a minute to process a standard minutes doc. This speed allows us to get through the entire set of sites every day, when spread across our five worker boxes.

	- Each document taking up to 3 minutes to process is fine. Taking 5 or more minutes is not. Small changes add up fast.

3. It has to run "cheaply". The funds for CivicBand are fixed, unless we get a massive influx of donations. This means two things in practice.

	- We're not able to spin up 1000 workers to blow through all the documents with a more-compute-intensive model.

	- We're not able to use 3rd-party hosted LLM companies. Even if each page only cost $0.001 (a tenth of a cent) to process with an LLM, that would be $13,000, which is more than our current budget.

4. It has to run "continuously".

	- It's not enough to process the whole corpus once and say "job done". New documents are uploaded every day, and new municipalities are added to CivicBand every week

	- This is another reason why I'm bearish on using a 3rd-party hosted LLM: we'd need a commitment that the company will be around for a while.

5. It has to fit in our mission. We are a project of the Raft Foundation, which is a 501(c)(3) non-profit. We need to carefully check license agreements and data use agreements to make sure we're not accidentally exposing us or Raft to liability.

# Ode to the City Clerk

With the constraints out of the way, let's talk about the data itself. If you look at a page of an agenda or minutes doc from a civic body, you might be tempted to think the data is already well structured. There are often sections, and sub-sections, and line items. There are often vote blocks and discussion blocks and blocks for amendments. Unfortunately, this is human thinking, not computer thinking.

To a computer, agendas and minutes are closer to complicated human poetry than well-formatted data. There's a rough structure every municipality seems to follow, but each civic body interprets that in their own way. Because these forms often don't really aid in readability, we can consider them aesthetic choices of the civic body, a sentiment that grows when you realize two bodies in the same municipality (say, the City Council and the Planning Board) can use distinct forms for their documents.

If you reinterpret the problem as "derive structured data out of an esoteric form of human poetry" you get closer to the truth.

With that preamble, let's talk about what I actually want to extract from these documents.

## Attendance records

Who from the civic body was present. Were they present for the whole meeting?

Who from the public or from civic staff was present? This will often require extracting terms from discussion blocks

## Item records

What's the item being discussed?

Was it in the Consent Calendar, or its own item?

Can we do any sentiment analysis or keyword extraction to try and categorize it?

## Voting records

Who raised the motion? Who seconded it?

Was it a consent vote? Was it a unanimous vote? If it was a unanimous vote, can we break that out by attendance?

Who voted yes? Who voted no? Who abstained?

What makes this complicated isn't just the Civic Poetry angle I described above, but also that these are documents. They are designed by people who are still thinking in terms of print, so they have headers and footers and page numbers and sometimes line numbers and all the other errata that makes perfect sense to a human reading a document but which a computer has some trouble reasoning about. This is why CivicBand deals in pages to begin with, it was the only consistent breakpoint.

It is super common for an item block or vote block to span multiple pages. To a computer, even if we were to join all the pages together, that might read as:

```
Here's some discussion about an item that's going to go to the next page\n
\n
City of Alameda City Council Page 17\n
\n
City of Alameda City Council Tuesday June 16, 2025\n
\n
And here's the rest of the discussion.
```

How would you extract just the item block out of that for 1000 municipalities that all have slightly different header and footer formats?

# What we do today

Today, right now, we follow this algorithm to get searchable text data from these civic body meetings.

- Fetch a document. If it's a PDF, great! If it's not a PDF, make it a PDF; HTML is currently not to be trusted

- Take that PDF and split it into page images. If it's a 10 page PDF, 10 PNGs will come out the other side.

- Run each page image through tesseract, saving the text from that page into a .txt file.

- Build a sqlite DB out of all the text files.

# What we have tried

- spacy entity extraction

	- not fast enough to do in-line with an update job, but fast enough to do once-a-day deltas

	- quality of extracted entities and votes is VERY rough. it's possible I could fix this by fine-tuning a model, this still doesn't fix the header/footer problem

- PaddleOCR instead of tesseract

	10x slower over tesseract; experiment died there

- docTR instead of tesseract with multiple permutations on the Text Detection and Text Recognition architectures

	Also 10x slower over tesseract; experiment died there

- Training my own machine learning algorithm to pull out votes

	The less said about this experiment the better; it did not work

- Shoving it into a text-parsing LLM running under ollama with instructions to extract votes

	- Waaaay too slow, and can't be distributed across multiple workers without a spend on GPUs that our budget can't support

# What am I missing?

I am not a data scientist or data engineer. Before starting CivicBand, I'd worked on exactly one production machine learning problem, and that was in 2016. I'm sure there are things I could be doing better, but I don't know what I don't know.

This is where you, yes you reading this, come in. Do you have thoughts on how I could solve this problem? Do you know someone who's solved similar problems and would be willing to help a non-profit? I'm extremely open to ideas, suggestions, PRs, and articles. I'm less open to ChatGPT answers, because I've already tried asking the LLMs, which is how we got to the "what I have tried" above.

I thought about how discussion on this could happen, and I think my best bet here is a Github Issue on one of our public repos. We have a Zulip, and I'm happy to invite people to that, but Github is probably more accessible. If that doesn't work for you, reach out to phildini@civic.band.

Please: Reach out, or pass this along to someone who would. And thanks 🙇‍♂️

