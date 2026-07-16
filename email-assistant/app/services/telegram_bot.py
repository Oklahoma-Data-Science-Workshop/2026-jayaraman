import os
import asyncio
from telegram import Bot
from telegram.error import TelegramError
from config import Config

config = Config()
bot_token = config.TELEGRAM_BOT_TOKEN
chat_id = config.TELEGRAM_CHAT_ID

def send_notification(email):
    """Send Telegram notification for important emails"""
    if not bot_token or not chat_id:
        print("Telegram not configured")
        return False
    
    try:
        # Run async function in event loop
        return asyncio.run(_send_async(email))
    except Exception as e:
        print(f"Notification error: {e}")
        return False

async def _send_async(email):
    """Send Telegram notification for important emails"""
    if not bot_token or not chat_id:
        print("Telegram not configured")
        return False
    
    try:
        bot = Bot(token=bot_token)
        
        # Format message
        urgency_emoji = {
            'critical': '🔴',
            'important': '🟠',
            'normal': '🟢',
            'low': '⚪'
        }
        
        emoji = urgency_emoji.get(email.urgency, '📧')
        
        message = f"""{emoji} <b>{email.urgency.upper()} EMAIL</b>

<b>From:</b> {email.sender_name or email.sender_email}
<b>Subject:</b> {email.subject}

<b>📝 Summary:</b>
{email.summary or 'No summary available'}
"""
        
        # Add action items if any
        if email.action_items_list:
            message += "\n<b>✅ Actions:</b>\n"
            for action in email.action_items_list[:3]:  # Max 3
                message += f"• {action.get('description', 'N/A')}\n"
        
        message += f"\n<a href='http://localhost:5000/emails/{email.id}'>View Full Email</a>"
        
        # Send message
        bot_message = await bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode='HTML'
        )
        
        # Update email with telegram message ID
        email.telegram_message_id = str(bot_message.message_id)
        
        return True
        
    except TelegramError as e:
        print(f"Telegram error: {e}")
        return False
    except Exception as e:
        print(f"Notification error: {e}")
        return False
