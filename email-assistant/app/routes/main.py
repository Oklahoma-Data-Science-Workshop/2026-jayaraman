import os
import json
from flask import Blueprint, render_template, request
from app.models import Email, Sender, ActionItem, Tag
from app import db
from config import Config
from sqlalchemy import func, desc
from datetime import datetime, timedelta

OVERVIEW_PATH = os.path.join(str(Config.BASE_DIR), 'instance', 'digest_overview.json')

bp = Blueprint('main', __name__)

TOPIC_COLORS = {t['name']: t['color'] for t in Config.TOPICS}
VENDOR_COLORS = {v['name']: v['color'] for v in Config.VENDOR_CATEGORIES}
PRANK = {'high': 0, 'medium': 1, 'low': 2}


@bp.route('/')
def dashboard():
    now = datetime.utcnow()
    today = now.date()
    week_ahead = today + timedelta(days=7)

    # --- stat tiles ---
    needs_action = Email.query.filter_by(status='needs_action', is_archived=False).count()
    awaiting_reply = Email.query.filter_by(requires_response=True, is_archived=False).count()
    critical = Email.query.filter_by(urgency='critical', is_archived=False).count()
    unread = Email.query.filter_by(is_read=False, is_archived=False).count()
    open_tasks = ActionItem.query.filter(ActionItem.status != 'completed').count()
    high_tasks = ActionItem.query.filter(ActionItem.status != 'completed',
                                          ActionItem.priority == 'high').count()

    # --- deadlines (action items with a due date) ---
    all_dl = ActionItem.query.filter(ActionItem.due_date.isnot(None),
                                     ActionItem.status != 'completed') \
                             .order_by(ActionItem.due_date.asc()).all()
    overdue = sum(1 for a in all_dl if a.due_date < today)
    due_week = sum(1 for a in all_dl if today <= a.due_date <= week_ahead)
    deadlines = all_dl[:6]

    # --- topic bar graph ---
    rows = db.session.query(Email.topic, func.count(Email.id)) \
        .filter(Email.is_archived == False).group_by(Email.topic).all()
    topic_stats = sorted([((t or 'Other'), n) for t, n in rows], key=lambda x: x[1], reverse=True)
    topic_max = max([n for _, n in topic_stats], default=1)

    # --- vendor-category bar graph ---
    vrows = db.session.query(Email.vendor_category, func.count(Email.id)) \
        .filter(Email.is_archived == False).group_by(Email.vendor_category).all()
    vendor_stats = sorted([((v or 'Other'), n) for v, n in vrows], key=lambda x: x[1], reverse=True)
    vendor_max = max([n for _, n in vendor_stats], default=1)

    # --- triage: needs-action emails (fallback to urgent) ---
    triage = Email.query.filter(Email.status == 'needs_action', Email.is_archived == False) \
        .order_by(desc(Email.received_at)).limit(6).all()
    triage_fallback = False
    if not triage:
        triage = Email.query.filter(Email.urgency.in_(['critical', 'important']),
                                    Email.is_archived == False) \
            .order_by(desc(Email.received_at)).limit(6).all()
        triage_fallback = True

    # --- top action items (high priority first, then soonest due) ---
    tasks = ActionItem.query.join(Email) \
        .filter(Email.is_archived == False, ActionItem.status != 'completed').all()
    far = today + timedelta(days=3650)
    tasks.sort(key=lambda a: (PRANK.get(a.priority, 3), a.due_date or far))
    top_tasks = tasks[:6]

    # --- top senders ---
    top_senders = Sender.query.order_by(desc(Sender.email_count)).limit(6).all()
    sender_max = max([s.email_count for s in top_senders], default=1)

    return render_template('dashboard.html',
                           today=today,
                           needs_action=needs_action, awaiting_reply=awaiting_reply,
                           critical=critical, unread=unread,
                           open_tasks=open_tasks, high_tasks=high_tasks,
                           overdue=overdue, due_week=due_week, deadlines=deadlines,
                           topic_stats=topic_stats, topic_max=topic_max, topic_colors=TOPIC_COLORS,
                           vendor_stats=vendor_stats, vendor_max=vendor_max, vendor_colors=VENDOR_COLORS,
                           triage=triage, triage_fallback=triage_fallback,
                           top_tasks=top_tasks,
                           top_senders=top_senders, sender_max=sender_max)


def _registrable_domain(value):
    """Collapse subdomains to the registrable domain: pro.crexi.com -> crexi.com."""
    d = (value or '').strip().lower()
    if '@' in d:
        d = d.split('@')[-1]
    parts = [p for p in d.split('.') if p]
    return '.'.join(parts[-2:]) if len(parts) >= 2 else (d or 'unknown')


def _brand_from_domain(dom):
    label = (dom or 'unknown').split('.')[0]
    return (label[:1].upper() + label[1:]) if label else 'Unknown'


@bp.route('/digest')
def digest():
    """Vendor digest — grouped by vendor domain, from stored per-email summaries (no AI call)."""
    cutoff = datetime.utcnow() - timedelta(days=7)
    base_q = Email.query.filter(Email.is_archived == False)
    emails = base_q.filter(Email.received_at >= cutoff).order_by(desc(Email.received_at)).all()
    window_label = 'past 7 days'
    if not emails:
        emails = base_q.order_by(desc(Email.received_at)).limit(25).all()
        window_label = 'recent'

    groups = {}
    for e in emails:
        dom = _registrable_domain(e.sender_domain or e.sender_email or '')
        g = groups.get(dom)
        if not g:
            g = {'domain': dom, 'brand': _brand_from_domain(dom), 'senders': set(), 'emails': []}
            groups[dom] = g
        nm = (e.sender_name or e.sender_email or '').strip()
        if nm:
            g['senders'].add(nm)
        g['emails'].append(e)

    vendors = []
    for g in sorted(groups.values(), key=lambda grp: len(grp['emails']), reverse=True):
        g['sender_count'] = len(g['senders'])
        vendors.append(g)

    overview = overview_at = None
    try:
        if os.path.exists(OVERVIEW_PATH):
            with open(OVERVIEW_PATH) as f:
                saved = json.load(f)
            overview = saved.get('text')
            overview_at = saved.get('generated_at')
    except Exception:
        pass

    return render_template('digest.html',
                           vendors=vendors,
                           total=len(emails),
                           vendor_count=len(vendors),
                           window_label=window_label,
                           overview=overview, overview_at=overview_at)


@bp.route('/digest/overview', methods=['POST'])
def digest_overview():
    """Approach B: one Haiku call to synthesize the week's vendor activity into a paragraph."""
    cutoff = datetime.utcnow() - timedelta(days=7)
    base_q = Email.query.filter(Email.is_archived == False)
    emails = base_q.filter(Email.received_at >= cutoff).order_by(desc(Email.received_at)).all()
    if not emails:
        emails = base_q.order_by(desc(Email.received_at)).limit(25).all()

    lines = []
    for e in emails[:40]:
        s = (e.summary or e.subject or '').strip().replace('\n', ' ')
        if s:
            lines.append('- %s: %s' % (e.sender_name or e.sender_email or 'Vendor', s))
    if not lines:
        return {'ok': False, 'error': 'No vendor emails to summarize.'}, 400

    prompt = (
        "You are summarizing a week of vendor emails for a busy program administrator. "
        "Write a 2-3 sentence executive overview of what vendors are updating this week, grouped by theme. "
        "Awareness only; do not invent action items or urgency. Plain prose, no markdown, no bullet points.\n\n"
        "Vendor emails:\n" + '\n'.join(lines)
    )
    try:
        import urllib.request
        req = urllib.request.Request(
            'https://api.anthropic.com/v1/messages',
            data=json.dumps({
                'model': Config.CLAUDE_MODEL,
                'max_tokens': 300,
                'messages': [{'role': 'user', 'content': prompt}],
            }).encode('utf-8'),
            method='POST',
            headers={
                'x-api-key': Config.ANTHROPIC_API_KEY,
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json',
            })
        with urllib.request.urlopen(req, timeout=40) as r:
            payload = json.loads(r.read().decode('utf-8'))
        text = ''.join(b.get('text', '') for b in payload.get('content', [])
                       if b.get('type') == 'text').strip()
        if not text:
            return {'ok': False, 'error': 'Empty response from model.'}, 502
    except Exception as ex:
        return {'ok': False, 'error': str(ex)[:200]}, 500

    generated_at = datetime.utcnow().strftime('%b %d, %H:%M UTC')
    try:
        with open(OVERVIEW_PATH, 'w') as f:
            json.dump({'text': text, 'generated_at': generated_at}, f)
    except Exception:
        pass
    return {'ok': True, 'text': text, 'generated_at': generated_at}


@bp.route('/tasks')
def tasks():
    """Action-items checklist — grouped by priority, with mark-done."""
    show_all = request.args.get('show') == 'all'
    today = datetime.utcnow().date()
    far = today + timedelta(days=3650)

    open_items = ActionItem.query.join(Email) \
        .filter(Email.is_archived == False, ActionItem.status != 'completed').all()
    open_items.sort(key=lambda a: (PRANK.get(a.priority, 3), a.due_date or far))

    buckets = {'high': [], 'medium': [], 'low': []}
    for a in open_items:
        buckets[a.priority if a.priority in buckets else 'low'].append(a)

    done = []
    if show_all:
        done = ActionItem.query.join(Email) \
            .filter(Email.is_archived == False, ActionItem.status == 'completed') \
            .order_by(ActionItem.completed_at.desc()).all()

    counts = {'open': len(open_items), 'high': len(buckets['high'])}
    return render_template('tasks.html', buckets=buckets, done=done,
                           counts=counts, today=today, show_all=show_all)


@bp.route('/tasks/<int:id>/toggle', methods=['POST'])
def task_toggle(id):
    a = ActionItem.query.get_or_404(id)
    if a.status == 'completed':
        a.status = 'pending'
        a.completed_at = None
    else:
        a.status = 'completed'
        a.completed_at = datetime.utcnow()
    db.session.commit()
    return {'ok': True, 'completed': a.status == 'completed'}


@bp.route('/triage')
def triage():
    """Urgency-grouped queue of what needs attention."""
    base_q = Email.query.filter(Email.is_archived == False)
    critical = base_q.filter(Email.urgency == 'critical').order_by(desc(Email.received_at)).all()
    important = base_q.filter(Email.urgency == 'important').order_by(desc(Email.received_at)).all()
    seen = {e.id for e in critical} | {e.id for e in important}
    needs_reply = [e for e in base_q.filter(Email.requires_response == True)
                   .order_by(desc(Email.received_at)).all() if e.id not in seen]
    seen |= {e.id for e in needs_reply}
    rest = base_q.count() - len(seen)
    groups = [g for g in [
        ('critical', 'Critical', '#ef4444', critical),
        ('important', 'Important', '#f59e0b', important),
        ('reply', 'Needs a reply', '#3b82f6', needs_reply),
    ] if g[3]]
    return render_template('triage.html', groups=groups, rest=rest,
                           topic_colors=TOPIC_COLORS, vendor_colors=VENDOR_COLORS)


@bp.route('/triage/<int:id>/archive', methods=['POST'])
def triage_archive(id):
    e = Email.query.get_or_404(id)
    e.is_archived = True
    db.session.commit()
    return {'ok': True}


@bp.route('/senders')
def senders():
    rows = Sender.query.order_by(Sender.is_vip.desc(), desc(Sender.email_count)).all()
    max_vol = max([s.email_count for s in rows], default=1)
    return render_template('senders.html', senders=rows, max_vol=max_vol)


@bp.route('/senders/<int:id>/vip', methods=['POST'])
def sender_vip(id):
    s = Sender.query.get_or_404(id)
    s.is_vip = not bool(s.is_vip)
    db.session.commit()
    return {'ok': True, 'vip': s.is_vip}
