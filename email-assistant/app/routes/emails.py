from flask import Blueprint, render_template, request, redirect, url_for, flash
from app.models import Email
from app import db
from sqlalchemy import desc

bp = Blueprint('emails', __name__, url_prefix='/emails')

@bp.route('/')
def list():
    page = request.args.get('page', 1, type=int)
    topic = request.args.get('topic')
    urgency = request.args.get('urgency')
    status = request.args.get('status')
    
    query = Email.query.filter_by(is_archived=False)
    
    if topic:
        query = query.filter_by(topic=topic)
    if urgency:
        query = query.filter_by(urgency=urgency)
    if status:
        query = query.filter_by(status=status)
    
    emails = query.order_by(desc(Email.received_at)).paginate(
        page=page, per_page=25, error_out=False
    )
    
    return render_template('emails/list.html', emails=emails, 
                         topic=topic, urgency=urgency, status=status)

@bp.route('/<int:id>')
def detail(id):
    email = Email.query.get_or_404(id)
    
    # Mark as read
    if not email.is_read:
        email.is_read = True
        db.session.commit()
    
    return render_template('emails/detail.html', email=email)

@bp.route('/<int:id>/archive', methods=['POST'])
def archive(id):
    email = Email.query.get_or_404(id)
    email.is_archived = True
    db.session.commit()
    flash('Email archived', 'success')
    return redirect(url_for('emails.list'))

@bp.route('/<int:id>/mark-read', methods=['POST'])
def mark_read(id):
    email = Email.query.get_or_404(id)
    email.is_read = True
    db.session.commit()
    return redirect(url_for('emails.detail', id=id))
