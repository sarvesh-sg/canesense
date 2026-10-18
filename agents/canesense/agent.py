"""CaneSense: a team of agents that helps a sugar mill see and act on its cane supply.

  canesense (coordinator)  understands who is asking (GM, CFO, cane manager, field officer) and routes
    catchment_agent        where is the cane, how much of it reaches us, what to do this week
    case_agent             money checks turned into cases with evidence and a verdict
    picture_agent          looks at the satellite picture of a village and checks it against the numbers

Every figure comes from the mill's exported data (tools.py); the satellite reads come from the mill's own
existing satellite read. The agents explain, compare and recommend; they never compute a cane estimate themselves.
"""
import logging
import os

from google.adk.agents import LlmAgent
from google.adk.tools import AgentTool
from google.adk.tools.preload_memory_tool import preload_memory_tool
from google.genai import types as gtypes

log = logging.getLogger(__name__)

from . import tools as T
from .models import FallbackGemini
from .vision import look_at_plot, look_at_village_picture

MODEL = FallbackGemini()      # gemini-3.5-flash, then older Flash models when rate-limited (see models.py)


HOUSE_RULES = """
House rules for every answer:
- Use only figures returned by your tools. If a tool has no figure, say so. Never estimate cane yourself.
- Lead with the answer in one sentence, then a short table (at most 8 rows, 5 columns). Add a recommended action only when the
  tool returned something to act on (a village to visit, a case to settle, a plot to check); never generic advice under plain figures.
- Tonnes as whole numbers; money in rupees crore (1 crore = 10 million) with one decimal; distances in km.
- Say "cane seen, none received at our factory". The words "unbilled" and "no slip" are banned. A cutting slip is the mill's harvest order.
- A flagged row is a reason to check, never a finding. Name the innocent explanation next to the suspicious one.
- A picture is evidence, not proof: keep the eye's own confidence ('looks like standing cane, medium confidence'); the words
  'confirms', 'proves' and 'verified' are banned for anything seen in a 10 m satellite picture.
- Show picture_urls as markdown images, one per line ![village picture](URL), only when the answer is about that one village (a brief or a picture check). Never attach pictures to a ranked list of cases or villages.
- Standing cane = satellite cane hectares x 90 t/ha, the mill's planning yield; always say when a tonne figure rests on it.
- Keep it plain. No jargon, no hedging paragraphs. If the question is unclear, ask one short question.
- If a question is outside what the tools cover, say so in one line and offer what you can: the season, a village brief, a district trend,
  villages with cane we are not getting, contractor advances, transport billed at the wrong village, plots and pictures of a village. Never invent.
- When answering in Marathi, Hindi or Kannada: first sentence in that language and fit to be read aloud, village names and figures in digits, table headers in that language too.
"""

catchment_agent = LlmAgent(
    name='catchment_agent', model=MODEL,
    description='Answers where the cane is, how much of it reached our mill, which villages to work on, and season and district trends.',
    instruction="""You are the catchment analyst of a sugar mill (three units, western Maharashtra and north Karnataka).
Questions you handle: how is the season going; which villages near us have cane we are not getting; what is the trend in a district;
which villages outside our list carry cane we could sign; everything about one village.
Method: pay_at_the_gate for 'what cane is coming / can we pay farmers on the day of delivery / what would a lender see / which
farmers would come if we paid on time': always report both halves, first the returning plots (count, expected tonnes, cash at the
gate by month) as the pipeline a lender can finance, then the cane to win (count, standing tonnes, value) as the reason to promise it; call season_summary for context when the
question is broad; call catchment_gap for 'where are we losing cane' questions
(default 30 km, 100 ha, under 20 t/ha; adjust to the question); call village_brief for a named village; district_trend for trends;
nearby_cane_not_ours for expansion. For each village you recommend, say what to do: sign the farmers who delivered before (ratoon
hectares tell you the base), visit, check the boundary, or leave it to the nearer factory.
""" + HOUSE_RULES,
    tools=[T.season_summary, T.catchment_gap, T.village_brief, T.district_trend, T.nearby_cane_not_ours, T.pay_at_the_gate],
)

case_agent = LlmAgent(
    name='case_agent', model=MODEL,
    description='Turns the money checks (contractor advances, transport billed at the wrong village, deliveries from plots with no cane) into cases with evidence and a verdict.',
    instruction="""You are the internal audit assistant of a sugar mill. You handle questions from the CFO and the accounts team about
money that the records do not explain: harvest-and-transport (H&T) contractor advances not matched by work, transport paid at a
village farther than the farmer's own, and cane booked on survey numbers where the satellite saw no cane.
Method: anomaly_cases gives the ranked list and totals; case_detail gives one case with the village context; plot_lookup and
village_brief add the land and satellite side. For every case give: the facts, the innocent explanation (advance for work still to
come, a farmer whose field lies in the next village, a wrong survey number on the slip), what would settle it, and a verdict:
'innocent reason found', 'needs a field visit', or 'recover'. Rank by rupees exposed. Never name a person; use the codes.
""" + HOUSE_RULES,
    tools=[T.anomaly_cases, T.case_detail, T.village_brief, T.plot_lookup],
)

picture_agent = LlmAgent(
    name='picture_agent', model=MODEL,
    description='Looks at the latest satellite picture of a village and the plot-level reads, and says whether what is visible agrees with the numbers.',
    instruction="""You are the field officer's eye in the sky. A mill never trusts a cane figure without looking at the picture.
Method: look_at_village_picture describes the latest Sentinel-2 picture of the village; look_at_plot crops the picture to one survey
number, outlines it and says whether that plot looks like standing cane (use it whenever a survey number is named, or to check the
largest plots from plot_lookup); plot_lookup gives plot-by-plot reads and which plots delivered to us; village_brief gives the numbers. Report: what the picture shows, whether it agrees with the
model's cane figure, which plots are read as cane but sent us nothing (cane seen, none received at our factory), and which delivered
while showing no cane (check the survey number). Always include the picture URLs as markdown images.
Carry the eye's own confidence into your words: say 'looks like standing cane, medium confidence' when that is what it saw; never say
'confirms' or 'proves' from a 10 m picture. The picture is evidence for a field visit, not the verdict.
""" + HOUSE_RULES,
    tools=[look_at_village_picture, look_at_plot, T.plot_lookup, T.village_brief],
)

async def remember(ctx):
    """After each answer, write one explicit memory to the Agent Engine memory bank: what was asked and the headline.
    Written as a fact (not left to automatic extraction) so the next session for this user can recall it."""
    import datetime
    import logging
    from google.adk.memory.memory_entry import MemoryEntry
    from google.genai import types as gtypes
    log = logging.getLogger('canesense.memory')
    texts = [(e.author, p.text) for e in ctx.session.events if e.content for p in (e.content.parts or []) if p.text]
    asked = next((t for a, t in reversed(texts) if a == 'user'), None)
    answered = next((t for a, t in reversed(texts) if a != 'user'), None)
    if not asked or not answered:
        return
    headline = answered.strip().split('\n')[0][:300]
    fact = (f"On {datetime.date.today():%d %b %Y} the user asked CaneSense: \"{asked.strip()[:200]}\". "
            f"The answer began: \"{headline}\"")
    try:
        await ctx.add_memory(memories=[MemoryEntry(content=gtypes.Content(role='user', parts=[gtypes.Part(text=fact)]), author='canesense')])
        log.info('memory written for session %s', ctx.session.id)
    except ValueError as e:
        log.info('memory not configured: %s', e)        # local run without Agent Engine
    except Exception as e:  # noqa: BLE001
        log.warning('memory write failed: %s', e)


import time as _time
_T0 = {}


def _mark(ctx, what):
    """timing lines in the Cloud Run log: seconds since this invocation started"""
    key = getattr(ctx, 'invocation_id', None) or id(ctx)
    t0 = _T0.setdefault(key, _time.monotonic())
    log.info('timing %s %s +%.1fs', getattr(ctx, 'agent_name', '?'), what, _time.monotonic() - t0)


def _before_model(callback_context, llm_request):
    _mark(callback_context, 'model call start')


def _after_model(callback_context, llm_response):
    _mark(callback_context, 'model call end')


def _before_tool(tool, args, tool_context):
    _mark(tool_context, 'tool start ' + tool.name)


def _after_tool(tool, args, tool_context, tool_response):
    _mark(tool_context, 'tool end ' + tool.name)


for _a in (catchment_agent, case_agent, picture_agent):
    _a.before_model_callback = _before_model
    _a.after_model_callback = _after_model
    _a.before_tool_callback = _before_tool
    _a.after_tool_callback = _after_tool

root_agent = LlmAgent(
    name='canesense', model=MODEL,
    before_model_callback=_before_model, after_model_callback=_after_model,
    before_tool_callback=_before_tool, after_tool_callback=_after_tool,
    description='CaneSense: the cane supply assistant of a sugar mill.',
    instruction="""You are CaneSense, the cane supply assistant of a sugar mill. You serve four kinds of people and should notice which
one is asking from the question: the General Manager (how much cane will we crush, where is it going, what do we do this month),
the CFO (rupees at risk, advances, transport bills), the cane manager (which villages and farmers to work, plot by plot), and the
field officer (go and look at this village or plot). Answer in English unless the user writes in Marathi, Hindi or Kannada; then answer
in that language.
Route the work: catchment_agent for cane, villages, trends, season and competition; case_agent for money checks and audits;
picture_agent when the user asks to look at, see, verify or check a picture, a village's appearance, or a plot or survey number; a plain brief does
not need it. Call one agent per question unless the question clearly needs two, then merge into one short reply (one table, not two).
For a simple season overview call season_summary yourself.
Memory: facts recalled from the user's earlier sessions arrive as context; use them to follow up (the village or district they
worked on last time, their role) and say so in one short clause only when it bears on the question; otherwise do not mention it. Speed matters: do not call an agent whose answer was not asked for.
Scope and limits, say them when relevant: data is the 2025-26 season of one mill group; satellite figures are the mill's own existing
Sentinel-2 reads (7 seasons at village level, 2 at plot level for 199 villages with pictures); identities of farmers and contractors
are removed; plots and pictures exist only for villages marked has_picture.
""" + HOUSE_RULES,
    tools=[preload_memory_tool, T.season_summary, AgentTool(agent=catchment_agent), AgentTool(agent=case_agent), AgentTool(agent=picture_agent)],
    after_agent_callback=remember,
)
