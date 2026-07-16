import anthropic
from config import Config
import json

config = Config()

CLASSIFICATION_PROMPT = """Analyze this email and return a JSON object with classification:

{
  "topic": "Vendor|Collaborator|Administration|IT|HR|Committee|Student|Finance|Other",
  "urgency": "critical|important|normal|low",
  "sentiment": "positive|negative|neutral|urgent",
  "email_type": "request|fyi|decision|meeting|deadline|reply",
  "status": "needs_action|inbox|reference",
  
  "summary": "2-3 sentence summary",
  "key_points": ["point 1", "point 2", "point 3"],
  
  "action_items": [
    {
      "type": "meeting|deadline|task|request|decision",
      "description": "what needs to be done",
      "due_date": "YYYY-MM-DD or null",
      "priority": "high|medium|low"
    }
  ],
  
  "is_vip": false,
  "requires_response": false
}

Guidelines:
- topic: Categorize based on sender and content
- urgency: critical (needs immediate action), important (needs action this week), normal, low
- status: needs_action (requires response/decision), inbox (FYI), reference (keep for later)
- Extract specific action items with due dates if mentioned
- Detect VIP senders (bosses, key collaborators)

Email:
From: {sender}
Subject: {subject}
Body: {body}
"""

def classify_email(sender, subject, body):
    """Use Claude to classify and extract metadata from email"""
    try:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        
        prompt = CLASSIFICATION_PROMPT.format(
            sender=sender,
            subject=subject,
            body=body[:3000]  # Limit body length
        )
        
        response = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}]
        )
        
        # Extract JSON from response
        text = response.content[0].text
        
        # Try to find JSON in the response
        start = text.find('{')
        end = text.rfind('}') + 1
        if start >= 0 and end > start:
            json_str = text[start:end]
            result = json.loads(json_str)
            return result
        else:
            raise ValueError("No JSON found in response")
            
    except Exception as e:
        print(f"Classification error: {e}")
        # Return default classification
        return {
            "topic": "Other",
            "urgency": "normal",
            "sentiment": "neutral",
            "email_type": "fyi",
            "status": "inbox",
            "summary": subject,
            "key_points": [],
            "action_items": [],
            "is_vip": False,
            "requires_response": False
        }
