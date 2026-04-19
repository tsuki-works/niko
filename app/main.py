from fastapi import FastAPI, Response
from twilio.twiml.voice_response import VoiceResponse

app = FastAPI(title="niko")


@app.get("/")
def root():
    return {"service": "niko", "status": "ok"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/voice")
def voice():
    """Twilio Voice webhook — POC scaffold.

    Returns a canned TwiML greeting so Kailash can wire the Twilio number
    to this URL and prove the webhook round-trip. Replaced with Media
    Streams + STT/LLM/TTS integration as the pipeline comes online.
    """
    twiml = VoiceResponse()
    twiml.say(
        "Hello, thanks for calling niko. The voice agent is coming soon.",
        voice="alice",
    )
    return Response(content=str(twiml), media_type="application/xml")
