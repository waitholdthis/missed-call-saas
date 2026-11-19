import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from xml.etree import ElementTree

from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

import main


class WebhookTest(unittest.TestCase):
    caller = "+19105550101"
    business = "+19105550199"
    token = "smoke-test-token"
    public_url = "https://test.example"

    def test_voice_sms_and_stop(self):
        settings = {
            "TWILIO_AUTH_TOKEN": self.token,
            "TWILIO_PHONE_NUMBER": self.business,
            "PUBLIC_BASE_URL": self.public_url,
            "TEXTBACK_CONSENT_NUMBERS": self.caller,
            "OPENAI_API_KEY": "test-key",
        }
        with patch.dict(os.environ, settings), patch.object(main, "send_text") as send:
            with TestClient(main.app) as client:
                voice = {"From": self.caller, "To": self.business, "CallSid": "CA-test"}
                self.assertEqual(client.post("/voice", data=voice).status_code, 403)
                self.assertEqual(client.get("/health").json(), {"status": "ok"})
                response = self.post(client, "/voice", voice)
                self.assertIn("sent you a text", response.findtext("Say"))
                self.assertIsNotNone(response.find("Hangup"))
                self.post(client, "/voice", voice)
                send.assert_called_once()
                self.assertEqual(send.call_args.args[0], self.caller)

                with patch.object(main, "AsyncOpenAI") as openai:
                    api = openai.return_value.__aenter__.return_value
                    api.chat.completions.create = AsyncMock(return_value=SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(content="A Silk Press is $75."))]
                    ))
                    sms = {"From": self.caller, "To": self.business, "Body": "How much is a silk press?"}
                    self.assertEqual(self.post(client, "/sms", sms).findtext("Message/Body"),
                                     "A Silk Press is $75.")
                    api.chat.completions.create.assert_awaited_once()
                    self.assertIsNone(self.post(client, "/sms", {**sms, "Body": "STOP"}).find("Message"))
                    self.post(client, "/voice", {**voice, "CallSid": "CA-after-stop"})
                    send.assert_called_once()

    def post(self, client, path, data):
        signature = RequestValidator(self.token).compute_signature(self.public_url + path, data)
        response = client.post(path, data=data, headers={"X-Twilio-Signature": signature})
        self.assertEqual(response.status_code, 200, response.text)
        return ElementTree.fromstring(response.content)


if __name__ == "__main__":
    unittest.main()
