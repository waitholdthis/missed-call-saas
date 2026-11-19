import logging
import os
import re
from collections import OrderedDict

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from openai import AsyncOpenAI, OpenAIError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData
from twilio.base.exceptions import TwilioException
from twilio.http.http_client import TwilioHttpClient
from twilio.request_validator import RequestValidator
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
from twilio.twiml.voice_response import VoiceResponse
from requests.exceptions import RequestException

load_dotenv()
app = FastAPI()
logger = logging.getLogger(__name__)

BUSINESS_CONFIG = {
    "name": "Diverse Hair Designs by Peachie",
    "booking_url": "https://diversehairdesigns.com/book",
    "hours": "Tuesday through Saturday, 9:00 AM to 6:00 PM",
    "services": "Silk Press ($75), Wash & Style ($55), Braids ($150+), Color & Highlights ($120+)",
    "location": "Fayetteville, NC",
}

chat_sessions: OrderedDict[str, list[dict[str, str]]] = OrderedDict()
handled_calls: OrderedDict[str, None] = OrderedDict()
blocked_numbers: set[str] = set()
PHONE = re.compile(r"\+[1-9][0-9]{7,14}")
STOP_WORDS = {"STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT", "REVOKE", "OPTOUT"}
START_WORDS = {"START", "UNSTOP", "YES"}


def setting(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise HTTPException(503, "Missing server configuration")
    return value


def xml(payload: VoiceResponse | MessagingResponse) -> Response:
    return Response(str(payload), media_type="application/xml")


async def verified_form(request: Request) -> FormData:
    base = setting("PUBLIC_BASE_URL").rstrip("/")
    url = base + request.url.path
    if request.url.query:
        url += "?" + request.url.query
    form = await request.form()
    signature = request.headers.get("X-Twilio-Signature", "")
    if not RequestValidator(setting("TWILIO_AUTH_TOKEN")).validate(url, form, signature):
        raise HTTPException(403, "Invalid Twilio signature")
    if form.get("To") != setting("TWILIO_PHONE_NUMBER"):
        raise HTTPException(400, "Unexpected destination")
    return form


def remember(caller: str, history: list[dict[str, str]]) -> None:
    chat_sessions[caller] = history[-6:]
    chat_sessions.move_to_end(caller)
    if len(chat_sessions) > 500:
        chat_sessions.popitem(last=False)


def send_text(caller: str, body: str) -> None:
    client = Client(
        setting("TWILIO_ACCOUNT_SID"),
        setting("TWILIO_AUTH_TOKEN"),
        http_client=TwilioHttpClient(timeout=3),
    )
    client.messages.create(body=body, from_=setting("TWILIO_PHONE_NUMBER"), to=caller)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/voice")
async def handle_missed_call(form: FormData = Depends(verified_form)):
    caller = str(form.get("From", ""))
    call_sid = str(form.get("CallSid", ""))
    business = BUSINESS_CONFIG
    initial_sms = (
        f"Hi, this is {business['name']}. We missed your call. "
        f"How can we help? Book here: {business['booking_url']} Reply STOP to opt out."
    )
    consent_numbers = {number.strip() for number in os.getenv("TEXTBACK_CONSENT_NUMBERS", "").split(",")}
    can_text = caller in consent_numbers
    text_queued = False
    if PHONE.fullmatch(caller) and call_sid and can_text and caller not in blocked_numbers:
        if call_sid not in handled_calls:
            handled_calls[call_sid] = None
            if len(handled_calls) > 2000:
                handled_calls.popitem(last=False)
            try:
                await run_in_threadpool(send_text, caller, initial_sms)
                remember(caller, [{"role": "assistant", "content": initial_sms}])
                text_queued = True
            except (TwilioException, RequestException) as error:
                logger.warning("Text-back request failed (%s)", type(error).__name__)
    response = VoiceResponse()
    greeting = f"Thanks for calling {business['name']}. We are unavailable right now."
    if text_queued:
        greeting += " We just sent you a text so we can help."
    else:
        greeting += " Please try calling again later."
    response.say(greeting, voice="Polly.Joanna")
    response.hangup()
    return xml(response)


@app.post("/sms")
async def handle_incoming_sms(form: FormData = Depends(verified_form)):
    caller = str(form.get("From", ""))
    body = str(form.get("Body", "")).strip()
    keyword = body.upper()
    opt_out_type = form.get("OptOutType")
    response = MessagingResponse()

    if not PHONE.fullmatch(caller):
        return xml(response)
    if opt_out_type == "STOP" or keyword in STOP_WORDS:
        blocked_numbers.add(caller)
        chat_sessions.pop(caller, None)
        return xml(response)
    if opt_out_type == "START" or keyword in START_WORDS:
        blocked_numbers.discard(caller)
        return xml(response)
    if opt_out_type or keyword in {"HELP", "INFO"} or not body or caller in blocked_numbers:
        return xml(response)

    business = BUSINESS_CONFIG
    instructions = (
        f"You are the SMS booking assistant for {business['name']} in {business['location']}. "
        f"Hours: {business['hours']}. Services and prices: {business['services']}. "
        f"Booking link: {business['booking_url']}. Use only these business facts. "
        "Never invent prices, discounts, availability, or confirm a booking. "
        "If unsure, ask the customer to call the salon. Use at most two short sentences."
    )
    history = [*chat_sessions.get(caller, []), {"role": "user", "content": body[:1600]}]
    reply = ""
    try:
        async with AsyncOpenAI(api_key=setting("OPENAI_API_KEY"), timeout=6, max_retries=0) as client:
            completion = await client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
                messages=[{"role": "system", "content": instructions}, *history[-6:]],
                max_completion_tokens=150,
                store=False,
            )
            reply = (completion.choices[0].message.content or "").strip()
    except OpenAIError as error:
        logger.warning("Booking reply request failed (%s)", type(error).__name__)
    if not reply:
        reply = f"Please call {business['name']} for help, or book here: {business['booking_url']}"
    if caller not in blocked_numbers:
        remember(caller, [*history, {"role": "assistant", "content": reply}])
        response.message(reply)
    return xml(response)

