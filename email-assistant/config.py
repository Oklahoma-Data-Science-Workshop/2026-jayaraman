import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
load_dotenv()

class Config:
    # Flask
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    BASE_DIR = Path(__file__).parent
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{BASE_DIR}/instance/emails.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Gmail
    GMAIL_CREDENTIALS_FILE = os.environ.get('GMAIL_CREDENTIALS_FILE', '~/.gmail-credentials.json')

    # Claude/Anthropic
    ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
    CLAUDE_MODEL = 'claude-haiku-4-5-20251001'

    # Telegram
    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')

    # Nextcloud
    NEXTCLOUD_URL = os.environ.get('NEXTCLOUD_URL', 'https://your-nextcloud.example.com/nextcloud')
    NEXTCLOUD_USERNAME = os.environ.get('NEXTCLOUD_USERNAME', 'your-username')
    NEXTCLOUD_PASSWORD = os.environ.get('NEXTCLOUD_PASSWORD', '')
    NEXTCLOUD_BASE_FOLDER = '/Email_Assistant/'
    NEXTCLOUD_CALENDAR_NAME = 'Email_Events'

    # Computed Nextcloud URLs
    @property
    def NEXTCLOUD_WEBDAV_URL(self):
        return f'{self.NEXTCLOUD_URL}/remote.php/dav/files/{self.NEXTCLOUD_USERNAME}/'

    @property
    def NEXTCLOUD_CALDAV_URL(self):
        return f'{self.NEXTCLOUD_URL}/remote.php/dav/calendars/{self.NEXTCLOUD_USERNAME}/'

    # Email Classification
    EXTERNAL_PATTERN = r'\[EXTERNAL\]'
    VIP_SENDERS = []  # Will be populated from database

    # Topics — the PURPOSE of a vendor-digest email
    TOPICS = [
        {'name': 'Opportunity',  'color': '#10b981', 'icon': '💡'},
        {'name': 'Promotion',    'color': '#ec4899', 'icon': '🏷️'},
        {'name': 'Newsletter',   'color': '#3b82f6', 'icon': '📰'},
        {'name': 'Account',      'color': '#ef4444', 'icon': '💳'},
        {'name': 'Announcement', 'color': '#f59e0b', 'icon': '📣'},
        {'name': 'Event',        'color': '#8b5cf6', 'icon': '📅'},
        {'name': 'Other',        'color': '#6b7280', 'icon': '📧'},
    ]

    # Vendor categories — the INDUSTRY / type of vendor
    VENDOR_CATEGORIES = [
        {'name': 'Lab Supplies & Equipment', 'color': '#14b8a6'},
        {'name': 'Research Services',        'color': '#8b5cf6'},
        {'name': 'Scientific & Academic',    'color': '#3b82f6'},
        {'name': 'Healthcare & Benefits',    'color': '#f43f5e'},
        {'name': 'Software & IT',            'color': '#06b6d4'},
        {'name': 'Finance & Procurement',    'color': '#22c55e'},
        {'name': 'Other',                    'color': '#6b7280'},
    ]

    # Notification Settings
    CRITICAL_KEYWORDS = ['urgent', 'asap', 'immediately', 'critical', 'deadline', 'approval needed']
    NOTIFICATION_BATCH_INTERVAL = 60  # minutes

    # Pagination
    EMAILS_PER_PAGE = 25
