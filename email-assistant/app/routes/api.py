from flask import Blueprint, request, jsonify
from app.models import Email, Sender, Attachment, ActionItem
from app import db
from config import Config
from app.services.nextcloud import NextcloudClient
from app.services.telegram_bot import send_notification
from datetime import datetime
from sqlalchemy.exc import IntegrityError
import json

bp = Blueprint('api', __name__, url_prefix='/api')

@bp.route('/emails/ingest', methods=['POST'])
def ingest_email():
    """
    Receive email data from n8n workflow
    Expected JSON:
    {
        "gmail_id": "...",
        "thread_id": "...",
        "sender": {"email": "...", "name": "..."},
        "subject": "...",
        "body_text": "...",
        "snippet": "...",
        "received_at": "2026-07-12T10:30:00Z",
        "attachments": [...],
        "classification": {
            "topic": "Vendor",
            "urgency": "important",
            "sentiment": "neutral",
            "email_type": "request",
            "status": "needs_action",
            "summary": "...",
            "key_points": [...],
            "action_items": [...],
            "requires_response": true,
            "is_vip": false
        }
    }
    """
    try:
        data = request.json
        
        # Check if email already exists
        existing = Email.query.filter_by(gmail_id=data['gmail_id']).first()
        if existing:
            return jsonify({'status': 'duplicate', 'email_id': existing.id}), 200
        
        # Parse sender
        sender_email = data['sender']['email']
        sender_name = data['sender'].get('name', '')
        sender_domain = sender_email.split('@')[1] if '@' in sender_email else ''

        # Forwarded vendor emails carry the forwarder (the user) in Gmail's "From".
        # If Claude extracted the real vendor from the body, use it as the sender
        # identity so digest grouping and Top Senders reflect the vendor, not the user.
        _cls = data.get('classification', {})
        _vname = (_cls.get('vendor_name') or '').strip()
        _vdom = (_cls.get('vendor_domain') or '').strip().lower().lstrip('@')
        if _vdom and '.' in _vdom:
            sender_domain = _vdom
            sender_email = 'mail@' + _vdom          # synthetic, uniform per vendor domain
            if _vname:
                sender_name = _vname
        
        # Get-or-create sender, race-safe on the senders.email UNIQUE constraint.
        # n8n POSTs a batch concurrently; two emails from the same vendor used to
        # both pass the existence check and collide on INSERT (500 the whole run).
        sender = Sender.query.filter_by(email=sender_email).first()
        if sender is None:
            try:
                with db.session.begin_nested():
                    sender = Sender(
                        email=sender_email,
                        name=sender_name,
                        domain=sender_domain,
                        email_count=1,
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow()
                    )
                    db.session.add(sender)
            except IntegrityError:
                # a concurrent request created it first; re-fetch and bump
                sender = Sender.query.filter_by(email=sender_email).first()
                if sender is not None:
                    sender.email_count += 1
                    sender.last_seen = datetime.utcnow()
        else:
            sender.email_count += 1
            sender.last_seen = datetime.utcnow()
            if sender_name and not sender.name:
                sender.name = sender_name
        
        # Create email record
        classification = data.get('classification', {})

        # Enum safety net: keep the two taxonomy dimensions from cross-
        # contaminating (e.g. a vendor_category value landing in topic).
        _valid_topics = {t['name'] for t in Config.TOPICS}
        _valid_vcats = {v['name'] for v in Config.VENDOR_CATEGORIES}
        _topic = classification.get('topic', 'Other')
        if _topic not in _valid_topics:
            _topic = 'Other'
        _vcat = classification.get('vendor_category', 'Other')
        if _vcat not in _valid_vcats:
            _vcat = 'Other'
        
        email = Email(
            gmail_id=data['gmail_id'],
            thread_id=data.get('thread_id'),
            sender_email=sender_email,
            sender_name=sender_name,
            sender_domain=sender_domain,
            recipient=data.get('recipient'),
            subject=data.get('subject'),
            body_text=data.get('body_text'),
            snippet=data.get('snippet'),
            received_at=datetime.fromisoformat(data['received_at'].replace('Z', '+00:00')),
            has_attachments=len(data.get('attachments', [])) > 0,
            attachment_count=len(data.get('attachments', [])),
            topic=_topic,
            vendor_category=_vcat,
            urgency=classification.get('urgency', 'normal'),
            sentiment=classification.get('sentiment'),
            email_type=classification.get('email_type'),
            status=classification.get('status', 'inbox'),
            summary=classification.get('summary'),
            key_points=json.dumps(classification.get('key_points', [])),
            action_items_json=json.dumps(classification.get('action_items', [])),
            requires_response=classification.get('requires_response', False),
            is_vip_sender=classification.get('is_vip', False)
        )
        
        db.session.add(email)
        db.session.flush()  # Get email.id
        
        # Handle attachments
        if data.get('attachments'):
            nc_client = NextcloudClient()
            for att_data in data['attachments']:
                attachment = Attachment(
                    email_id=email.id,
                    filename=att_data['filename'],
                    size=att_data.get('size'),
                    mime_type=att_data.get('mime_type')
                )
                
                # Upload to Nextcloud if file data provided
                if att_data.get('file_data'):
                    try:
                        nc_path = nc_client.upload_attachment(
                            email.id,
                            email.topic,
                            sender_email,
                            email.received_at,
                            att_data['file_data'],
                            att_data['filename']
                        )
                        attachment.nextcloud_path = nc_path
                        
                        # Create share link
                        share_link = nc_client.create_share_link(nc_path)
                        attachment.nextcloud_share_link = share_link
                    except Exception as e:
                        print(f"Nextcloud upload failed: {e}")
                
                db.session.add(attachment)
        
        # Create action items
        for action_data in classification.get('action_items', []):
            raw_due = action_data.get('due_date')
            due_date = None
            if raw_due:
                try:
                    due_date = datetime.fromisoformat(str(raw_due).replace('Z', '+00:00')).date()
                except (ValueError, TypeError):
                    due_date = None
            action = ActionItem(
                email_id=email.id,
                type=action_data.get('type', 'task'),
                description=action_data.get('description', ''),
                due_date=due_date,
                priority=action_data.get('priority', 'medium')
            )
            db.session.add(action)
        
        db.session.commit()
        
        # Send Telegram notification if urgent
        if email.urgency in ['critical', 'important']:
            try:
                send_notification(email)
            except Exception as e:
                print(f"Telegram notification failed: {e}")
        
        return jsonify({
            'status': 'success',
            'email_id': email.id,
            'topic': email.topic,
            'urgency': email.urgency
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bp.route('/emails/exists', methods=['POST'])
def emails_exist():
    """Return which gmail_ids are already stored, so n8n can skip re-classifying them."""
    data = request.get_json(silent=True) or {}
    ids = data.get('ids') or []
    if not ids:
        return jsonify({'existing': []})
    rows = Email.query.with_entities(Email.gmail_id).filter(Email.gmail_id.in_(ids)).all()
    return jsonify({'existing': [r[0] for r in rows]})
