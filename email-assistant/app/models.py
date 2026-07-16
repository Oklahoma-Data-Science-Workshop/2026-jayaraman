from datetime import datetime
from app import db
import json

class Email(db.Model):
    __tablename__ = 'emails'
    
    id = db.Column(db.Integer, primary_key=True)
    gmail_id = db.Column(db.String(100), unique=True, nullable=False, index=True)
    thread_id = db.Column(db.String(100), index=True)
    
    # Sender/Recipient
    sender_email = db.Column(db.String(200), index=True)
    sender_name = db.Column(db.String(200))
    sender_domain = db.Column(db.String(100), index=True)
    recipient = db.Column(db.String(200))
    
    # Content
    subject = db.Column(db.Text)
    body_text = db.Column(db.Text)
    snippet = db.Column(db.String(500))
    
    # Dates
    received_at = db.Column(db.DateTime, index=True)
    
    # Attachments
    has_attachments = db.Column(db.Boolean, default=False)
    attachment_count = db.Column(db.Integer, default=0)
    nextcloud_folder_path = db.Column(db.String(500))
    
    # Classification
    topic = db.Column(db.String(50), index=True, default='Other')
    vendor_category = db.Column(db.String(50), index=True, default='Other')
    urgency = db.Column(db.String(20), index=True, default='normal')
    sentiment = db.Column(db.String(20))
    email_type = db.Column(db.String(50))
    
    # Status
    status = db.Column(db.String(50), default='inbox', index=True)
    is_read = db.Column(db.Boolean, default=False, index=True)
    is_archived = db.Column(db.Boolean, default=False)
    
    # AI-generated content
    summary = db.Column(db.Text)
    key_points = db.Column(db.Text)  # JSON array
    action_items_json = db.Column(db.Text)  # JSON array
    
    # Integration IDs
    telegram_message_id = db.Column(db.String(100))
    
    # Metadata
    is_vip_sender = db.Column(db.Boolean, default=False, index=True)
    requires_response = db.Column(db.Boolean, default=False)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    attachments = db.relationship('Attachment', backref='email', lazy='dynamic', cascade='all, delete-orphan')
    action_items = db.relationship('ActionItem', backref='email', lazy='dynamic', cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'id': self.id,
            'gmail_id': self.gmail_id,
            'sender_email': self.sender_email,
            'sender_name': self.sender_name,
            'subject': self.subject,
            'received_at': self.received_at.isoformat() if self.received_at else None,
            'topic': self.topic,
            'urgency': self.urgency,
            'status': self.status,
            'is_read': self.is_read,
            'summary': self.summary,
        }
    
    @property
    def key_points_list(self):
        if self.key_points:
            try:
                return json.loads(self.key_points)
            except:
                return []
        return []
    
    @property
    def action_items_list(self):
        if self.action_items_json:
            try:
                return json.loads(self.action_items_json)
            except:
                return []
        return []


class Sender(db.Model):
    __tablename__ = 'senders'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(200), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200))
    domain = db.Column(db.String(100), index=True)
    
    is_vip = db.Column(db.Boolean, default=False, index=True)
    email_count = db.Column(db.Integer, default=0)
    first_seen = db.Column(db.DateTime)
    last_seen = db.Column(db.DateTime)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Attachment(db.Model):
    __tablename__ = 'attachments'
    
    id = db.Column(db.Integer, primary_key=True)
    email_id = db.Column(db.Integer, db.ForeignKey('emails.id'), nullable=False)
    
    filename = db.Column(db.String(500))
    size = db.Column(db.Integer)
    mime_type = db.Column(db.String(100))
    
    nextcloud_path = db.Column(db.String(500))
    nextcloud_share_link = db.Column(db.String(500))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ActionItem(db.Model):
    __tablename__ = 'action_items'
    
    id = db.Column(db.Integer, primary_key=True)
    email_id = db.Column(db.Integer, db.ForeignKey('emails.id'), nullable=False)
    
    type = db.Column(db.String(50))  # meeting, deadline, task, request, decision
    description = db.Column(db.Text)
    due_date = db.Column(db.Date, index=True)
    priority = db.Column(db.String(20))
    status = db.Column(db.String(50), default='pending', index=True)
    
    completed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Tag(db.Model):
    __tablename__ = 'tags'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    category = db.Column(db.String(50))
    color = db.Column(db.String(20))
    icon = db.Column(db.String(10))
    email_count = db.Column(db.Integer, default=0)
