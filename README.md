# Missed Call Text Back

A single salon prototype for Diverse Hair Designs by Peachie. A forwarded call triggers a text to a caller who has opted in, then plays a short greeting and ends. SMS replies go to an AI booking assistant using the salon profile in main.py. Confirm the sample prices, hours, and booking URL before testing with customers.

## Run locally

Windows PowerShell, from the project folder

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m unittest -v
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Linux or a Hostinger VPS, from the project folder

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python -m unittest -v
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Create .env only if it does not already exist. The test uses signed synthetic webhooks and mocks both providers.

## Connect Twilio

1. In .env, enter the Twilio Account SID, Auth Token, a number with voice and messaging, and an OpenAI API key. Add the consenting test caller to TEXTBACK_CONSENT_NUMBERS in international format (for example, +19105550101). Additional opted-in numbers can be comma separated.
2. Run `ngrok http 8000` or proxy HTTPS to local port 8000 using Nginx. Set PUBLIC_BASE_URL to the exact external HTTPS origin, such as https://api.example.com. Restart after changing .env. Confirm GET /health returns an OK status.
3. In the Twilio number settings, set the incoming voice and messaging webhooks to POST /voice and POST /sms on that HTTPS origin. Use a registered sender as applicable and confirm Twilio opt out handling is enabled for the sender.
4. Call the Twilio number directly from your test phone first. Check that the greeting plays, the text arrives, and replying with a price or hours question produces a useful answer. Reply STOP, then call again to check suppression.
5. For T-Mobile no-answer forwarding, dial `**61*1NPANXXXXXX#`, replacing the number with your actual Twilio number. Call the salon's regular number from the opted-in test phone and let it ring out. Check that the caller ID reaches Twilio and measure delivery from the time the call forwards. Dial `##61#` to disable no-answer forwarding.

The app validates Twilio signatures against PUBLIC_BASE_URL and checks the destination number. Use one worker for this prototype. Conversation history, call retry tracking, and local opt-out state reset on restart. Keep the provider's opt-out controls active and maintain the consent list before use. The voice greeting does not record a message. OpenAI receives the SMS text and recent conversation context. PostgreSQL and Stripe are outside this prototype.

References

- [Twilio webhook security](https://www.twilio.com/docs/usage/webhooks/webhooks-security)
- [Twilio messaging policy](https://www.twilio.com/en-us/legal/messaging-policy)
- [Twilio US local number registration](https://www.twilio.com/docs/messaging/compliance/a2p-10dlc)
- [T-Mobile call forwarding codes](https://www.t-mobile.com/support/plans-features/self-service-short-codes)
