"""CaneSense web service: the ADK agent API plus a small chat page and the village pictures.

Runs on Cloud Run. Sessions and memory go to Vertex AI Agent Engine when AGENT_ENGINE is set, otherwise to a local SQLite file.
"""
import asyncio
import logging
import os

import pydantic_core
from fastapi import Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.cli.fast_api import get_fast_api_app
from google.adk.cli.utils.service_factory import create_session_service_from_options
from google.adk.live.live_request_queue import LiveRequest, LiveRequestQueue
from google.adk.runners import Runner
from google.genai import types

log = logging.getLogger('canesense')
_h = logging.StreamHandler(); _h.setFormatter(logging.Formatter('%(name)s %(message)s'))
for _n in ('canesense', 'canesense.agent', 'canesense.models'):
    _l = logging.getLogger(_n); _l.setLevel(logging.INFO); _l.addHandler(_h); _l.propagate = False   # timing lines reach the Cloud Run log

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENTS_DIR = os.path.join(ROOT, 'agents')
DATA_DIR = os.environ.get('DATA_DIR', os.path.join(ROOT, 'data'))
WEB_DIR = os.path.join(ROOT, 'web')

# AGENT_ENGINE is the full resource name, projects/<p>/locations/<region>/reasoningEngines/<id>, so the sessions and
# memory bank can live in one region (asia-south1) while Gemini is called through the global endpoint.
engine = os.environ.get('AGENT_ENGINE')
session_uri = f'agentengine://{engine}' if engine else os.environ.get('SESSION_SERVICE_URI', 'sqlite+aiosqlite:////tmp/canesense_sessions.db')
memory_uri = f'agentengine://{engine}' if engine else None

app = get_fast_api_app(
    agents_dir=AGENTS_DIR,
    session_service_uri=session_uri,
    memory_service_uri=memory_uri,
    allow_origins=['*'],
    web=False,
    auto_create_session=True,
)

# ---- usage guard: the page is public for the judges, so model-calling requests are capped per client and per hour.
# A bot or a runaway script gets a polite 429; the mill's bill stays bounded. Static files and pictures are not counted.
import time as _time
from collections import defaultdict, deque
from starlette.responses import JSONResponse

PER_CLIENT_10MIN = int(os.environ.get('RATE_PER_CLIENT_10MIN', '30'))
PER_HOUR_ALL = int(os.environ.get('RATE_PER_HOUR_ALL', '300'))
_client_hits: dict[str, deque] = defaultdict(deque)
_all_hits: deque = deque()


def allow_request(client: str) -> bool:
    now = _time.monotonic()
    q = _client_hits[client]
    while q and now - q[0] > 600:
        q.popleft()
    while _all_hits and now - _all_hits[0] > 3600:
        _all_hits.popleft()
    if len(q) >= PER_CLIENT_10MIN or len(_all_hits) >= PER_HOUR_ALL:
        return False
    q.append(now)
    _all_hits.append(now)
    return True


def client_of(headers, fallback: str) -> str:
    fwd = headers.get('x-forwarded-for', '')
    return (fwd.split(',')[0].strip() if fwd else '') or fallback


BUSY = {'detail': 'CaneSense has answered a lot of questions in the last few minutes. Please try again in a little while.'}


@app.middleware('http')
async def usage_guard(request, call_next):
    if request.method == 'POST' and request.url.path in ('/run', '/run_sse'):
        who = client_of(request.headers, request.client.host if request.client else 'unknown')
        if not allow_request(who):
            log.warning('usage guard: refused %s', who)
            return JSONResponse(BUSY, status_code=429)
    return await call_next(request)


app.mount('/pictures', StaticFiles(directory=os.path.join(DATA_DIR, 'pictures')), name='pictures')
app.mount('/static', StaticFiles(directory=WEB_DIR), name='static')


@app.get('/', include_in_schema=False)
async def index():
    return FileResponse(os.path.join(WEB_DIR, 'index.html'))


@app.get('/health', include_in_schema=False)
async def healthz():
    return {'ok': True}


# ---- spoken CaneSense: our own live route so the speech language and voice can be chosen per session ----
# The stock /run_live route takes no speech config, and without a language code the voice reads digits in
# English inside a Marathi sentence. Here the browser passes lang (mr-IN, hi-IN, kn-IN, en-IN) and the voice.
LIVE_APP = 'canesense_live'
LANGS = {'mr-IN', 'hi-IN', 'kn-IN', 'en-IN'}
LANG_NAMES = {'mr-IN': 'Marathi', 'hi-IN': 'Hindi', 'kn-IN': 'Kannada', 'en-IN': 'English'}
DEFAULT_VOICE = os.environ.get('GEMINI_LIVE_VOICE', 'Aoede')
VOICES = {'Aoede', 'Leda', 'Zephyr', 'Kore', 'Charon', 'Puck', 'Fenrir', 'Orus'}
_live_runner = None


def live_runner() -> Runner:
    global _live_runner
    if _live_runner is None:
        from canesense_live.agent import root_agent  # agents dir is on sys.path once ADK has loaded the apps
        svc = create_session_service_from_options(base_dir=AGENTS_DIR, session_service_uri=session_uri)
        _live_runner = Runner(app_name=LIVE_APP, agent=root_agent, session_service=svc)
    return _live_runner


@app.websocket('/live')
async def live(websocket: WebSocket, user_id: str, session_id: str,
               lang: str = Query(default='mr-IN'), voice: str = Query(default=DEFAULT_VOICE)):
    await websocket.accept()
    if not allow_request(client_of(websocket.headers, websocket.client.host if websocket.client else 'unknown')):
        log.warning('usage guard: refused a voice session')
        await websocket.close(code=1013, reason='busy')          # 1013: try again later
        return
    lang = lang if lang in LANGS else 'mr-IN'
    voice = voice if voice in VOICES else DEFAULT_VOICE
    runner = live_runner()
    svc = runner.session_service
    if not await svc.get_session(app_name=LIVE_APP, user_id=user_id, session_id=session_id):
        await svc.create_session(app_name=LIVE_APP, user_id=user_id, session_id=session_id,
                                 state={'lang': lang, 'lang_name': LANG_NAMES[lang]})
    queue = LiveRequestQueue()
    run_config = RunConfig(
        streaming_mode=StreamingMode.BIDI,
        response_modalities=['AUDIO'],
        speech_config=types.SpeechConfig(
            language_code=lang,
            voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))),
        # push to talk: the browser marks the start and end of each question, so talk in the room is never heard
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(disabled=True)),
    )

    async def forward():
        async for event in runner.run_live(user_id=user_id, session_id=session_id, live_request_queue=queue, run_config=run_config):
            await websocket.send_text(pydantic_core.to_json(event.model_dump(exclude_none=True, by_alias=True, mode='json')).decode())

    async def receive():
        while True:
            queue.send(LiveRequest.model_validate_json(await websocket.receive_text()))

    tasks = [asyncio.create_task(forward()), asyncio.create_task(receive())]
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
    try:
        for t in done:
            t.result()
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        log.exception('live session failed')
        try:
            await websocket.close(code=1011, reason=str(e)[:120])
        except Exception:  # noqa: BLE001
            pass
    finally:
        for t in pending:
            t.cancel()
        queue.close()
