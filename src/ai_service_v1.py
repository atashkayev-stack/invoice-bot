"""
ai_service_v1.py
Claude AI для распознавания документов
"""
from typing import Dict
import os
import base64
import json
import logging
import anthropic

logger = logging.getLogger(__name__)


class AIService:

    def __init__(self):
        api_key = os.getenv("ANTHROPIC_API_KEY")
        self.client = anthropic.Anthropic(api_key=api_key)

    def extract_client_data(self,
                            image_bytes: bytes,
                            media_type: str = "image/jpeg") -> dict:
        try:
            img_b64 = base64.b64encode(image_bytes).decode('utf-8')

            response = self.client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=1024,
                messages=[{
                    "role":
                    "user",
                    "content": [{
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": img_b64
                        }
                    }, {
                        "type":
                        "text",
                        "text":
                        """Analysiere dieses Dokument und extrahiere Kundendaten.

Antworte NUR im JSON Format (ohne Markdown):
{
  "company_name": "...",
  "street": "...",
  "postal_code": "...",
  "city": "...",
  "country": "Deutschland",
  "email": "...",
  "phone": "...",
  "tax_id": "...",
  "vat_id": "...",
  "customer_id": "...",
  "confidence": "hoch/mittel/niedrig"
}

Falls Feld nicht erkennbar: null setzen."""
                    }]
                }])

            ai_text = response.content[0].text.replace('```json',
                                                       '').replace('```',
                                                                   '').strip()

            try:
                return json.loads(ai_text)
            except:
                import re
                json_match = re.search(r'\{.*\}', ai_text, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group())
                return None

        except Exception as e:
            logger.error(f"AI extraction error: {e}")
            return None

    def format_address(self, data: Dict) -> str:
        parts = []
        if data.get('street'):
            parts.append(data['street'])
        if data.get('postal_code') and data.get('city'):
            parts.append(f"{data['postal_code']} {data['city']}")
        if data.get('country'):
            parts.append(data['country'])
        return ", ".join(filter(None, parts))
