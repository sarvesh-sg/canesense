# CaneSense

**The cane supply assistant of a sugar mill.** Satellite reads of every village and plot, the mill's own
delivery and payment records, and a team of Gemini agents that answer the questions a General Manager,
a CFO, a cane manager and a field officer actually ask.

AI Builder Cup 2026 entry. Theme: **Manufacturing: Intelligent Operations & Industrial Efficiency**,
the upstream raw-material problem: a sugar mill lives or dies by the cane that reaches its gate.

## The problem

A sugar mill in western India crushes 2.1 million tonnes of cane in a season and pays about Rs 690 crore
to 33,000 farmers and Rs 227 crore to harvesting and transport contractors. It has no reliable view of
how much cane stands in its villages, how much of it will come to its gate, and where the rest goes.
Its records are full of rows that "need a look" (advances not matched by work, transport billed at the
wrong village, cane booked on survey numbers that show no cane) and nobody has time to look.

The mill in this prototype already has its own satellite read of cane (an existing system, not part of this repository), village by
village for seven seasons and plot by plot for the latest two. The satellite says 158,000 ha of cane
stood in its 699 supply villages in 2026, about 14 million tonnes at the planning yield. The mill
received 15 percent of it. Inside 15 km of its gates, 32 percent. Between 15 and 30 km, 11 percent.

## What CaneSense does

Four agents built with the Agent Development Kit (ADK) and Gemini, deployed on Cloud Run:

| Agent | For whom | What it does |
|---|---|---|
| `canesense` (coordinator) | everyone | works out who is asking and routes; merges answers; enforces the house rules |
| `catchment_agent` | GM, cane manager | where the cane is, how much reached us, which villages to work this month, district trends, villages to sign |
| `case_agent` | CFO, accounts | turns money checks into cases: facts, innocent explanation, what settles it, verdict |
| `picture_agent` | field officer | Gemini looks at the latest Sentinel-2 picture of a village and checks it against the numbers and the plot reads |

Every figure in an answer comes from a tool over the exported data; the agents explain, compare and
recommend, they never compute a cane estimate. The picture agent is a hybrid: the mill's own satellite
model gives the area, Gemini gives the eyes.

## Architecture

```
browser ──► Cloud Run service (FastAPI, ADK API server)
             ├─ /            chat page (web/)
             ├─ /run_sse     ADK runner: canesense ─► catchment_agent | case_agent | picture_agent
             │                 tools: season_summary, catchment_gap, village_brief, district_trend,
             │                        nearby_cane_not_ours, anomaly_cases, case_detail, plot_lookup,
             │                        look_at_village_picture (Gemini vision, google-genai)
             ├─ /pictures    Sentinel-2 true colour + greenness, one pair per village
             └─ sessions     Agent Engine session + memory service (agentengine://) or SQLite locally
Gemini on Vertex AI (GOOGLE_GENAI_USE_VERTEXAI=TRUE)
data/  anonymised export from the mill's database (produced inside the mill, see Data and grounding), read-only at runtime
```

Google Cloud used: Cloud Run (service), Vertex AI Gemini (reasoning and vision), Agent Development Kit
2.x (agents, tools, API server), Agent Engine sessions and memory bank (when
`AGENT_ENGINE` is set to its resource name), Cloud Build (source deploy).

## Data and grounding

`data/` is produced inside the mill by an export step that is not part of this repository (it runs against the mill's
product and its satellite model, which stay private). The export contract is the set of JSON files below; any mill
that can produce them is onboarded:

- `villages.json`: 699 supply villages, satellite cane per season 2020 to 2026 (six layers), deliveries 2025-26 by month, distance to our nearest mill and to the nearest competing factory, ratoon on plots that delivered to us, satellite harvest progress.
- `highcane.json`: 411 villages outside the supply list with 50 ha or more of cane.
- `districts.json`: 66 districts of Maharashtra and Karnataka, seven seasons.
- `plots/<village_id>.json`: plot-level reads (2025, 2026) for the 199 villages that have a picture, with tonnes delivered per survey number.
- `pictures/<village_id>/`: latest clear Sentinel-2 true colour and greenness picture, downsized, with its date.
- `anomalies.json`: three money checks, identities removed.
- `summary.json`: season totals.

Identities: farmers appear only as counts, contractors as codes `C-0001`..., no bank, phone or name
data leaves the mill. The satellite figures come from the mill's existing satellite read (Sentinel-2, 10 m); this
prototype does not recompute them.

Guardrails, in the agents' instructions: use only tool figures; say when a figure rests on the 90 t/ha
planning yield; a flagged row is a reason to check, never a finding; name the innocent explanation
beside the suspicious one; never name a person. Scope and limits are stated on the page and by the
coordinator when relevant.

## Sample questions that work

- How did the 2025-26 season go, and how much of the cane standing in our villages did we actually get?
- Which villages within 30 km have a lot of cane we are not getting? What should I do this month?
- Give me the brief on Ashtha.
- Which H&T contractors took an advance and did not earn it back? How much is exposed?
- Where are we paying transport at the wrong village's distance, and what does it cost us?
- What is the cane trend in Sangli district over the last seven seasons?
- Look at the picture of Bedag and tell me if it agrees with the model's cane figure.
- In Ashtha, which plots are read as cane but sent us nothing, and which sent cane while showing none?

Voice, with Gemini Live: press "Talk to CaneSense" and speak in Marathi, Hindi, Kannada or English. The
browser streams the microphone to the ADK live websocket; a second agent (`agents/canesense_live`, model
gemini-live-2.5-flash) listens, calls the same tools, and speaks the answer back in the language it heard,
in an Indian voice with the speech language set per session (`/live` route in `app/main.py`), so figures are
spoken the way that language speaks them. Both transcriptions are written into the chat. Village names are matched as spoken
or in Devanagari (Asta, Ashta, आष्टा all find Ashtha). Typing in English is a real barrier for field
officers, contractors and farmers in rural India; speaking is not.

Limits: one mill group, season 2025-26; plots and pictures for 199 villages only; answers take 10 to 75
seconds because a question may pass through two agents and three tools; the picture agent makes one
extra Gemini vision call.

## Tests

Nine tools, no model, no network: `DATA_DIR=data python -m unittest tests/test_tools.py`. They check the
season figures, the catchment ranking, village briefs, spoken and Devanagari and Kannada village names, the
district trend, cane outside our list, contractor cases with codes only, plot reads, and that no name is in the export.

## Run locally

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # fill in the project; or set GOOGLE_API_KEY and GOOGLE_GENAI_USE_VERTEXAI=FALSE
set -a; . ./.env; set +a
uvicorn app.main:app --port 8080
```

Open http://localhost:8080.

## Deploy to Cloud Run

```bash
PROJECT=your-project REGION=asia-south1 ./deploy.sh
# optional: AGENT_ENGINE=projects/<p>/locations/<region>/reasoningEngines/<id> for Agent Engine sessions and memory
```

## Re-export the data from a mill

```bash
# data/ is produced by the mill's export step (not in this repo); the sample export is committed
```

The export expects the mill's cane management database (villages, plots, trips, weighments, payments,
advances) and the satellite read tables its remote-sensing pipeline fills. Any mill with the same
pipeline can be onboarded by running this one script.

## Why it scales

Every sugar mill has the same upstream problem, and Sentinel-2 covers every cane field on earth every
five days. The mill's satellite read already covers 66 districts across two states;
the agents are mill-agnostic and read whatever the export gives them. India alone has over 700 running
mills; Thailand, Indonesia, the Philippines and Australia add several hundred more in the JAPAC region.
