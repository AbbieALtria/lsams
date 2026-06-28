import os
import json
import pandas as pd
from datetime import datetime, date
from flask import Flask, render_template, redirect, url_for, request, flash, jsonify, send_file
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from sqlalchemy import func, and_, or_, extract, text
import io

from config import Config
from models import db, User, Lead, Visit, Registration, LeadAssignmentHistory, Notification, GabayTarget, StrictBuilding, Campaign, CampaignPriorityLog, LeadIntelligence, Presentation, Brand, ScoutLog

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access LSAMS.'
login_manager.login_message_category = 'warning'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('instance', exist_ok=True)

# ── Timezone: all DB timestamps are UTC; display in Philippine Time (UTC+8) ──
from datetime import timezone, timedelta as _td
_PHT = timezone(_td(hours=8))

_SHOPEE_ALIASES = {'shopee': 'Coffee', 'SHOPEE': 'COFFEE', 'Shopee': 'Coffee'}
def _mask_shopee(text):
    if not text:
        return text
    for k, v in _SHOPEE_ALIASES.items():
        text = text.replace(k, v)
    return text

@app.template_filter('safe_brand')
def safe_brand_filter(value):
    """Replace Shopee with Coffee in any displayed text."""
    return _mask_shopee(str(value)) if value else value

@app.context_processor
def inject_safe_brand():
    return dict(safe_brand=_mask_shopee)

@app.template_filter('pht')
def to_pht(dt, fmt='%b %d, %Y %I:%M %p'):
    if dt is None:
        return '—'
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_PHT).strftime(fmt)

@app.template_filter('pht_date')
def to_pht_date(dt, fmt='%b %d, %Y'):
    return to_pht(dt, fmt)

@app.template_filter('pht_time')
def to_pht_time(dt, fmt='%I:%M %p'):
    return to_pht(dt, fmt)

with app.app_context():
    db.create_all()
    # Add new User columns if they don't exist (safe for existing Railway DB)
    _new_user_cols = [
        ("whatsapp_alerts_enabled", "BOOLEAN DEFAULT TRUE"),
        ("telegram_chat_id", "VARCHAR(30)"),
        ("mobile",         "VARCHAR(20)"),
        ("mobile2",        "VARCHAR(20)"),
        ("viber",          "VARCHAR(20)"),
        ("facebook",       "VARCHAR(200)"),
        ("house_number",   "VARCHAR(50)"),
        ("street",         "VARCHAR(200)"),
        ("barangay",       "VARCHAR(100)"),
        ("city_address",   "VARCHAR(100)"),
        ("profile_photo",  "VARCHAR(200)"),
        ("deactivated_at", "TIMESTAMP"),
        ("gabay_name",     "VARCHAR(100)"),
        ("last_seen",      "TIMESTAMP"),
    ]
    with db.engine.connect() as _conn:
        for _col, _type in _new_user_cols:
            try:
                _conn.execute(text(
                    f"ALTER TABLE users ADD COLUMN {_col} {_type}"
                ))
                _conn.commit()
            except Exception:
                _conn.rollback()

    # Add photo_pending column to visits
    with db.engine.connect() as _conn:
        try:
            _conn.execute(text(
                "ALTER TABLE visits ADD COLUMN photo_pending BOOLEAN DEFAULT FALSE"
            ))
            _conn.commit()
        except Exception:
            _conn.rollback()

    # Drop the old global unique constraint on leads.lazada_id so the same seller
    # can appear in multiple campaigns (Option A: per-campaign uniqueness only).
    with db.engine.connect() as _conn:
        try:
            _conn.execute(text(
                "ALTER TABLE leads DROP CONSTRAINT IF EXISTS leads_lazada_id_key"
            ))
            _conn.commit()
        except Exception:
            _conn.rollback()

    # Add ML scoring + health inspection columns to leads
    _new_lead_cols = [
        ("ml_score",          "FLOAT"),
        ("ml_trained_at",     "TIMESTAMP"),
        ("ai_readiness",      "TEXT"),
        ("ai_inspected_at",   "TIMESTAMP"),
        ("is_warehouse",      "BOOLEAN DEFAULT FALSE"),
        ("is_duplicate_addr", "BOOLEAN DEFAULT FALSE"),
        ("campaign_id",       "INTEGER"),
        ("ai_score",          "INTEGER"),
        ("is_archived",       "BOOLEAN DEFAULT FALSE"),
    ]
    with db.engine.connect() as _conn:
        for _col, _type in _new_lead_cols:
            try:
                _conn.execute(text(
                    f"ALTER TABLE leads ADD COLUMN {_col} {_type}"
                ))
                _conn.commit()
            except Exception:
                _conn.rollback()

    # Add is_priority to brands table
    with db.engine.connect() as _conn:
        try:
            _conn.execute(text("ALTER TABLE brands ADD COLUMN is_priority BOOLEAN DEFAULT FALSE"))
            _conn.commit()
        except Exception:
            _conn.rollback()

    # Add can_scout to users table
    with db.engine.connect() as _conn:
        try:
            _conn.execute(text("ALTER TABLE users ADD COLUMN can_scout BOOLEAN DEFAULT FALSE"))
            _conn.commit()
        except Exception:
            _conn.rollback()

    # Create scout_logs table for Prospect Scout audit trail
    with db.engine.connect() as _conn:
        try:
            _conn.execute(text("""
                CREATE TABLE IF NOT EXISTS scout_logs (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id),
                    keyword VARCHAR(200) NOT NULL,
                    category VARCHAR(80),
                    city VARCHAR(120),
                    platform VARCHAR(40),
                    result_count INTEGER DEFAULT 0,
                    searched_at TIMESTAMP DEFAULT NOW()
                )
            """))
            _conn.commit()
        except Exception:
            _conn.rollback()

    # Create campaigns and campaign_priority_log tables if not exist, then seed Legacy campaign
    with db.engine.connect() as _conn:
        try:
            _conn.execute(text("""
                CREATE TABLE IF NOT EXISTS campaigns (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(200) NOT NULL,
                    description TEXT,
                    priority INTEGER DEFAULT 99,
                    status VARCHAR(20) DEFAULT 'active',
                    created_by INTEGER REFERENCES users(id),
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            _conn.execute(text("""
                CREATE TABLE IF NOT EXISTS campaign_priority_log (
                    id SERIAL PRIMARY KEY,
                    campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
                    changed_by INTEGER NOT NULL REFERENCES users(id),
                    prev_priority INTEGER,
                    new_priority INTEGER,
                    reason TEXT,
                    changed_at TIMESTAMP DEFAULT NOW()
                )
            """))
            _conn.commit()
        except Exception:
            _conn.rollback()

    # Create lead_intelligence table
    with db.engine.connect() as _conn:
        try:
            _conn.execute(text("""
                CREATE TABLE IF NOT EXISTS lead_intelligence (
                    id SERIAL PRIMARY KEY,
                    lead_id INTEGER NOT NULL UNIQUE REFERENCES leads(id),
                    ai_score INTEGER,
                    ai_brief TEXT,
                    platforms_json TEXT,
                    is_on_lazada BOOLEAN,
                    score_reason TEXT,
                    top_platform VARCHAR(50),
                    max_followers INTEGER,
                    last_active VARCHAR(50),
                    product_category VARCHAR(200),
                    price_range VARCHAR(100),
                    avg_rating FLOAT,
                    product_count INTEGER,
                    scan_status VARCHAR(20) DEFAULT 'pending',
                    scan_trigger VARCHAR(30),
                    scanned_at TIMESTAMP,
                    error_msg TEXT
                )
            """))
            _conn.commit()
        except Exception:
            _conn.rollback()

    # Add any new columns to existing lead_intelligence table (safe for existing deploys)
    _new_intel_cols = [
        ("top_platform",     "VARCHAR(50)"),
        ("max_followers",    "INTEGER"),
        ("last_active",      "VARCHAR(50)"),
        ("product_category", "VARCHAR(200)"),
        ("price_range",      "VARCHAR(100)"),
        ("avg_rating",       "FLOAT"),
        ("product_count",    "INTEGER"),
        ("pitch_script",     "TEXT"),
    ]
    with db.engine.connect() as _conn:
        for _col, _type in _new_intel_cols:
            try:
                _conn.execute(text(
                    f"ALTER TABLE lead_intelligence ADD COLUMN {_col} {_type}"
                ))
                _conn.commit()
            except Exception:
                _conn.rollback()

    # Seed "Legacy" campaign for existing leads that have no campaign_id
    with app.app_context():
        try:
            legacy = Campaign.query.filter_by(name='Legacy').first()
            if not legacy:
                legacy = Campaign(name='Legacy', description='Leads imported before campaign tracking was added.', priority=99, status='active')
                db.session.add(legacy)
                db.session.flush()
            # Backfill existing leads
            db.session.execute(
                text("UPDATE leads SET campaign_id = :cid WHERE campaign_id IS NULL"),
                {'cid': legacy.id}
            )
            db.session.commit()
        except Exception:
            db.session.rollback()


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.before_request
def update_last_seen():
    if current_user.is_authenticated:
        # Update at most once per minute to avoid DB spam
        now = datetime.utcnow()
        if not current_user.last_seen or (now - current_user.last_seen).total_seconds() > 60:
            current_user.last_seen = now
            db.session.commit()


# ─── AI LEAD INTELLIGENCE ENGINE ─────────────────────────────────────────────

def _enrich_lead(lead_id):
    """SerpAPI search + Claude Haiku extraction for one lead. Runs in background thread."""
    import threading, requests as _req, json as _json
    try:
        import anthropic as _anthropic
    except ImportError:
        return

    with app.app_context():
        lead = Lead.query.get(lead_id)
        if not lead:
            return
        intel = lead.intelligence
        if not intel:
            intel = LeadIntelligence(lead_id=lead_id)
            db.session.add(intel)
        intel.scan_status = 'running'
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            return

        try:
            # 1. SerpAPI web search
            serp_key = os.environ.get('SERPAPI_KEY', '')
            search_snippet = ''
            if serp_key:
                query = f'{lead.seller_name} {lead.city or ""} online seller shop'.strip()
                resp = _req.get('https://serpapi.com/search', params={
                    'q': query, 'api_key': serp_key, 'num': 5, 'engine': 'google'
                }, timeout=12)
                if resp.ok:
                    organic = resp.json().get('organic_results', [])
                    lines = []
                    for r in organic[:5]:
                        lines.append(f"- {r.get('title','')} | {r.get('snippet','')}\n  URL: {r.get('link','')}")
                    search_snippet = '\n'.join(lines)

            # 2. Claude Haiku extraction
            api_key = os.environ.get('ANTHROPIC_API_KEY', '')
            if not api_key:
                raise Exception('ANTHROPIC_API_KEY not set')

            client = _anthropic.Anthropic(api_key=api_key)
            prompt = f"""You are analyzing a seller lead for Lazada recruitment in Southeast Asia.

Seller info:
- Name: {lead.seller_name}
- City: {lead.city or 'Unknown'}
- Category: {lead.category or 'Unknown'}
- Phone: {lead.contact_number or 'Unknown'}
- Known link: {lead.link or 'None'}

Web search results:
{search_snippet if search_snippet else '(No search results available — use seller info only)'}

Extract ALL available intelligence. Respond ONLY with valid JSON (no markdown, no extra text):
{{
  "ai_score": <integer 0-100; 90-100=active multi-platform seller NOT on Lazada; 70-89=single platform active; 50-69=physical biz with social presence; below 50=hard to verify or wrong data>,
  "ai_brief": "<2-3 sentences for the field agent: what they sell, where found online, key numbers, and the single best pitch angle. Max 60 words.>",
  "score_reason": "<one sentence explaining the score>",
  "is_on_lazada": <true if confirmed already on Lazada, false if not found, null if unknown>,
  "top_platform": "<the platform where they are most active, e.g. Shopee, TikTok, Facebook, or null>",
  "max_followers": <integer — highest follower/fan count found across all platforms, or null>,
  "last_active": "<approximate last activity across any platform, e.g. '2 days ago', 'last week', 'this month', 'inactive', or null>",
  "product_category": "<specific product category found, e.g. 'Baked goods', 'Women fashion / Hijab', 'Electronics accessories', or null>",
  "price_range": "<price range found, e.g. 'Budget RM5–30', 'Mid-range RM50–200', 'Premium RM300+', or null>",
  "avg_rating": <float — best rating found, e.g. 4.8, or null>,
  "product_count": <integer — total number of products listed across platforms, or null>,
  "pitch_script": "<3 punchy lines for the field agent to say when meeting this seller. Line 1: ice-breaker referencing their business. Line 2: Lazada value proposition tailored to their category. Line 3: clear next step / call to action. Max 40 words total. Write in English.>",
  "platforms": [
    {{
      "name": "<Shopee|TikTok|Facebook|Instagram|Tokopedia|WhatsApp Business|Google Business|Other>",
      "status": "<active|inactive|not_found>",
      "detail": "<concise summary: followers/products/rating/sales — only what was actually found>",
      "followers": <integer or null>,
      "rating": <float or null>,
      "product_count": <integer or null>,
      "last_active": "<recency string or null>"
    }}
  ]
}}"""

            msg = client.messages.create(
                model='claude-haiku-4-5-20251001',
                max_tokens=800,
                messages=[{'role': 'user', 'content': prompt}]
            )
            raw = msg.content[0].text.strip()
            if raw.startswith('```'):
                raw = raw[raw.find('{'):]
                if '```' in raw:
                    raw = raw[:raw.rfind('```')]
            result = _json.loads(raw.strip())

            intel.ai_score = max(0, min(100, int(result.get('ai_score', 50))))
            intel.ai_brief = result.get('ai_brief', '')
            intel.score_reason = result.get('score_reason', '')
            intel.platforms_json = _json.dumps(result.get('platforms', []))
            intel.is_on_lazada = result.get('is_on_lazada')
            # New product intelligence fields
            intel.top_platform = result.get('top_platform')
            intel.max_followers = result.get('max_followers')
            intel.last_active = result.get('last_active')
            intel.product_category = result.get('product_category')
            intel.price_range = result.get('price_range')
            _rating = result.get('avg_rating')
            intel.avg_rating = float(_rating) if _rating is not None else None
            _pcount = result.get('product_count')
            intel.product_count = int(_pcount) if _pcount is not None else None
            intel.pitch_script = result.get('pitch_script')
            intel.scan_status = 'done'
            intel.scanned_at = datetime.utcnow()
            intel.error_msg = None
            lead.ai_score = intel.ai_score
            db.session.commit()

        except Exception as e:
            intel.scan_status = 'failed'
            intel.error_msg = str(e)[:300]
            intel.scanned_at = datetime.utcnow()
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()


def _enrich_lead_background(lead_id, trigger='auto'):
    """Queue a lead for background enrichment (fire-and-forget thread)."""
    import threading
    with app.app_context():
        intel = LeadIntelligence.query.filter_by(lead_id=lead_id).first()
        if not intel:
            intel = LeadIntelligence(lead_id=lead_id, scan_status='pending', scan_trigger=trigger)
            db.session.add(intel)
        else:
            intel.scan_status = 'pending'
            intel.scan_trigger = trigger
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
    t = threading.Thread(target=_enrich_lead, args=(lead_id,), daemon=True)
    t.start()


@app.route('/leads/<int:lead_id>/scan', methods=['POST'])
@login_required
def lead_scan(lead_id):
    """Trigger AI enrichment for a single lead (manual or Gabay re-scan)."""
    lead = Lead.query.get_or_404(lead_id)
    if current_user.role not in ('gabay', 'superadmin', 'admin', 'manager', 'supervisor'):
        return jsonify({'error': 'Access denied'}), 403
    if current_user.role == 'gabay' and lead.gabay_id != current_user.id:
        return jsonify({'error': 'Not your lead'}), 403
    _enrich_lead_background(lead_id, trigger='manual')
    return jsonify({'status': 'queued', 'lead_id': lead_id})


@app.route('/leads/<int:lead_id>/intel')
@login_required
def lead_intel(lead_id):
    """Return current intel JSON for a lead (polled by Gabay after scan)."""
    lead = Lead.query.get_or_404(lead_id)
    if current_user.role == 'gabay' and lead.gabay_id != current_user.id:
        return jsonify({'error': 'Not your lead'}), 403
    intel = lead.intelligence
    if not intel:
        return jsonify({'scan_status': 'none'})
    return jsonify({
        'scan_status': intel.scan_status,
        'ai_score': intel.ai_score,
        'ai_brief': intel.ai_brief,
        'score_reason': intel.score_reason,
        'is_on_lazada': intel.is_on_lazada,
        'top_platform': intel.top_platform,
        'max_followers': intel.max_followers,
        'last_active': intel.last_active,
        'product_category': intel.product_category,
        'price_range': intel.price_range,
        'avg_rating': intel.avg_rating,
        'product_count': intel.product_count,
        'platforms': intel.platforms,
        'scanned_at': intel.scanned_at.isoformat() if intel.scanned_at else None,
        'error_msg': intel.error_msg,
    })


@app.route('/campaigns/<int:campaign_id>/sweep', methods=['POST'])
@login_required
def campaign_sweep(campaign_id):
    """Bulk AI enrichment for all un-scanned leads in a campaign."""
    if not current_user.is_manager:
        return jsonify({'error': 'Access denied'}), 403
    campaign = Campaign.query.get_or_404(campaign_id)
    leads = Lead.query.filter_by(campaign_id=campaign_id).all()
    queued = 0
    for lead in leads:
        intel = lead.intelligence
        if not intel or intel.scan_status in ('pending', 'failed'):
            _enrich_lead_background(lead.id, trigger='campaign_sweep')
            queued += 1
    return jsonify({'status': 'ok', 'queued': queued, 'campaign': campaign.name})


# ─────────────────────────────────────────────────────────────────────────────

@app.context_processor
def inject_globals():
    from datetime import datetime as dt
    pool_count = 0
    unread_notif = 0
    if current_user.is_authenticated:
        if current_user.is_supervisor:
            pool_count = Lead.query.filter_by(status='pool').count()
        unread_notif = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    return dict(pool_nav_count=pool_count, now=dt.utcnow(), unread_notif=unread_notif)


# ─── FIRST-TIME SETUP ────────────────────────────────────────────────────────

@app.route('/setup')
def setup():
    if User.query.count() > 0:
        return 'Setup already done. Users exist.', 403
    from werkzeug.security import generate_password_hash
    u = User(username='superadmin', full_name='Super Admin', email='admin@altria.com',
             role='superadmin', password_hash=generate_password_hash('Super@2026'), is_active=True)
    db.session.add(u)
    db.session.commit()
    return 'Superadmin created! Username: superadmin  Password: Super@2026 — Go to /login now.'


# ─── MANAGER WHATSAPP NOTIFICATIONS ─────────────────────────────────────────

def _notify_managers_whatsapp(message: str):
    """Send a WhatsApp message to all active managers/admins who have a mobile number."""
    import threading
    from whatsapp import send_message
    managers = User.query.filter(
        User.is_active == True,
        User.role.in_(['manager', 'admin', 'superadmin', 'supervisor']),
        User.mobile.isnot(None),
        User.mobile != '',
        User.whatsapp_alerts_enabled == True
    ).all()
    def _send():
        with app.app_context():
            for m in managers:
                try:
                    send_message(m.mobile, message)
                except Exception as e:
                    app.logger.error(f'[WA Notify] Failed to notify {m.username}: {e}')
    threading.Thread(target=_send, daemon=True).start()


def _notify_managers_telegram(message: str):
    """Send a Telegram message to all managers/admins who have linked their Telegram."""
    import threading
    from telegram_bot import send_message as tg_send
    managers = User.query.filter(
        User.is_active == True,
        User.role.in_(['manager', 'admin', 'superadmin', 'supervisor']),
        User.telegram_chat_id.isnot(None),
        User.telegram_chat_id != '',
    ).all()
    def _send():
        with app.app_context():
            for m in managers:
                try:
                    tg_send(m.telegram_chat_id, message)
                except Exception as e:
                    app.logger.error(f'[TG Notify] Failed to notify {m.username}: {e}')
    threading.Thread(target=_send, daemon=True).start()


# ─── TELEGRAM DAILY REPORT ───────────────────────────────────────────────────

def _build_daily_report(period: str) -> str:
    """Build the 8 AM / 8 PM Telegram report for all linked managers."""
    from datetime import timezone, timedelta as _td
    _PHT = timezone(_td(hours=8))
    now_pht = datetime.now(_PHT)
    today_pht = now_pht.date()

    # UTC window for "today PHT"
    day_start_utc = datetime(today_pht.year, today_pht.month, today_pht.day, 0, 0, 0) - timedelta(hours=8)
    day_end_utc   = day_start_utc + timedelta(days=1)

    gabays = User.query.filter_by(role='gabay', is_active=True).order_by(User.full_name).all()

    emoji = '🌅' if period == 'morning' else '🌙'
    label = 'Morning' if period == 'morning' else 'Evening'
    lines = [
        f"{emoji} *LSAMS {label} Report*",
        f"📅 {now_pht.strftime('%b %d, %Y — %I:%M %p')} PHT",
        f"",
        f"👥 *Gabay Activity ({len(gabays)} agents)*",
    ]

    total_visits = 0
    for g in gabays:
        # Check if logged in today (PHT)
        logged_in = (
            g.last_seen and
            day_start_utc <= g.last_seen.replace(tzinfo=None) < day_end_utc
        )
        # Visits today
        visits_today = Visit.query.filter(
            Visit.gabay_id == g.id,
            Visit.visited_at >= day_start_utc,
            Visit.visited_at < day_end_utc,
        ).all()

        total_visits += len(visits_today)
        name = g.display_name or g.full_name

        if visits_today:
            outcome_counts = {}
            for v in visits_today:
                o = (v.outcome or 'unknown').replace('_', ' ')
                outcome_counts[o] = outcome_counts.get(o, 0) + 1
            outcome_str = ', '.join(f"{cnt} {o}" for o, cnt in outcome_counts.items())
            status_icon = '✅'
            activity = f"{len(visits_today)} visit{'s' if len(visits_today)>1 else ''} ({outcome_str})"
        elif logged_in:
            status_icon = '🟡'
            activity = 'Logged in — no visits yet'
        else:
            status_icon = '⚪'
            activity = 'Not active today'

        lines.append(f"{status_icon} {name} — {activity}")

    lines += [
        f"",
        f"📊 Total visits today: *{total_visits}*",
    ]

    # Live sellers count
    live_count = Lead.query.filter_by(status='live').count()
    lines.append(f"✅ Live sellers (all time): *{live_count}*")

    return '\n'.join(lines)


def _send_daily_report(period: str):
    with app.app_context():
        try:
            message = _build_daily_report(period)
            _notify_managers_telegram(message)
            app.logger.info(f'[TG] Daily {period} report sent.')
        except Exception as e:
            app.logger.error(f'[TG] Daily report error: {e}', exc_info=True)


# Start APScheduler — 8 AM and 8 PM Philippine Time daily
def _start_scheduler():
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        import pytz
        _tz = pytz.timezone('Asia/Manila')
        scheduler = BackgroundScheduler(timezone=_tz)
        scheduler.add_job(
            lambda: _send_daily_report('morning'),
            CronTrigger(hour=8, minute=0, timezone=_tz),
            id='daily_morning_report', replace_existing=True,
        )
        scheduler.add_job(
            lambda: _send_daily_report('evening'),
            CronTrigger(hour=20, minute=0, timezone=_tz),
            id='daily_evening_report', replace_existing=True,
        )
        scheduler.start()
        app.logger.info('[TG] Daily report scheduler started (8 AM & 8 PM PHT)')
    except Exception as e:
        app.logger.warning(f'[TG] Scheduler not started: {e}')


# Only start once (not on every gunicorn worker fork)
if os.environ.get('WERKZEUG_RUN_MAIN') != 'false':
    _start_scheduler()


# ─── AUTH ────────────────────────────────────────────────────────────────────

@app.route('/', methods=['GET', 'POST'])
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and user.is_active and user.check_password(password):
            login_user(user, remember=request.form.get('remember'))
            user.last_login = datetime.utcnow()
            db.session.commit()
            # Notify managers when a Gabay agent logs in
            if user.role == 'gabay':
                from datetime import datetime as _dt
                _login_msg = (
                    f"📱 *Gabay Login*\n"
                    f"👤 {user.full_name} just logged in to LSAMS\n"
                    f"🕐 {_dt.now().strftime('%b %d, %Y at %I:%M %p')}"
                )
                _notify_managers_whatsapp(_login_msg)
                _notify_managers_telegram(_login_msg)
            dest = request.args.get('next')
            if not dest:
                if user.role == 'gabay':
                    dest = url_for('gabay_home')
                elif user.role == 'lazada':
                    dest = url_for('lazada_portal')
                else:
                    dest = url_for('dashboard')
            return redirect(dest)
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


# ─── DASHBOARD ───────────────────────────────────────────────────────────────

@app.route('/dashboard')
@login_required
def dashboard():
    from datetime import timedelta

    # Campaign filter — default to P1 (highest priority active campaign)
    p1 = _priority1_campaign()
    campaign_id = request.args.get('campaign_id', type=int)
    if campaign_id is None and p1:
        campaign_id = p1.id
    campaigns = Campaign.query.order_by(Campaign.priority, Campaign.name).all()
    selected_campaign = Campaign.query.get(campaign_id) if campaign_id else None

    def base_q():
        q = Lead.query.filter(Lead.status != 'removed')
        if campaign_id:
            q = q.filter_by(campaign_id=campaign_id)
        return q

    # KPI totals
    total_pool   = base_q().count()
    assigned     = base_q().filter(Lead.gabay_id.isnot(None)).count()
    attempting   = base_q().filter_by(status='attempting').count()
    negotiation  = base_q().filter_by(status='negotiation').count()
    registration = base_q().filter_by(status='registration').count()
    live    = base_q().filter_by(status='live').count()
    matched = base_q().filter_by(status='matched').count()

    # Per-gabay summary for table
    gabay_users = User.query.filter_by(role='gabay', is_active=True).all()
    gabay_stats = []
    for g in gabay_users:
        def gq(status=None):
            q = Lead.query.filter(Lead.gabay_id == g.id, Lead.status != 'removed')
            if campaign_id:
                q = q.filter_by(campaign_id=campaign_id)
            if status:
                q = q.filter_by(status=status)
            return q
        g_total      = gq().count()  # all leads with this Gabay, any status
        g_assigned   = gq('assigned').count()
        g_attempting = gq('attempting').count()
        g_negotiation = gq('negotiation').count()
        g_registration = gq('registration').count()
        g_live    = gq('live').count()
        g_matched = gq('matched').count()
        if g_total == 0 and not campaign_id:
            pass  # skip gabays with zero leads only in all-campaign view? No, show all
        gabay_stats.append({
            'id': g.id, 'name': g.full_name, 'pool': g_total, 'assigned': g_assigned,
            'attempting': g_attempting, 'negotiation': g_negotiation,
            'registration': g_registration, 'live': g_live, 'matched': g_matched,
        })

    forecast = round(negotiation * 0.6 + registration * 0.85)

    # Week-over-week activity per KPI status
    _7d  = datetime.utcnow() - timedelta(days=7)
    _14d = datetime.utcnow() - timedelta(days=14)
    def _week_act(status):
        sq = db.session.query(Lead.id).filter(Lead.status == status, Lead.status != 'removed')
        if campaign_id:
            sq = sq.filter(Lead.campaign_id == campaign_id)
        this_wk = Visit.query.filter(Visit.lead_id.in_(sq), Visit.visited_at >= _7d).count()
        prev_wk = Visit.query.filter(Visit.lead_id.in_(sq), Visit.visited_at >= _14d, Visit.visited_at < _7d).count()
        return {'this': this_wk, 'prev': prev_wk, 'delta': this_wk - prev_wk}
    kpi_meta = {s: _week_act(s) for s in ('attempting','negotiation','registration','live','matched')}

    # Visits KPIs
    from datetime import timezone as _tz
    _today_utc = date.today()
    visits_today_q = Visit.query.filter(func.date(Visit.visited_at) == _today_utc)
    if campaign_id:
        visits_today_q = visits_today_q.join(Lead, Visit.lead_id == Lead.id).filter(Lead.campaign_id == campaign_id)
    visits_today = visits_today_q.count()
    visits_total = Visit.query.count()

    # Recent activity
    rv_q = Visit.query.order_by(Visit.visited_at.desc())
    if campaign_id:
        rv_q = rv_q.join(Lead).filter(Lead.campaign_id == campaign_id)
    recent_visits = rv_q.limit(10).all()

    # Aging leads
    aging_cutoff = datetime.utcnow() - timedelta(days=14)
    aging_q = base_q().filter(
        Lead.status.in_(['assigned', 'attempting']),
        ~Lead.id.in_(
            db.session.query(Visit.lead_id).filter(Visit.visited_at >= aging_cutoff)
        )
    ).order_by(Lead.assigned_at.asc()).limit(20)
    aging_leads = aging_q.all()
    for al in aging_leads:
        al._gabay = User.query.get(al.gabay_id) if al.gabay_id else None

    return render_template('dashboard.html',
        total_pool=total_pool, assigned=assigned, attempting=attempting,
        negotiation=negotiation, registration=registration, live=live,
        matched=matched, forecast=forecast, gabay_stats=gabay_stats,
        recent_visits=recent_visits, aging_leads=aging_leads,
        visits_today=visits_today, visits_total=visits_total,
        campaigns=campaigns, selected_campaign=selected_campaign, campaign_id=campaign_id,
        kpi_meta=kpi_meta)


# ─── LEADS ───────────────────────────────────────────────────────────────────

@app.route('/leads')
@login_required
def leads():
    page = request.args.get('page', 1, type=int)
    status_filter = request.args.get('status', '')
    gabay_filter = request.args.get('gabay', '', type=str)
    search = request.args.get('q', '')
    campaign_id = request.args.get('campaign_id', type=int)
    per_page = 20

    query = Lead.query
    if current_user.role == 'gabay':
        query = query.filter_by(gabay_id=current_user.id)
    if campaign_id:
        query = query.filter(Lead.campaign_id == campaign_id)
    if status_filter:
        query = query.filter_by(status=status_filter)
    if gabay_filter:
        query = query.filter_by(gabay_id=gabay_filter)
    if search:
        query = query.filter(or_(
            Lead.seller_name.ilike(f'%{search}%'),
            Lead.sender_name.ilike(f'%{search}%'),
            Lead.contact_number.ilike(f'%{search}%'),
            Lead.city.ilike(f'%{search}%'),
            Lead.barangay.ilike(f'%{search}%'),
            Lead.province.ilike(f'%{search}%'),
            Lead.address.ilike(f'%{search}%'),
            Lead.category.ilike(f'%{search}%'),
            Lead.cluster.ilike(f'%{search}%'),
            Lead.project.ilike(f'%{search}%'),
            Lead.lazada_id.ilike(f'%{search}%'),
            Lead.email.ilike(f'%{search}%'),
            Lead.notes.ilike(f'%{search}%'),
        ))

    pagination = query.order_by(Lead.imported_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    gabay_users = User.query.filter_by(role='gabay', is_active=True).all()
    campaigns = Campaign.query.order_by(Campaign.priority, Campaign.name).all()
    selected_campaign = Campaign.query.get(campaign_id) if campaign_id else None
    return render_template('leads/list.html', pagination=pagination,
                           status_filter=status_filter, gabay_filter=gabay_filter,
                           search=search, gabay_users=gabay_users,
                           campaigns=campaigns, campaign_id=campaign_id,
                           selected_campaign=selected_campaign)


# ─── AJAX LIVE SEARCH ────────────────────────────────────────────────────────

@app.route('/api/leads/search')
@login_required
def api_leads_search():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    query = Lead.query
    if current_user.role == 'gabay':
        query = query.filter_by(gabay_id=current_user.id)
    results = query.filter(or_(
        Lead.seller_name.ilike(f'%{q}%'),
        Lead.contact_number.ilike(f'%{q}%'),
        Lead.city.ilike(f'%{q}%'),
        Lead.barangay.ilike(f'%{q}%'),
        Lead.province.ilike(f'%{q}%'),
        Lead.category.ilike(f'%{q}%'),
        Lead.cluster.ilike(f'%{q}%'),
        Lead.project.ilike(f'%{q}%'),
        Lead.address.ilike(f'%{q}%'),
    )).order_by(Lead.seller_name).limit(12).all()
    return jsonify([{
        'id': l.id,
        'name': l.seller_name,
        'city': l.city or '',
        'barangay': l.barangay or '',
        'province': l.province or '',
        'status': l.status,
        'status_label': l.status_label,
        'category': l.category or '',
        'gabay': l.assigned_gabay.display_name if l.assigned_gabay else None,
        'url': url_for('lead_detail', lead_id=l.id)
    } for l in results])


# ─── PROSPECT SCOUT ──────────────────────────────────────────────────────────

@app.route('/prospect-scout')
@login_required
def prospect_scout():
    # Lazada team + supervisors + admins + gabay users with scout permission
    if not (current_user.is_supervisor or current_user.role == 'lazada'
            or (current_user.role == 'gabay' and current_user.can_scout)):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))

    gabay_users = User.query.filter_by(role='gabay', is_active=True).order_by(User.full_name).all()
    campaigns = Campaign.query.filter_by(status='active').order_by(Campaign.priority).all()

    # City access rules
    see_all_cities = current_user.role in ('superadmin', 'admin', 'manager', 'lazada')
    user_cities = current_user.city_list if hasattr(current_user, 'city_list') else []

    # SerpAPI check — only show status to admins
    serp_status = 'not_set'
    serp_plan = ''
    if current_user.is_admin:
        serp_key = os.environ.get('SERPAPI_KEY', '').strip()
        if serp_key:
            try:
                import requests as _req
                r = _req.get('https://serpapi.com/account', params={'api_key': serp_key}, timeout=8)
                if r.ok:
                    info = r.json()
                    serp_status = 'ok'
                    serp_plan = f"{info.get('plan_name','')} · {info.get('plan_searches_left','?')} searches left"
                else:
                    serp_status = 'invalid'
            except Exception:
                serp_status = 'error'
        serp_configured = serp_status == 'ok'
    else:
        serp_key = os.environ.get('SERPAPI_KEY', '').strip()
        serp_configured = bool(serp_key)

    return render_template('leads/prospect_scout.html',
                           gabay_users=gabay_users,
                           campaigns=campaigns,
                           serp_configured=serp_configured,
                           serp_status=serp_status,
                           serp_plan=serp_plan,
                           see_all_cities=see_all_cities,
                           user_cities=user_cities,
                           user_role=current_user.role)


@app.route('/api/prospect/scout')
@login_required
def api_prospect_scout():
    if not (current_user.is_supervisor or current_user.role == 'lazada'
            or (current_user.role == 'gabay' and current_user.can_scout)):
        return jsonify({'error': 'Access denied'}), 403

    import requests as _req, re as _re

    keyword  = request.args.get('keyword', '').strip()
    city     = request.args.get('city', '').strip()
    platform = request.args.get('platform', 'all').strip()
    category = request.args.get('category', '').strip()
    serp_key = os.environ.get('SERPAPI_KEY', '')

    if not keyword:
        return jsonify({'error': 'Keyword required'}), 400
    if not serp_key:
        return jsonify({'error': 'SERPAPI_KEY not configured.'}), 503

    # Enforce city restrictions for gabay
    if current_user.role == 'gabay':
        allowed = current_user.city_list
        if allowed and city.lower() not in [c.lower() for c in allowed]:
            city = allowed[0] if allowed else city

    location_str = f'{city} Philippines' if city else 'Philippines'

    # Platform query map — Coffee = Shopee PH (internal alias)
    platform_queries = {
        'coffee':   [f'site:shopee.ph {keyword} {city}', f'shopee seller {keyword} {location_str}'],
        'tiktok':   [f'site:tiktok.com {keyword} {city} shop', f'tiktok shop {keyword} {location_str}'],
        'facebook': [f'site:facebook.com {keyword} {city} seller', f'facebook {keyword} seller {location_str}'],
        'rrld':     [f'{keyword} {city} Philippines retailer reseller',
                     f'{keyword} {location_str} local distributor authorized dealer'],
    }

    if platform == 'all':
        queries = [(p, qs[0]) for p, qs in platform_queries.items()]
    else:
        queries = [(platform, q) for q in platform_queries.get(platform, [])[:2]]

    results  = []
    seen_urls = set()

    for plat, q in queries:
        try:
            resp = _req.get('https://serpapi.com/search', params={
                'q': q, 'api_key': serp_key, 'num': 10,
                'engine': 'google', 'gl': 'ph', 'hl': 'en',
            }, timeout=15)
            if not resp.ok:
                continue
            organic = resp.json().get('organic_results', [])
            for r in organic:
                url  = r.get('link', '')
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                title   = r.get('title', '')
                snippet = r.get('snippet', '')

                # Detect display platform from URL
                detected = plat
                if 'shopee.ph' in url:
                    detected = 'coffee'
                elif 'tiktok.com' in url:
                    detected = 'tiktok'
                elif 'facebook.com' in url:
                    detected = 'facebook'

                # Skip Shopee homepage
                if detected == 'coffee' and '/shop/' not in url and '/product/' not in url:
                    if url.rstrip('/') == 'https://shopee.ph':
                        continue

                # RRLD scoring
                combined = (title + ' ' + snippet).lower()
                rrld_score = 0
                rrld_tags  = []
                for sig in ['official', 'brand', 'authorized', 'verified', 'top seller', 'mall', 'premium']:
                    if sig in combined:
                        rrld_score += 15
                        rrld_tags.append(sig.title())
                for sig in ['branches', 'nationwide', 'all over ph', 'multiple locations', 'store locator']:
                    if sig in combined:
                        rrld_score += 20
                        rrld_tags.append('Multi-Branch')
                        break
                for num, label in _re.findall(r'(\d[\d.,]+)\s*[kK]\s*(followers|sold|sales|reviews)', snippet):
                    if float(num.replace(',', '')) >= 10:
                        rrld_score += 25
                        rrld_tags.append(f'{num}K {label.title()}')

                rrld_score = min(100, rrld_score)

                # Clean shop name
                shop_name = title
                for suffix in [' | Shopee Philippines', ' - Shopee', ' | TikTok', ' | Facebook', ' (@', ' - Facebook']:
                    if suffix in shop_name:
                        shop_name = shop_name[:shop_name.index(suffix)]
                shop_name = shop_name.strip()

                existing = Lead.query.filter(
                    Lead.seller_name.ilike(f'%{shop_name[:30]}%')
                ).first() if len(shop_name) > 5 else None

                results.append({
                    'shop_name':      shop_name,
                    'platform':       detected,
                    'url':            url,
                    'snippet':        snippet,
                    'rrld_score':     rrld_score,
                    'rrld_tags':      list(set(rrld_tags))[:4],
                    'is_rrld':        rrld_score >= 30,
                    'in_system':      existing is not None,
                    'existing_id':    existing.id if existing else None,
                    'existing_status':existing.status if existing else None,
                })
        except Exception:
            continue

    results.sort(key=lambda x: (-x['rrld_score'], x['shop_name']))

    # ── Lazada presence check — 1 extra SerpAPI call ──────────────────────────
    try:
        laz_query = f'site:lazada.com.ph {keyword}'
        laz_resp  = _req.get('https://serpapi.com/search', params={
            'q': laz_query, 'api_key': serp_key, 'num': 10,
            'engine': 'google', 'gl': 'ph', 'hl': 'en',
        }, timeout=10)
        laz_names = []   # store names found on Lazada
        laz_urls  = {}   # shop_name_token → lazada URL
        if laz_resp.ok:
            for lr in laz_resp.json().get('organic_results', []):
                lt = lr.get('title', '')
                lu = lr.get('link', '')
                # Extract store slug from lazada URL
                import re as _rez
                slug_m = _rez.search(r'lazada\.com\.ph/shop/([^/?#]+)', lu)
                store_name = slug_m.group(1).replace('-', ' ') if slug_m else lt
                laz_names.append(store_name.lower())
                laz_urls[store_name.lower()] = lu

        _STOP = {'store','shop','official','ph','philippines','online','the','and','ng','de','seller'}

        def _laz_match(shop):
            """Returns (matched, lazada_url) — fuzzy name-token overlap check."""
            words = {w for w in shop.lower().split() if w not in _STOP and len(w) > 2}
            if not words:
                return False, None
            for lname, lurl in laz_urls.items():
                lwords = {w for w in lname.split() if w not in _STOP and len(w) > 2}
                if not lwords:
                    continue
                overlap = words & lwords
                threshold = max(1, min(len(words), len(lwords)) // 2)
                if len(overlap) >= threshold:
                    return True, lurl
            return False, None

        for r in results:
            matched, lurl = _laz_match(r['shop_name'])
            if laz_names:   # we got Lazada results — can make a call
                r['lazada_status'] = 'on_lazada' if matched else 'not_on_lazada'
                r['lazada_url']    = lurl
            else:
                r['lazada_status'] = 'unknown'
                r['lazada_url']    = None
    except Exception:
        for r in results:
            r.setdefault('lazada_status', 'unknown')
            r.setdefault('lazada_url', None)

    # ── Log search & notify supervisors ──────────────────────────────────────
    try:
        log = ScoutLog(
            user_id=current_user.id,
            keyword=keyword,
            category=category or None,
            city=city or None,
            platform=platform,
            result_count=len(results),
        )
        db.session.add(log)

        # In-app notification to all admins/supervisors
        pht_now = datetime.utcnow() + timedelta(hours=8)
        city_label = city or 'All PH'
        cat_label  = f' · {category}' if category else ''
        platform_labels = {'coffee': 'Shopee', 'tiktok': 'TikTok',
                           'facebook': 'Facebook', 'rrld': 'RRLD', 'all': 'All'}
        plat_label = platform_labels.get(platform, platform.title())
        notif_msg = (
            f"{current_user.display_name} searched for \"{keyword}\"{cat_label} "
            f"in {city_label} on {plat_label} — {len(results)} result(s) found "
            f"at {pht_now.strftime('%I:%M %p')}."
        )
        supervisors = User.query.filter(
            User.role.in_(['superadmin', 'admin', 'manager', 'supervisor']),
            User.is_active == True,
        ).all()
        for sup in supervisors:
            db.session.add(Notification(
                user_id=sup.id,
                type='scout_search',
                title=f'🔭 Scout: {current_user.display_name} searched "{keyword}"',
                message=notif_msg,
                link='/admin/scout-activity',
            ))
        db.session.commit()
    except Exception:
        db.session.rollback()

    return jsonify({'results': results, 'count': len(results)})


@app.route('/api/prospect/add-lead', methods=['POST'])
@login_required
def api_prospect_add_lead():
    if not (current_user.is_supervisor or current_user.role == 'lazada'
            or (current_user.role == 'gabay' and current_user.can_scout)):
        return jsonify({'error': 'Access denied'}), 403

    data = request.get_json()
    if not data or not data.get('shop_name'):
        return jsonify({'error': 'shop_name required'}), 400

    platform = data.get('platform', '')
    platform_map = {'coffee': 'COFFEE', 'tiktok': 'TIKTOK', 'facebook': 'FACEBOOK', 'rrld': 'RRLD'}

    lead = Lead(
        seller_name=data['shop_name'],
        link=data.get('url', ''),
        city=data.get('city', ''),
        notes=f"[Prospect Scout] Found on {platform.upper()}. {data.get('snippet', '')[:300]}",
        project=platform_map.get(platform, 'EXTERNAL'),
        status='pool',
        campaign_id=data.get('campaign_id') or None,
        imported_at=datetime.utcnow(),
        batch_ref=f'scout-{datetime.utcnow().strftime("%Y%m%d")}',
    )
    db.session.add(lead)
    db.session.commit()
    return jsonify({'ok': True, 'lead_id': lead.id, 'url': url_for('lead_detail', lead_id=lead.id)})


# ── Brand Management ─────────────────────────────────────────────────────────

_FMCG_DEFAULTS = [
    'NIVEA','Bench','Garnier',"Kiehl's",'Jo Malone London','Glad2Glow',
    '17 MILE','7D','Absidy Beauty','Aesop','Aficionado','AGRILIFE','Aiwibi','Akeeva',
    'All About Baking','All Covered','Anastasia Beverly Hills','Anchor','Andrea Secret',
    'Aozi','Apruva','Ashley','Ashley Beauty Lines','Ashley Hair Fashion','Athlene Nutrition',
    'AUGEAS','Auro Chocolate','AVEDA','AXIS-Y','B Coffee Co','Baby First','Babyflo',
    'BabyPal','Baltra','BAONEO','barenbliss','Be Organic','Bean','Beauty & Co',
    "Belle's Pantry Essentials",'Belo Essentials','Benefit','Benzac','Berber',
    'Beybiko Diapers','Bioré','Bioten','Birch Tree','Bluenotes','Bobbi Brown',
    'Bremod','BritePH','BYS','Camou Men','Careline','Caress','CASSIEL-PET',
    'CheezUp','Chicco','Child Care','ChuChu Beauty','Cimory','Clarins','Clinique',
    'CloudBeauty','COCO FALL IN LOVE WITH','COCOBB','Coffee Grounds PH',
    'Coffee N Tea Essentials','Colourette','Cotton Central','Cuddly','Curve',
    'DAZZLE ME','Deoproce','Dermorepubliq.','Dewha','Dr Alvin Products',
    'Dr. Sensitive','Dr.Isla','Dr.Leo','DW (Danie Wang)','eelhoe','Einmilk',
    'Elizabeth Arden','Enchen','Enfagrow','Enfant','EQ','Eqqualberry',
    'Estée Lauder','Euro Chef','Euromed','Ever Bilena','face republic',
    'FITGUM','Focallure','FOCANO','GAIFEEL','Glutamax','GMEELAN','Gold Leaf',
    'Golden Grains','GOODEST','Goodies Nutrition','GRAFEN','Greenika','Greenola',
    'GRWM Cosmetics','Happy','Happy Life Organics',"Harvester's",'Hegen',
    'HeroKiddy','Human Nature','ICIC','inJoy','Inspi Babies','IPI',
    'iWhite Korea','Japan Home Centre','Jergens','JMCY','Just Love','Kalbe',
    'Kapok','Kérastase','KINETIQQ','Kirkland Signature','KISS','Kleenfant','KMY',
    'La Mer','Lactezin','Laura Mercier','Lactum',"L'Occitane",'Love k-derma',
    'Love k-glow','Lucky Beauty Inc.','Lucky Me!','Luxe Organix','LUXU',
    "M·A·C","Mama's Choice",'Masko.','Master Chef','MCY','Maximo Trading',
    'Maybelline','Medela','MELEDE','Mentholatum',
]

_BRAND_CATEGORIES = ['FMCG', 'Electronics', 'Fashions & Accessories', 'General Merchandise']

def _can_manage_brands():
    return current_user.role in ('superadmin', 'admin', 'lazada')

@app.route('/admin/brands')
@login_required
def admin_brands():
    if not _can_manage_brands():
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    return render_template('admin/brands.html', categories=_BRAND_CATEGORIES)

@app.route('/api/brands', methods=['GET'])
@login_required
def api_brands_list():
    if not (current_user.is_supervisor or current_user.role == 'lazada'):
        return jsonify({'error': 'Access denied'}), 403
    cat = request.args.get('category', '').strip()
    q = Brand.query.filter_by(is_active=True)
    if cat:
        q = q.filter_by(category=cat)
    brands = q.order_by(Brand.is_priority.desc(), Brand.name).all()
    return jsonify({
        'brands': [{
            'id': b.id, 'name': b.name, 'category': b.category,
            'is_priority': bool(b.is_priority),
            'added_by_name': b.adder.display_name if b.adder else '—',
        } for b in brands],
        'can_manage': _can_manage_brands(),
    })

@app.route('/api/brands', methods=['POST'])
@login_required
def api_brands_add():
    if not _can_manage_brands():
        return jsonify({'error': 'Access denied'}), 403
    data = request.get_json()
    name = (data.get('name') or '').strip()
    cat  = (data.get('category') or 'FMCG').strip()
    is_priority = bool(data.get('is_priority', False))
    if not name:
        return jsonify({'error': 'Brand name required'}), 400
    if Brand.query.filter(Brand.name.ilike(name), Brand.is_active == True).first():
        return jsonify({'error': 'Brand already exists'}), 409
    b = Brand(name=name, category=cat, is_priority=is_priority, added_by=current_user.id)
    db.session.add(b)
    db.session.commit()
    return jsonify({'ok': True, 'id': b.id, 'name': b.name, 'category': b.category, 'is_priority': b.is_priority})

@app.route('/api/brands/<int:brand_id>', methods=['PUT'])
@login_required
def api_brands_update(brand_id):
    if not _can_manage_brands():
        return jsonify({'error': 'Access denied'}), 403
    b = Brand.query.get_or_404(brand_id)
    data = request.get_json()
    if 'name' in data and data['name'].strip():
        b.name = data['name'].strip()
    if 'category' in data:
        b.category = data['category'].strip()
    if 'is_priority' in data:
        b.is_priority = bool(data['is_priority'])
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/brands/<int:brand_id>', methods=['DELETE'])
@login_required
def api_brands_delete(brand_id):
    if not _can_manage_brands():
        return jsonify({'error': 'Access denied'}), 403
    b = Brand.query.get_or_404(brand_id)
    b.is_active = False
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/brands/bulk', methods=['POST'])
@login_required
def api_brands_bulk():
    if not _can_manage_brands():
        return jsonify({'error': 'Access denied'}), 403
    data = request.get_json()
    names = [n.strip() for n in (data.get('names') or []) if str(n).strip()]
    cat  = (data.get('category') or 'FMCG').strip()
    is_priority = bool(data.get('is_priority', False))
    added = skipped = 0
    for name in names:
        if Brand.query.filter(Brand.name.ilike(name), Brand.is_active == True).first():
            skipped += 1
        else:
            db.session.add(Brand(name=name, category=cat, is_priority=is_priority, added_by=current_user.id))
            added += 1
    db.session.commit()
    return jsonify({'ok': True, 'added': added, 'skipped': skipped})

@app.route('/api/brands/load-defaults', methods=['POST'])
@login_required
def api_brands_load_defaults():
    if not _can_manage_brands():
        return jsonify({'error': 'Access denied'}), 403
    added = skipped = 0
    for name in _FMCG_DEFAULTS:
        if Brand.query.filter(Brand.name.ilike(name), Brand.is_active == True).first():
            skipped += 1
        else:
            db.session.add(Brand(name=name, category='FMCG', is_priority=True, added_by=current_user.id))
            added += 1
    db.session.commit()
    return jsonify({'ok': True, 'added': added, 'skipped': skipped})


# Auto-seed FMCG defaults on first deploy if brands table is empty
with app.app_context():
    try:
        if Brand.query.filter_by(is_active=True).count() == 0:
            for _name in _FMCG_DEFAULTS:
                db.session.add(Brand(name=_name, category='FMCG', is_priority=True))
            db.session.commit()
    except Exception:
        db.session.rollback()


@app.route('/leads/radar')
@login_required
def leads_radar():
    if not current_user.is_supervisor:
        flash('Access denied.', 'danger')
        return redirect(url_for('leads'))

    city_filter = request.args.get('city', '').strip().lower()
    priority_filter = request.args.get('priority', '').strip()
    campaign_id = request.args.get('campaign_id', type=int)

    pool_q = Lead.query.filter(Lead.status == 'pool', Lead.gabay_id.is_(None))
    if campaign_id:
        pool_q = pool_q.filter(Lead.campaign_id == campaign_id)
    if city_filter:
        pool_q = pool_q.filter(func.lower(Lead.city) == city_filter)
    if priority_filter:
        pool_q = pool_q.filter(Lead.priority_tier == priority_filter)
    pool_leads = pool_q.order_by(Lead.priority_tier).all()
    pool_leads.sort(key=lambda l: l.conversion_score, reverse=True)

    # All distinct cities that have pool leads (for filter dropdown)
    city_rows = db.session.query(Lead.city).filter(
        Lead.status == 'pool', Lead.gabay_id.is_(None),
        Lead.city.isnot(None), Lead.city != ''
    ).distinct().order_by(Lead.city).all()
    cities = [r[0] for r in city_rows]

    gabays = User.query.filter_by(role='gabay', is_active=True).order_by(User.full_name).all()
    campaigns = Campaign.query.order_by(Campaign.priority, Campaign.name).all()

    return render_template('leads/radar.html',
        pool_leads=pool_leads,
        cities=cities,
        gabays=gabays,
        city_filter=city_filter,
        priority_filter=priority_filter,
        total_pool=Lead.query.filter(Lead.status == 'pool', Lead.gabay_id.is_(None)).count(),
        campaigns=campaigns, campaign_id=campaign_id,
    )


@app.route('/leads/import', methods=['GET', 'POST'])
@login_required
def import_leads():
    if not current_user.is_manager:
        flash('Access denied.', 'danger')
        return redirect(url_for('leads'))

    campaigns = Campaign.query.filter_by(status='active').order_by(Campaign.priority, Campaign.name).all()

    if request.method == 'POST':
        file = request.files.get('file')
        if not file or not file.filename.endswith(('.xlsx', '.xls', '.csv')):
            flash('Please upload a valid Excel or CSV file.', 'danger')
            return redirect(request.url)

        campaign_mode = request.form.get('campaign_mode', 'new')  # 'new' or 'existing'
        campaign_id = None

        try:
            if campaign_mode == 'new':
                camp_name = request.form.get('new_campaign_name', '').strip()
                camp_desc = request.form.get('new_campaign_desc', '').strip()
                camp_priority = int(request.form.get('new_campaign_priority', 99))
                if not camp_name:
                    flash('Please enter a campaign name.', 'danger')
                    return redirect(request.url)
                campaign = Campaign(
                    name=camp_name,
                    description=camp_desc or None,
                    priority=camp_priority,
                    status='active',
                    created_by=current_user.id
                )
                db.session.add(campaign)
                db.session.flush()
                campaign_id = campaign.id
            else:
                campaign_id = int(request.form.get('existing_campaign_id', 0))
                if not campaign_id:
                    flash('Please select a campaign.', 'danger')
                    return redirect(request.url)
                campaign = Campaign.query.get(campaign_id)
                if not campaign:
                    flash('Campaign not found.', 'danger')
                    return redirect(request.url)

            if file.filename.endswith('.csv'):
                df = pd.read_csv(file)
            else:
                df = pd.read_excel(file, header=1)

            df.columns = [str(c).strip() for c in df.columns]
            added, skipped, errors = 0, 0, 0
            duplicates = []

            # Duplicate check is per-campaign: same lazada_id in the SAME campaign = skip.
            # Same seller in a different campaign = allowed (Option A: each campaign is independent).
            existing_ids_in_campaign = {
                r[0] for r in db.session.query(Lead.lazada_id)
                .filter(Lead.campaign_id == campaign_id, Lead.lazada_id.isnot(None)).all()
            }
            existing_phones_in_campaign = {
                r[0] for r in db.session.query(Lead.contact_number)
                .filter(Lead.campaign_id == campaign_id, Lead.contact_number.isnot(None)).all()
            }

            def val(row, *keys):
                for k in keys:
                    v = row.get(k)
                    if v is not None and str(v).strip() not in ('', 'nan', '0', 'None'):
                        return str(v).strip()
                return None

            for _, row in df.iterrows():
                try:
                    seller = val(row, 'Shop Name', 'shop_name', 'Seller Name', 'seller_name', 'Name')
                    if not seller:
                        skipped += 1
                        continue

                    lazada_id = val(row, 'Leads ID', 'leads_id', 'Leads Id', 'lazada_id', 'ID')
                    phone = val(row, 'Contact Number', 'contact_number', 'Mobile', 'Phone')
                    email = val(row, 'Email Address', 'email_address', 'Email', 'email')

                    if lazada_id and lazada_id in existing_ids_in_campaign:
                        duplicates.append({'seller': seller, 'reason': 'Already in this campaign'})
                        skipped += 1
                        continue
                    if phone and phone in existing_phones_in_campaign:
                        duplicates.append({'seller': seller, 'reason': f'Phone {phone} already in this campaign'})
                        skipped += 1
                        continue

                    lead = Lead(
                        seller_name=seller,
                        lazada_id=lazada_id,
                        priority_tier=val(row, 'Priority', 'priority'),
                        project=val(row, 'Project', 'project'),
                        cluster=val(row, 'Cluster', 'cluster'),
                        category=val(row, 'Category', 'category'),
                        link=val(row, 'Link', 'link'),
                        barangay=val(row, 'Barangay', 'barangay'),
                        city=val(row, 'City', 'city'),
                        province=val(row, 'Province', 'province', 'Region', 'region'),
                        address=val(row, 'Complete Address', 'complete_address', 'Address', 'address'),
                        sender_name=val(row, 'Sender Name', 'sender_name'),
                        contact_number=phone,
                        email=email,
                        social_media_link=val(row, 'Social Media Link', 'social_media_link'),
                        batch_ref=file.filename,
                        campaign_id=campaign_id,
                        status='pool'
                    )
                    db.session.add(lead)
                    if lazada_id:
                        existing_ids.add(lazada_id)
                    if phone:
                        existing_phones.add(phone)
                    added += 1
                except Exception:
                    errors += 1

            db.session.commit()
            # Phase 1: auto-enrich all newly imported leads in background
            new_leads = Lead.query.filter_by(campaign_id=campaign.id).filter(
                ~Lead.id.in_(
                    db.session.query(LeadIntelligence.lead_id)
                )
            ).all()
            for _l in new_leads:
                _enrich_lead_background(_l.id, trigger='auto')
            dup_msg = f', {len(duplicates)} duplicate{"s" if len(duplicates)!=1 else ""} skipped' if duplicates else ''
            flash(f'Import complete: {added} leads added to campaign "{campaign.name}"{dup_msg}, {errors} errors. AI enrichment running in background.', 'success')
            return redirect(url_for('campaign_manage'))
        except Exception as e:
            db.session.rollback()
            flash(f'Import failed: {str(e)}', 'danger')

    return render_template('leads/import.html', campaigns=campaigns)


# ─── EXCEL UPDATE MODE ────────────────────────────────────────────────────────

@app.route('/leads/import/update-preview', methods=['POST'])
@login_required
def import_update_preview():
    """Stage 1: Parse Excel and return breakdown without saving."""
    if not current_user.is_manager:
        return jsonify({'error': 'Access denied'}), 403

    file = request.files.get('file')
    if not file or not file.filename.endswith(('.xlsx', '.xls', '.csv')):
        return jsonify({'error': 'Please upload a valid Excel or CSV file.'}), 400

    try:
        if file.filename.endswith('.csv'):
            df = pd.read_csv(file)
        else:
            df = pd.read_excel(file, header=1)

        df.columns = [str(c).strip() for c in df.columns]

        def val(row, *keys):
            for k in keys:
                v = row.get(k)
                if v is not None and str(v).strip() not in ('', 'nan', '0', 'None'):
                    return str(v).strip()
            return None

        new_leads, update_leads, duplicate_leads = [], [], []
        seen_phones = set()

        for _, row in df.iterrows():
            seller = val(row, 'Shop Name', 'shop_name', 'Seller Name', 'seller_name', 'Name')
            if not seller:
                continue

            phone = val(row, 'Contact Number', 'contact_number', 'Mobile', 'Phone')
            lazada_id = val(row, 'Leads ID', 'leads_id', 'Leads Id', 'lazada_id', 'ID')
            project = val(row, 'Project', 'project')
            gabay_name = val(row, 'Gabay Name', 'gabay_name', 'Assigned To', 'assigned_to', 'Gabay')

            # Skip if we already processed this phone in this file
            if phone and phone in seen_phones:
                continue
            if phone:
                seen_phones.add(phone)

            # Match by phone first, then lazada_id
            existing = None
            if phone:
                existing = Lead.query.filter_by(contact_number=phone).filter(
                    Lead.status != 'removed'
                ).first()
            if not existing and lazada_id:
                existing = Lead.query.filter_by(lazada_id=lazada_id).filter(
                    Lead.status != 'removed'
                ).first()

            entry = {
                'seller': seller,
                'phone': phone or '—',
                'project': project or '—',
                'gabay_name': gabay_name or '—',
                'lazada_id': lazada_id,
                'row_data': {k: val(row, k) for k in df.columns}
            }

            if existing:
                entry['lead_id'] = existing.id
                entry['current_status'] = existing.status
                entry['current_campaign'] = existing.campaign.name if existing.campaign else '—'
                entry['current_gabay'] = existing.assigned_gabay.full_name if existing.assigned_gabay else 'Unassigned'
                visit_count = existing.visits.count()
                entry['visit_count'] = visit_count
                if visit_count > 0:
                    duplicate_leads.append(entry)
                else:
                    update_leads.append(entry)
            else:
                new_leads.append(entry)

        return jsonify({
            'new': new_leads,
            'update': update_leads,
            'duplicate': duplicate_leads,
            'total': len(new_leads) + len(update_leads) + len(duplicate_leads)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/leads/import/update-confirm', methods=['POST'])
@login_required
def import_update_confirm():
    """Stage 2: Apply the update — create new, update no-visit, skip or reassign duplicates."""
    if not current_user.is_manager:
        return jsonify({'error': 'Access denied'}), 403

    try:
        data = request.get_json()
        campaign_id = data.get('campaign_id')
        file_data = data.get('rows', [])          # all rows from preview
        duplicate_action = data.get('duplicate_action', 'skip')  # 'skip' or 'reassign'

        campaign = Campaign.query.get(campaign_id) if campaign_id else None

        created, updated, reassigned, skipped = 0, 0, 0, 0

        for item in file_data:
            action = item.get('action')  # 'new', 'update', 'duplicate'
            lead_id = item.get('lead_id')
            seller = item.get('seller')
            phone = item.get('phone') if item.get('phone') != '—' else None
            lazada_id = item.get('lazada_id')
            row_data = item.get('row_data', {})
            gabay_name = item.get('gabay_name') if item.get('gabay_name') != '—' else None

            # Resolve gabay user
            gabay_user = None
            if gabay_name:
                gabay_user = User.query.filter(
                    User.full_name.ilike(f'%{gabay_name}%'),
                    User.role == 'gabay',
                    User.is_active == True
                ).first()

            def get_val(key, *aliases):
                v = row_data.get(key)
                if v and str(v) not in ('', 'nan', 'None'):
                    return str(v).strip()
                for a in aliases:
                    v = row_data.get(a)
                    if v and str(v) not in ('', 'nan', 'None'):
                        return str(v).strip()
                return None

            if action == 'new':
                lead = Lead(
                    seller_name=seller,
                    lazada_id=lazada_id,
                    priority_tier=get_val('Priority'),
                    project=get_val('Project'),
                    cluster=get_val('Cluster'),
                    category=get_val('Category'),
                    link=get_val('Link'),
                    barangay=get_val('Barangay'),
                    city=get_val('City'),
                    province=get_val('Province'),
                    address=get_val('Complete Address'),
                    sender_name=get_val('Sender Name'),
                    contact_number=phone,
                    email=get_val('Email Address'),
                    social_media_link=get_val('Social Media Link'),
                    batch_ref='update_mode',
                    campaign_id=campaign_id,
                    status='pool'
                )
                if gabay_user:
                    lead.gabay_id = gabay_user.id
                    lead.status = 'assigned'
                    lead.assigned_at = datetime.utcnow()
                db.session.add(lead)
                created += 1

            elif action == 'update':
                lead = Lead.query.get(lead_id)
                if lead:
                    if campaign_id:
                        lead.campaign_id = campaign_id
                    if gabay_user:
                        lead.gabay_id = gabay_user.id
                        if lead.status == 'pool':
                            lead.status = 'assigned'
                        lead.assigned_at = datetime.utcnow()
                    proj = get_val('Project')
                    if proj:
                        lead.project = proj
                    cluster = get_val('Cluster')
                    if cluster:
                        lead.cluster = cluster
                    updated += 1

            elif action == 'duplicate':
                if duplicate_action == 'reassign':
                    lead = Lead.query.get(lead_id)
                    if lead and gabay_user:
                        lead.gabay_id = gabay_user.id
                        lead.assigned_at = datetime.utcnow()
                        reassigned += 1
                    elif lead and campaign_id:
                        lead.campaign_id = campaign_id
                        reassigned += 1
                    else:
                        skipped += 1
                else:
                    skipped += 1

        db.session.commit()

        # Notify all managers about skipped duplicates (sellers already visited)
        skipped_items = [r for r in file_data if r.get('action') == 'duplicate' and duplicate_action == 'skip']
        if skipped_items:
            camp_name = campaign.name if campaign else 'Unknown Campaign'
            dup_lines = '\n'.join(
                f"• {r['seller']} ({r.get('phone','—')}) — {r.get('visit_count',0)} visit(s), currently in {r.get('current_campaign','—')}"
                for r in skipped_items[:20]
            )
            if len(skipped_items) > 20:
                dup_lines += f'\n…and {len(skipped_items)-20} more'
            notif_msg = (
                f"{len(skipped_items)} seller(s) from your upload were already visited in the system "
                f"and were NOT imported to {camp_name}.\n\n{dup_lines}"
            )
            managers = User.query.filter(User.role.in_(['manager', 'supervisor']), User.is_active == True).all()
            for mgr in managers:
                db.session.add(Notification(
                    user_id=mgr.id,
                    type='import_duplicates',
                    title=f'⚠️ {len(skipped_items)} Duplicate(s) Skipped — {camp_name}',
                    message=notif_msg,
                    link='/leads/import'
                ))
            db.session.commit()

        # Background enrich any new leads
        new_db_leads = Lead.query.filter_by(campaign_id=campaign_id, status='pool').filter(
            ~Lead.id.in_(db.session.query(LeadIntelligence.lead_id))
        ).all() if campaign_id else []
        for _l in new_db_leads:
            _enrich_lead_background(_l.id, trigger='auto')

        # Telegram alert for power users
        camp_label = campaign.name if campaign else 'No Campaign'
        _notify_managers_telegram(
            f"📥 *Lead Upload Complete*\n"
            f"👤 By: {current_user.full_name}\n"
            f"📋 Campaign: {camp_label}\n"
            f"✅ Added: {created} · 🔄 Updated: {updated} · ⏭ Skipped: {skipped}"
        )

        return jsonify({
            'created': created,
            'updated': updated,
            'reassigned': reassigned,
            'skipped': skipped,
            'dup_notif_sent': len(skipped_items) if skipped_items else 0
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/leads/<int:lead_id>')
@login_required
def lead_detail(lead_id):
    lead = Lead.query.get_or_404(lead_id)
    if current_user.role == 'gabay' and lead.gabay_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('leads'))
    visits = lead.visits.order_by(Visit.visited_at.desc()).all()
    gabay_users = User.query.filter_by(role='gabay', is_active=True).all()
    assignment_history = LeadAssignmentHistory.query.filter_by(lead_id=lead_id)\
        .order_by(LeadAssignmentHistory.assigned_at.desc()).all()
    for h in assignment_history:
        h.gabay_user = User.query.get(h.gabay_id)
        h.assigned_by_user = User.query.get(h.assigned_by)
    return render_template('leads/detail.html', lead=lead, visits=visits,
                           gabay_users=gabay_users, assignment_history=assignment_history)


@app.route('/leads/<int:lead_id>/assign', methods=['POST'])
@login_required
def assign_lead(lead_id):
    if not current_user.is_supervisor:
        return jsonify({'error': 'Access denied'}), 403
    lead = Lead.query.get_or_404(lead_id)
    gabay_id = request.form.get('gabay_id', type=int)
    gabay = User.query.get_or_404(gabay_id)
    lead.gabay_id = gabay_id
    lead.assigned_at = datetime.utcnow()
    if lead.status == 'pool':
        lead.status = 'assigned'
    history = LeadAssignmentHistory(lead_id=lead_id, gabay_id=gabay_id, assigned_by=current_user.id)
    db.session.add(history)
    notif = Notification(
        user_id=gabay_id, type='new_assignment',
        title='New lead assigned to you',
        message=f'{lead.seller_name} ({lead.city or "—"}) has been assigned to you.',
        link=f'/gabay/app/lead/{lead_id}', related_lead_id=lead_id
    )
    db.session.add(notif)
    db.session.commit()
    flash(f'Lead assigned to {gabay.full_name}.', 'success')
    return redirect(request.referrer or url_for('lead_detail', lead_id=lead_id))


@app.route('/leads/bulk-assign', methods=['POST'])
@login_required
def bulk_assign():
    if not current_user.is_supervisor:
        flash('Access denied.', 'danger')
        return redirect(url_for('leads'))
    lead_ids = request.form.getlist('lead_ids', type=int)
    gabay_id = request.form.get('gabay_id', type=int)
    if not lead_ids or not gabay_id:
        flash('Select leads and a Gabay to assign.', 'warning')
        return redirect(url_for('leads'))
    gabay = User.query.get_or_404(gabay_id)
    for lid in lead_ids:
        lead = Lead.query.get(lid)
        if lead:
            lead.gabay_id = gabay_id
            lead.assigned_at = datetime.utcnow()
            if lead.status == 'pool':
                lead.status = 'assigned'
            db.session.add(LeadAssignmentHistory(lead_id=lid, gabay_id=gabay_id, assigned_by=current_user.id))
    db.session.commit()
    flash(f'{len(lead_ids)} leads assigned to {gabay.full_name}.', 'success')
    return redirect(url_for('leads'))


@app.route('/leads/<int:lead_id>/status', methods=['POST'])
@login_required
def update_lead_status(lead_id):
    lead = Lead.query.get_or_404(lead_id)
    new_status = request.form.get('status')
    allowed = ['attempting', 'negotiation', 'registration', 'live', 'matched', 'closed']
    if new_status in allowed:
        lead.status = new_status
        db.session.commit()
        flash(f'Lead status updated to {lead.status_label}.', 'success')
    return redirect(request.referrer or url_for('lead_detail', lead_id=lead_id))


# ─── VISITS ──────────────────────────────────────────────────────────────────

@app.route('/visits')
@login_required
def visits():
    page = request.args.get('page', 1, type=int)
    campaign_id = request.args.get('campaign_id', type=int)
    query = Visit.query
    if current_user.role == 'gabay':
        query = query.filter_by(gabay_id=current_user.id)
    if campaign_id:
        query = query.join(Lead, Visit.lead_id == Lead.id).filter(Lead.campaign_id == campaign_id)
    pagination = query.order_by(Visit.visited_at.desc()).paginate(page=page, per_page=20, error_out=False)
    campaigns = Campaign.query.order_by(Campaign.priority, Campaign.name).all()
    return render_template('visits/list.html', pagination=pagination,
                           campaigns=campaigns, campaign_id=campaign_id)


@app.route('/visits/backfill', methods=['GET', 'POST'])
@login_required
def visits_backfill():
    if not current_user.is_supervisor:
        flash('Access denied.', 'danger')
        return redirect(url_for('visits'))
    gabay_users = User.query.filter_by(role='gabay', is_active=True).order_by(User.full_name).all()
    if request.method == 'POST':
        rows_saved = 0
        rows_skipped = 0
        outcome_customs = request.form.getlist('outcome_custom')
        entries = zip(
            request.form.getlist('gabay_id'),
            request.form.getlist('lead_id'),
            request.form.getlist('visit_date'),
            request.form.getlist('visit_time'),
            request.form.getlist('outcome'),
            outcome_customs + [''] * 200,
            request.form.getlist('notes'),
            request.form.getlist('new_status'),
        )
        for gabay_id, lead_id, visit_date, visit_time, outcome, outcome_custom, notes, new_status in entries:
            if outcome == '__other__':
                outcome = outcome_custom.strip() or 'other'
            if not gabay_id or not lead_id or not outcome or not visit_date:
                rows_skipped += 1
                continue
            try:
                dt_str = f"{visit_date} {visit_time or '08:00'}"
                visited_at = datetime.strptime(dt_str, '%Y-%m-%d %H:%M')
                visit = Visit(
                    lead_id=int(lead_id),
                    gabay_id=int(gabay_id),
                    visited_at=visited_at,
                    outcome=outcome,
                    notes=notes or '',
                    gps_lat=None, gps_lng=None,
                    gps_address='Manual entry by supervisor',
                )
                db.session.add(visit)
                lead = Lead.query.get(int(lead_id))
                if lead and new_status and new_status != '__keep__':
                    lead.status = new_status
                    if new_status in ('assigned', 'attempting', 'negotiation', 'registration') and not lead.assigned_at:
                        lead.assigned_at = visited_at
                rows_saved += 1
            except Exception:
                rows_skipped += 1
        db.session.commit()
        flash(f'{rows_saved} visit(s) saved successfully.{(" " + str(rows_skipped) + " row(s) skipped.") if rows_skipped else ""}', 'success')
        return redirect(url_for('visits_backfill'))
    return render_template('visits/backfill.html', gabay_users=gabay_users)


@app.route('/visits/backfill/leads-json')
@login_required
def backfill_leads_json():
    if not current_user.is_supervisor:
        return jsonify([])
    gabay_id = request.args.get('gabay_id', type=int)
    if not gabay_id:
        return jsonify([])
    leads = Lead.query.filter(
        Lead.gabay_id == gabay_id,
        Lead.status.in_(['assigned', 'attempting', 'negotiation', 'registration', 'live'])
    ).order_by(Lead.seller_name).all()
    return jsonify([{'id': l.id, 'name': l.seller_name, 'city': l.city or '', 'status': l.status} for l in leads])


@app.route('/gabay/app/scan-shop', methods=['POST'])
@login_required
def scan_shop():
    if current_user.role not in ('gabay', 'admin', 'manager', 'supervisor', 'superadmin'):
        return jsonify({'error': 'Unauthorized'}), 403

    photo = request.files.get('photo')
    if not photo:
        return jsonify({'error': 'No photo uploaded'}), 400

    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        return jsonify({'error': 'Shop scanner not configured. Ask your supervisor to set ANTHROPIC_API_KEY.'}), 503

    try:
        import anthropic, base64
        img_bytes = photo.read()
        img_b64   = base64.standard_b64encode(img_bytes).decode('utf-8')
        mime      = photo.content_type or 'image/jpeg'

        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model='claude-opus-4-8',
            max_tokens=512,
            messages=[{
                'role': 'user',
                'content': [
                    {
                        'type': 'image',
                        'source': {'type': 'base64', 'media_type': mime, 'data': img_b64},
                    },
                    {
                        'type': 'text',
                        'text': (
                            'You are a field sales assistant for Lazada Philippines. '
                            'Look at this photo of a shop, storefront, or business card. '
                            'Extract the following details if visible. '
                            'Return ONLY a JSON object with these exact keys (use null if not found):\n'
                            '{\n'
                            '  "seller_name": "business/shop name",\n'
                            '  "contact_number": "phone number",\n'
                            '  "email": "email address",\n'
                            '  "address": "full street address",\n'
                            '  "barangay": "barangay name",\n'
                            '  "city": "city name",\n'
                            '  "category": "product category (e.g. Food, Fashion, Electronics, Beauty, etc.)",\n'
                            '  "social_media": "Facebook page or TikTok handle if visible",\n'
                            '  "notes": "any other useful detail about the business"\n'
                            '}\n'
                            'Return only the JSON, no other text.'
                        )
                    }
                ]
            }]
        )

        import json as _json
        raw = msg.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith('```'):
            raw = raw.split('```')[1]
            if raw.startswith('json'):
                raw = raw[4:]
        data = _json.loads(raw.strip())
        return jsonify({'success': True, 'data': data})

    except Exception as e:
        return jsonify({'error': f'Scan failed: {str(e)}'}), 500


@app.route('/gabay/app/new-lead', methods=['GET', 'POST'])
@login_required
def gabay_new_lead():
    if current_user.role not in ('gabay', 'admin', 'manager', 'supervisor', 'superadmin'):
        return redirect(url_for('gabay_app_leads'))

    if request.method == 'POST':
        seller_name = request.form.get('seller_name', '').strip()
        if not seller_name:
            flash('Shop name is required.', 'danger')
            return redirect(url_for('gabay_new_lead'))

        p1 = _priority1_campaign()
        lead = Lead(
            seller_name    = seller_name,
            contact_number = request.form.get('contact_number') or None,
            email          = request.form.get('email') or None,
            address        = request.form.get('address') or None,
            barangay       = request.form.get('barangay') or None,
            city           = request.form.get('city') or None,
            category       = request.form.get('category') or None,
            notes          = request.form.get('notes') or None,
            link           = request.form.get('social_media') or None,
            status         = 'assigned',
            gabay_id       = current_user.id,
            campaign_id    = p1.id if p1 else None,
            assigned_at    = datetime.utcnow(),
            imported_at    = datetime.utcnow(),
        )
        db.session.add(lead)
        db.session.commit()
        flash(f'New lead "{seller_name}" added successfully!', 'success')
        return redirect(url_for('gabay_app_leads'))

    return render_template('gabay_app/new_lead.html')


@app.route('/gabay/app/voice-transcribe', methods=['POST'])
@login_required
def voice_transcribe():
    if current_user.role not in ('gabay', 'admin', 'manager', 'supervisor', 'superadmin'):
        return jsonify({'error': 'Unauthorized'}), 403

    audio_file = request.files.get('audio')
    if not audio_file:
        return jsonify({'error': 'No audio file'}), 400

    openai_key = os.environ.get('OPENAI_API_KEY', '')
    if not openai_key:
        return jsonify({'error': 'Voice feature not configured. Ask your supervisor to set OPENAI_API_KEY.'}), 503

    # ── Step 1: Transcribe with Whisper (auto-detects language) ──────────────
    try:
        import openai as _openai, httpx as _httpx
        # Use a plain httpx client so Railway's HTTPS_PROXY env var doesn't get
        # injected as a 'proxies' kwarg — removed in openai-python >= 1.x
        client = _openai.OpenAI(
            api_key=openai_key,
            http_client=_httpx.Client(),
        )
        audio_bytes = audio_file.read()
        import io as _io
        audio_io = _io.BytesIO(audio_bytes)
        ct = audio_file.content_type or ''
        ext = 'mp4' if 'mp4' in ct else 'ogg' if 'ogg' in ct else 'm4a' if 'm4a' in ct else 'webm'
        audio_io.name = f'voice.{ext}'
        transcript = client.audio.transcriptions.create(
            model='whisper-1',
            file=audio_io,
            language=None,  # auto-detect: Tagalog, Bisaya, Chinese, English, Taglish
            prompt=(
                'Field agent in Philippines reporting a seller visit. '
                'May speak Tagalog, English, Bisaya/Cebuano, Mandarin Chinese, or mixed. '
                'Terms: interesado, gusto, nag-register, wala, hindi, follow up, mag-register, '
                'negotiation, callback, tawagan, babalik, interested, 感兴趣, 注册, 拒绝.'
            )
        )
        text = transcript.text.strip()
    except Exception as e:
        err_str = str(e)
        if '429' in err_str or 'quota' in err_str.lower() or 'billing' in err_str.lower():
            return jsonify({'error': 'Voice check-in is temporarily unavailable (API quota reached). Please fill the form manually and inform your supervisor.'}), 503
        if '401' in err_str or 'invalid' in err_str.lower() and 'key' in err_str.lower():
            return jsonify({'error': 'Voice feature not configured correctly. Please inform your supervisor.'}), 503
        return jsonify({'error': f'Transcription failed: {err_str}'}), 500

    # ── Step 2: Parse with Claude — extract all structured fields ─────────────
    gid = current_user.id
    my_leads = Lead.query.filter(
        Lead.gabay_id == gid,
        Lead.status.in_(['assigned', 'attempting', 'negotiation', 'registration'])
    ).all()
    seller_list = [{'id': l.id, 'name': l.seller_name, 'city': l.city or ''} for l in my_leads]
    today_pht = (datetime.utcnow() + timedelta(hours=8)).strftime('%Y-%m-%d')

    parsed = {}
    anthropic_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if anthropic_key:
        try:
            import anthropic as _anthropic
            import re as _re
            ac = _anthropic.Anthropic(api_key=anthropic_key)
            sellers_json = json.dumps(seller_list[:40], ensure_ascii=False)
            msg = ac.messages.create(
                model='claude-haiku-4-5-20251001',
                max_tokens=600,
                messages=[{'role': 'user', 'content': f"""You are an AI assistant for LSAMS, a Lazada Seller Activation System in the Philippines.
A Gabay (field agent) recorded this voice note after visiting a seller:

TRANSCRIPT: "{text}"

TODAY (PHT): {today_pht}
GABAY'S LEADS: {sellers_json}

The agent may speak Tagalog, English, Bisaya/Cebuano, Chinese, or a mix. Extract:

- outcome: one of [interested, not_interested, callback, follow_up, not_home, rejected, registered] or null
- new_status: one of [attempting, negotiation, registration, live, matched, closed] or null (only if clearly upgrading status)
- follow_up_date: "YYYY-MM-DD" computed from today {today_pht} (e.g. "next Monday" → actual date), or null
- notes: clean 1-2 sentence English summary of what happened
- seller_id: integer id from GABAY'S LEADS that best matches who was visited, or null
- seller_confidence: "high" (name clearly matches), "medium" (partial), "low" (guessing/not mentioned)
- unclear: true if outcome or seller is genuinely ambiguous

Return ONLY valid JSON, nothing else."""}]
            )
            raw = msg.content[0].text.strip()
            m = _re.search(r'\{.*\}', raw, _re.DOTALL)
            if m:
                parsed = json.loads(m.group())
        except Exception:
            pass

    # Fallback keyword detection if Claude unavailable
    if not parsed.get('outcome'):
        parsed['outcome'] = _parse_outcome(text)

    # ── Step 3: Build seller candidates for confirmation UI ───────────────────
    seller_candidates = []
    matched_id = parsed.get('seller_id')
    confidence = parsed.get('seller_confidence', 'low')

    if matched_id and confidence == 'high':
        hit = next((s for s in seller_list if s['id'] == matched_id), None)
        if hit:
            seller_candidates = [hit]
    else:
        # Include Claude's best guess + fuzzy fragment matches
        candidates = {}
        if matched_id:
            hit = next((s for s in seller_list if s['id'] == matched_id), None)
            if hit:
                candidates[hit['id']] = hit
        # Fragment match on transcript words
        words = [w for w in text.lower().split() if len(w) > 2]
        for s in seller_list:
            name_lower = s['name'].lower()
            score = sum(1 for w in words if w in name_lower)
            if score > 0 and s['id'] not in candidates:
                candidates[s['id']] = s
            if len(candidates) >= 3:
                break
        seller_candidates = list(candidates.values())[:3]

    return jsonify({
        'text': text,
        'outcome': parsed.get('outcome'),
        'new_status': parsed.get('new_status'),
        'follow_up_date': parsed.get('follow_up_date'),
        'notes': parsed.get('notes') or text,
        'seller_id': matched_id,
        'seller_confidence': confidence,
        'seller_candidates': seller_candidates,
        'unclear': parsed.get('unclear', False),
    })


def _parse_outcome(text):
    t = text.lower()
    for kw in ['register', 'nag-register', 'sign up', 'signed up', 'na-onboard', 'live na', '注册']:
        if kw in t: return 'registered'
    for kw in ['ayaw', 'hindi interesado', 'not interested', 'rejected', 'wag na', 'hindi na', '拒绝']:
        if kw in t: return 'rejected'
    for kw in ['wala', 'walang tao', 'not home', 'closed', 'nakasirado', 'store close']:
        if kw in t: return 'not_home'
    for kw in ['tatawag', 'call back', 'callback', 'tawagan', 'magtatawag', '回电']:
        if kw in t: return 'callback'
    for kw in ['interested', 'interesado', 'gusto', 'willing', 'pwede', '感兴趣']:
        if kw in t: return 'interested'
    for kw in ['follow up', 'babalik', 'bumalik', 'susunod', 'next time', 'revisit']:
        if kw in t: return 'follow_up'
    return ''


@app.route('/gabay/app/plan-route', methods=['GET', 'POST'])
@login_required
def gabay_plan_route():
    if current_user.role not in ('gabay', 'admin', 'manager', 'supervisor', 'superadmin'):
        return redirect(url_for('gabay_home'))

    gid = current_user.id
    maps_key = os.environ.get('GOOGLE_MAPS_API_KEY', '')
    p1 = _priority1_campaign()

    # Fetch today's unvisited / priority leads that have an address (priority1 campaign only)
    from datetime import date as _date
    route_q = Lead.query.filter(
        Lead.gabay_id == gid,
        Lead.status.in_(['assigned', 'attempting', 'negotiation', 'registration']),
        Lead.address != None,
        Lead.address != ''
    )
    if p1:
        route_q = route_q.filter(Lead.campaign_id == p1.id)
    active_leads = route_q.all()

    if not active_leads:
        return render_template('gabay_app/route.html',
            stops=[], maps_url='', optimized=False,
            error='No leads with addresses found. Add addresses to your leads first.',
            maps_key=maps_key)

    # Sort locally by conversion_score desc as default order
    active_leads.sort(key=lambda l: l.conversion_score, reverse=True)
    # Limit to top 10 for route optimization (Maps API limit)
    route_leads = active_leads[:10]

    optimized_order = list(range(len(route_leads)))
    maps_url = ''
    error = None

    import urllib.parse
    import urllib.request

    if maps_key and len(route_leads) >= 2:
        try:

            origin = route_leads[0].address
            destination = route_leads[-1].address
            waypoints_raw = [l.address for l in route_leads[1:-1]]
            waypoints_str = 'optimize:true|' + '|'.join(
                urllib.parse.quote(w) for w in waypoints_raw
            ) if waypoints_raw else ''

            url = (
                'https://maps.googleapis.com/maps/api/directions/json'
                f'?origin={urllib.parse.quote(origin)}'
                f'&destination={urllib.parse.quote(destination)}'
                + (f'&waypoints={waypoints_str}' if waypoints_str else '')
                + f'&key={maps_key}'
                + '&region=PH'
            )
            with urllib.request.urlopen(url, timeout=8) as resp:
                data = json.loads(resp.read().decode())

            if data.get('status') == 'OK':
                route = data['routes'][0]
                wp_order = route.get('waypoint_order', [])
                # Rebuild order: origin(0) + optimized waypoints + destination(last)
                middle = [route_leads[i + 1] for i in wp_order] if wp_order else route_leads[1:-1]
                route_leads = [route_leads[0]] + middle + [route_leads[-1]]
                optimized_order = list(range(len(route_leads)))
            else:
                error = f"Maps API: {data.get('status', 'unknown error')}"
        except Exception as e:
            error = f'Route optimization unavailable: {str(e)}'

    # Build Google Maps navigation deep-link for all stops
    if route_leads:
        wps = '/'.join(urllib.parse.quote(l.address) for l in route_leads)
        maps_url = f'https://www.google.com/maps/dir/{wps}'

    # Build Waze link for first stop only
    waze_url = ''
    if route_leads:
        waze_url = f'https://waze.com/ul?q={urllib.parse.quote(route_leads[0].address)}&navigate=yes'

    # ── RADAR: unassigned pool sellers in the same cities ──────────────
    radar_leads = []
    gabay_cities = current_user.city_list  # normalized lowercase list
    if gabay_cities:
        pool_candidates = Lead.query.filter(
            Lead.status == 'pool',
            Lead.gabay_id == None
        ).all()
        for pl in pool_candidates:
            if pl.city and pl.city.strip().lower() in gabay_cities:
                radar_leads.append(pl)
        # Sort by priority tier then conversion score
        tier_order = {'P0': 0, 'P1': 1, 'P2': 2, 'P3': 3}
        radar_leads.sort(key=lambda l: (tier_order.get(l.priority_tier or 'P3', 3), -l.conversion_score))
        radar_leads = radar_leads[:8]  # top 8 nearby unassigned

    return render_template('gabay_app/route.html',
        stops=route_leads, maps_url=maps_url, waze_url=waze_url,
        optimized=(maps_key != '' and error is None),
        error=error, maps_key=maps_key,
        total_leads=len(active_leads),
        radar_leads=radar_leads)


@app.route('/visits/new/<int:lead_id>', methods=['GET', 'POST'])
@login_required
def new_visit(lead_id):
    lead = Lead.query.get_or_404(lead_id)
    if request.method == 'POST':
        visit = Visit(
            lead_id=lead_id,
            gabay_id=current_user.id,
            gps_lat=request.form.get('gps_lat', type=float),
            gps_lng=request.form.get('gps_lng', type=float),
            gps_address=request.form.get('gps_address', ''),
            outcome=request.form.get('outcome'),
            notes=request.form.get('notes', ''),
            follow_up_date=datetime.strptime(request.form['follow_up_date'], '%Y-%m-%d').date()
                if request.form.get('follow_up_date') else None,
        )
        db.session.add(visit)
        # Update lead status based on outcome
        outcome = request.form.get('outcome')
        if outcome == 'interested' and lead.status in ('assigned', 'attempting'):
            lead.status = 'negotiation'
        elif lead.status == 'assigned':
            lead.status = 'attempting'
        db.session.commit()
        flash('Visit recorded successfully.', 'success')
        return redirect(url_for('lead_detail', lead_id=lead_id))
    return render_template('visits/new.html', lead=lead)


# ─── REGISTRATIONS ───────────────────────────────────────────────────────────

@app.route('/registrations')
@login_required
def registrations():
    page = request.args.get('page', 1, type=int)
    status_filter = request.args.get('status', '')
    campaign_id = request.args.get('campaign_id', type=int)
    query = Registration.query.join(Lead)
    if current_user.role == 'gabay':
        query = query.filter(Lead.gabay_id == current_user.id)
    if campaign_id:
        query = query.filter(Lead.campaign_id == campaign_id)
    if status_filter:
        query = query.filter(Registration.status == status_filter)
    pagination = query.order_by(Registration.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    campaigns = Campaign.query.order_by(Campaign.priority, Campaign.name).all()
    return render_template('registrations/list.html', pagination=pagination,
                           status_filter=status_filter, campaigns=campaigns, campaign_id=campaign_id)


@app.route('/registrations/new/<int:lead_id>', methods=['GET', 'POST'])
@login_required
def new_registration(lead_id):
    lead = Lead.query.get_or_404(lead_id)
    if lead.registration:
        flash('Registration already exists for this lead.', 'warning')
        return redirect(url_for('registration_detail', reg_id=lead.registration.id))
    if request.method == 'POST':
        reg = Registration(
            lead_id=lead_id,
            has_dti='has_dti' in request.form,
            has_permit='has_permit' in request.form,
            has_gov_id='has_gov_id' in request.form,
            has_tin='has_tin' in request.form,
            has_bank='has_bank' in request.form,
            notes=request.form.get('notes', ''),
            status='draft'
        )
        db.session.add(reg)
        lead.status = 'registration'
        db.session.commit()
        flash('Registration created.', 'success')
        return redirect(url_for('registration_detail', reg_id=reg.id))
    return render_template('registrations/new.html', lead=lead)


@app.route('/registrations/<int:reg_id>')
@login_required
def registration_detail(reg_id):
    reg = Registration.query.get_or_404(reg_id)
    return render_template('registrations/detail.html', reg=reg)


@app.route('/registrations/<int:reg_id>/submit', methods=['POST'])
@login_required
def submit_registration(reg_id):
    reg = Registration.query.get_or_404(reg_id)
    reg.status = 'pending'
    reg.submitted_at = datetime.utcnow()
    db.session.commit()
    flash('Registration submitted for review.', 'success')
    return redirect(url_for('registration_detail', reg_id=reg_id))


@app.route('/registrations/<int:reg_id>/approve', methods=['POST'])
@login_required
def approve_registration(reg_id):
    if not current_user.is_manager:
        flash('Access denied.', 'danger')
        return redirect(url_for('registrations'))
    reg = Registration.query.get_or_404(reg_id)
    is_vw = 'is_vw' in request.form
    is_vw_rrld = 'is_vw_rrld' in request.form
    reg.status = 'approved'
    reg.reviewed_at = datetime.utcnow()
    reg.activated_at = datetime.utcnow()
    reg.is_vw = is_vw
    reg.is_vw_rrld = is_vw_rrld
    reg.lead.status = 'matched' if (is_vw or is_vw_rrld) else 'live'
    db.session.commit()
    flash('Registration approved. Seller is now LIVE.', 'success')
    return redirect(url_for('registration_detail', reg_id=reg_id))


@app.route('/registrations/<int:reg_id>/reject', methods=['POST'])
@login_required
def reject_registration(reg_id):
    if not current_user.is_manager:
        flash('Access denied.', 'danger')
        return redirect(url_for('registrations'))
    reg = Registration.query.get_or_404(reg_id)
    reg.status = 'rejected'
    reg.reviewed_at = datetime.utcnow()
    reg.rejected_at = datetime.utcnow()
    reg.rejection_reason = request.form.get('reason', '')
    db.session.commit()
    flash('Registration rejected.', 'warning')
    return redirect(url_for('registration_detail', reg_id=reg_id))


# ─── GABAY MANAGEMENT ────────────────────────────────────────────────────────

@app.route('/gabay')
@login_required
def gabay_list():
    if not current_user.is_supervisor:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    agents = User.query.filter_by(role='gabay').order_by(User.full_name).all()
    stats = {}
    for a in agents:
        stats[a.id] = {
            'total': Lead.query.filter_by(gabay_id=a.id).count(),
            'live': Lead.query.filter_by(gabay_id=a.id, status='live').count(),
            'matched': Lead.query.filter_by(gabay_id=a.id, status='matched').count(),
            'visits': Visit.query.filter_by(gabay_id=a.id).count(),
        }
    return render_template('gabay/list.html', agents=agents, stats=stats)


@app.route('/gabay/new', methods=['GET', 'POST'])
@login_required
def new_gabay():
    if not current_user.is_admin:
        flash('Access denied.', 'danger')
        return redirect(url_for('gabay_list'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
            return redirect(request.url)
        user = User(
            username=username,
            full_name=request.form.get('full_name', '').strip(),
            email=request.form.get('email', '').strip(),
            role=request.form.get('role', 'gabay'),
            mobile=request.form.get('mobile', '').strip() or None,
            mobile2=request.form.get('mobile2', '').strip() or None,
            viber=request.form.get('viber', '').strip() or None,
            facebook=request.form.get('facebook', '').strip() or None,
            house_number=request.form.get('house_number', '').strip() or None,
            street=request.form.get('street', '').strip() or None,
            barangay=request.form.get('barangay', '').strip() or None,
            city_address=request.form.get('city_address', '').strip() or None,
            assigned_city=request.form.get('assigned_city', '').strip() or None,
        )
        user.set_password(request.form.get('password', ''))
        db.session.add(user)
        db.session.commit()
        flash(f'User {user.full_name} created.', 'success')
        return redirect(url_for('gabay_list'))
    return render_template('gabay/new.html')


@app.route('/gabay/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_gabay(user_id):
    if not current_user.is_admin:
        flash('Access denied.', 'danger')
        return redirect(url_for('gabay_list'))
    u = User.query.get_or_404(user_id)
    if request.method == 'POST':
        u.full_name = request.form.get('full_name', '').strip()
        u.email = request.form.get('email', '').strip()
        u.role = request.form.get('role', u.role)
        u.mobile = request.form.get('mobile', '').strip() or None
        u.mobile2 = request.form.get('mobile2', '').strip() or None
        u.viber = request.form.get('viber', '').strip() or None
        u.facebook = request.form.get('facebook', '').strip() or None
        u.house_number = request.form.get('house_number', '').strip() or None
        u.street = request.form.get('street', '').strip() or None
        u.barangay = request.form.get('barangay', '').strip() or None
        u.city_address = request.form.get('city_address', '').strip() or None
        u.assigned_city = request.form.get('assigned_city', '').strip() or None
        pw = request.form.get('password', '').strip()
        if pw:
            u.set_password(pw)
        was_active = u.is_active
        u.is_active = 'is_active' in request.form
        if was_active and not u.is_active:
            u.deactivated_at = datetime.utcnow()
        elif not was_active and u.is_active:
            u.deactivated_at = None
        db.session.commit()
        flash(f'{u.full_name} updated.', 'success')
        return redirect(url_for('gabay_list'))
    return render_template('gabay/edit.html', u=u)


# ─── REPORTS ─────────────────────────────────────────────────────────────────

@app.route('/assign')
@login_required
def assign_center():
    if not current_user.is_supervisor:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))

    page = request.args.get('page', 1, type=int)
    search = request.args.get('q', '')
    city_filter = request.args.get('city', '')

    # Only show pool leads from ACTIVE campaigns (exclude archived/legacy)
    campaign_id = request.args.get('campaign_id', type=int)
    active_campaign_ids = [c.id for c in Campaign.query.filter_by(status='active').all()]
    query = Lead.query.filter(Lead.status == 'pool', Lead.campaign_id.in_(active_campaign_ids))
    if campaign_id:
        query = query.filter(Lead.campaign_id == campaign_id)
    if search:
        query = query.filter(or_(
            Lead.seller_name.ilike(f'%{search}%'),
            Lead.sender_name.ilike(f'%{search}%'),
            Lead.contact_number.ilike(f'%{search}%'),
        ))
    if city_filter:
        query = query.filter_by(city=city_filter)

    # Sort: P1 campaign leads first, then by imported_at
    pagination = query.outerjoin(Campaign, Lead.campaign_id == Campaign.id)\
        .order_by(Campaign.priority.asc().nullslast(), Lead.imported_at.asc())\
        .paginate(page=page, per_page=25, error_out=False)
    pool_count_q = Lead.query.filter(Lead.status == 'pool', Lead.campaign_id.in_(active_campaign_ids))
    if campaign_id:
        pool_count_q = pool_count_q.filter(Lead.campaign_id == campaign_id)
    pool_count = pool_count_q.count()

    gabay_users = User.query.filter_by(role='gabay', is_active=True).order_by(User.full_name).all()
    gabay_counts = {}
    for g in gabay_users:
        gabay_counts[g.id] = {
            'total': Lead.query.filter_by(gabay_id=g.id).count(),
            'live': Lead.query.filter_by(gabay_id=g.id, status='live').count(),
            'matched': Lead.query.filter_by(gabay_id=g.id, status='matched').count(),
            'assigned': Lead.query.filter_by(gabay_id=g.id, status='assigned').count(),
        }

    cities = [r[0] for r in db.session.query(Lead.city).filter(Lead.city != None, Lead.city != '').distinct().order_by(Lead.city).all()]
    recent_assigned = Lead.query.filter(Lead.gabay_id != None).order_by(Lead.assigned_at.desc()).limit(20).all()

    # Orphan cities: pool leads whose city already has a Gabay assigned
    # Build city→Gabay map from User.assigned_city
    city_to_gabay = {}
    for g in gabay_users:
        if g.assigned_city:
            for c in [x.strip() for x in g.assigned_city.split(',') if x.strip()]:
                city_to_gabay[c.lower()] = g

    orphan_cities = []
    pool_by_city = db.session.query(Lead.city, db.func.count(Lead.id))\
        .filter(Lead.status == 'pool', Lead.city != None, Lead.city != '',
                Lead.campaign_id.in_(active_campaign_ids))\
        .group_by(Lead.city).all()
    for city, count in pool_by_city:
        gabay = city_to_gabay.get(city.lower())
        if gabay:
            orphan_cities.append((city, count, gabay.full_name, gabay.id))
    orphan_cities.sort(key=lambda x: -x[1])  # highest count first

    campaigns = Campaign.query.filter_by(status='active').order_by(Campaign.priority, Campaign.name).all()
    return render_template('assign/index.html',
        pagination=pagination, pool_leads=pagination.items,
        pool_count=pool_count, gabay_users=gabay_users,
        gabay_counts=gabay_counts, cities=cities,
        recent_assigned=recent_assigned, search=search, city_filter=city_filter,
        orphan_cities=orphan_cities, campaigns=campaigns, campaign_id=campaign_id)


@app.route('/assign/do', methods=['POST'])
@login_required
def do_assign():
    if not current_user.is_supervisor:
        flash('Access denied.', 'danger')
        return redirect(url_for('assign_center'))
    lead_ids = request.form.getlist('lead_ids', type=int)
    gabay_id = request.form.get('gabay_id', type=int)
    if not lead_ids:
        flash('Please select at least one lead to assign.', 'warning')
        return redirect(url_for('assign_center'))
    if not gabay_id:
        flash('Please select a Gabay agent to assign leads to.', 'warning')
        return redirect(url_for('assign_center'))
    gabay = User.query.get_or_404(gabay_id)
    for lid in lead_ids:
        lead = Lead.query.get(lid)
        if lead and lead.status == 'pool':
            lead.gabay_id = gabay_id
            lead.assigned_at = datetime.utcnow()
            lead.status = 'assigned'
            db.session.add(LeadAssignmentHistory(lead_id=lid, gabay_id=gabay_id, assigned_by=current_user.id))
    db.session.commit()
    flash(f'{len(lead_ids)} lead(s) assigned to {gabay.full_name}.', 'success')
    return redirect(url_for('assign_center'))


@app.route('/assign/gabay-leads/<int:gabay_id>')
@login_required
def gabay_leads_json(gabay_id):
    """Return assigned leads for a Gabay as JSON (for reassign panel)."""
    if not current_user.is_supervisor:
        return {'error': 'Access denied'}, 403
    leads = Lead.query.filter_by(gabay_id=gabay_id).order_by(Lead.city, Lead.seller_name).all()
    return jsonify(leads=[{
        'id': l.id,
        'seller': l.seller_name or '—',
        'business': getattr(l, 'business_name', None) or '—',
        'city': l.city or '',
        'phone': l.contact_number or '',
        'category': l.category or '—',
        'status': l.status,
    } for l in leads])


@app.route('/assign/reassign', methods=['POST'])
@login_required
def do_reassign():
    """Move already-assigned leads from one Gabay to another."""
    if not current_user.is_supervisor:
        flash('Access denied.', 'danger')
        return redirect(url_for('assign_center'))
    lead_ids = request.form.getlist('lead_ids', type=int)
    gabay_id = request.form.get('gabay_id', type=int)
    if not lead_ids or not gabay_id:
        flash('Invalid request.', 'warning')
        return redirect(url_for('assign_center'))
    gabay = User.query.get_or_404(gabay_id)
    moved = 0
    for lid in lead_ids:
        lead = Lead.query.get(lid)
        if lead:
            lead.gabay_id = gabay_id
            lead.assigned_at = datetime.utcnow()
            lead.status = 'assigned'
            db.session.add(LeadAssignmentHistory(
                lead_id=lid, gabay_id=gabay_id, assigned_by=current_user.id))
            moved += 1
    db.session.commit()
    flash(f'{moved} lead(s) moved to {gabay.full_name}.', 'success')
    return redirect(url_for('assign_center'))


@app.route('/assign/remaining-city', methods=['POST'])
@login_required
def assign_remaining_city():
    """Assign all pool leads from a specific city to a specific Gabay in one click."""
    if not current_user.is_supervisor:
        flash('Access denied.', 'danger')
        return redirect(url_for('assign_center'))
    city    = request.form.get('city', '').strip()
    gabay_id = request.form.get('gabay_id', type=int)
    if not city or not gabay_id:
        flash('Invalid request.', 'danger')
        return redirect(url_for('assign_center'))
    gabay = User.query.get_or_404(gabay_id)
    leads = Lead.query.filter_by(status='pool', city=city).all()
    for lead in leads:
        lead.gabay_id = gabay_id
        lead.assigned_at = datetime.utcnow()
        lead.status = 'assigned'
        db.session.add(LeadAssignmentHistory(lead_id=lead.id, gabay_id=gabay_id, assigned_by=current_user.id))
    db.session.commit()
    flash(f'{len(leads)} {city} leads assigned to {gabay.full_name}.', 'success')
    return redirect(url_for('assign_center'))


@app.route('/assign/auto', methods=['POST'])
@login_required
def auto_distribute():
    if not current_user.is_supervisor:
        flash('Access denied.', 'danger')
        return redirect(url_for('assign_center'))
    pool_leads = Lead.query.filter_by(status='pool').filter(Lead.is_archived.isnot(True)).order_by(Lead.imported_at.asc()).all()
    gabay_users = User.query.filter_by(role='gabay', is_active=True).order_by(User.full_name).all()
    if not gabay_users:
        flash('No active Gabay agents found. Add agents first.', 'warning')
        return redirect(url_for('assign_center'))
    if not pool_leads:
        flash('No unassigned leads in pool.', 'info')
        return redirect(url_for('assign_center'))
    for i, lead in enumerate(pool_leads):
        g = gabay_users[i % len(gabay_users)]
        lead.gabay_id = g.id
        lead.assigned_at = datetime.utcnow()
        lead.status = 'assigned'
        db.session.add(LeadAssignmentHistory(lead_id=lead.id, gabay_id=g.id, assigned_by=current_user.id))
    db.session.commit()
    flash(f'{len(pool_leads)} leads distributed across {len(gabay_users)} Gabay agents.', 'success')
    return redirect(url_for('assign_center'))


@app.route('/help')
@login_required
def help_page():
    return render_template('help.html')


# ─── SMART ASSIGNMENT MAP ─────────────────────────────────────────────────────

# City coordinates for Metro Manila
CITY_COORDS = {
    'Makati': (14.5547, 121.0244), 'Quezon City': (14.6760, 121.0437),
    'Pasig': (14.5764, 121.0851), 'Taguig': (14.5243, 121.0792),
    'Mandaluyong': (14.5794, 121.0359), 'Manila': (14.5995, 120.9842),
    'Paranaque': (14.4793, 121.0198), 'Parañaque': (14.4793, 121.0198),
    'Las Pinas': (14.4426, 120.9938), 'Las Piñas': (14.4426, 120.9938),
    'Caloocan': (14.7650, 120.9572), 'Marikina': (14.6507, 121.1029),
    'Muntinlupa': (14.4081, 121.0415), 'Valenzuela': (14.7011, 120.9830),
    'Malabon': (14.6628, 120.9573), 'Navotas': (14.6668, 120.9432),
    'San Juan': (14.6000, 121.0300), 'Pateros': (14.5450, 121.0682),
    'Pasay': (14.5378, 120.9972), 'Cainta': (14.5781, 121.1247),
    'Antipolo': (14.6284, 121.1760), 'Taytay': (14.5573, 121.1325),
    'Angono': (14.5234, 121.1540), 'Binangonan': (14.4685, 121.1966),
    'San Mateo': (14.6946, 121.1222), 'Rodriguez': (14.7378, 121.1322),
    'Bacoor': (14.4580, 120.9400), 'Imus': (14.4297, 120.9367),
    'General Trias': (14.3867, 120.8817), 'Dasmarinas': (14.3294, 120.9367),
    'Dasmariñas': (14.3294, 120.9367), 'Cavite City': (14.4791, 120.8965),
    'Trece Martires': (14.2833, 120.8667), 'Silang': (14.2294, 120.9694),
    'Tanza': (14.3919, 120.8508), 'Kawit': (14.4358, 120.9028),
    'Noveleta': (14.4228, 120.8853), 'Rosario': (14.4167, 120.8500),
    'Naic': (14.3178, 120.7681), 'Carmona': (14.3156, 121.0547),
    'General Mariano Alvarez': (14.2981, 121.0033),
    'Indang': (14.1978, 120.8817), 'Pilila': (14.4833, 121.3167),
    'Morong': (14.5236, 121.2397), 'Malolos': (14.8527, 120.8122),
    'Meycauayan': (14.7362, 120.9624), 'San Jose del Monte': (14.8138, 121.0453),
    'Santa Rosa': (14.3122, 121.1114), 'San Pedro': (14.3588, 121.0539),
}

def _haversine_km(lat1, lng1, lat2, lng2):
    import math
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def _city_coords(city_name):
    """Return (lat, lng) for a city or None."""
    if not city_name:
        return None
    for key, coords in CITY_COORDS.items():
        if key.lower() == city_name.lower().strip():
            return coords
    return None

def _gabay_base_coords(gabay_user):
    """Return coords of the gabay's first assigned city."""
    if not gabay_user.assigned_city:
        return None
    first = gabay_user.assigned_city.split(',')[0].strip()
    return _city_coords(first)

def _distance_to_city(gabay_user, city_name):
    """Return km distance from gabay's base to city, or 9999 if unknown."""
    gc = _gabay_base_coords(gabay_user)
    cc = _city_coords(city_name)
    if gc and cc:
        return _haversine_km(gc[0], gc[1], cc[0], cc[1])
    return 9999


@app.route('/smart_assign')
@login_required
def smart_assign():
    if not current_user.is_supervisor:
        flash('Access restricted.', 'error')
        return redirect(url_for('dashboard'))

    pool_leads = Lead.query.filter_by(status='pool').filter(Lead.is_archived.isnot(True)).all()

    # ── Split: leads WITH city vs leads with NO city (excluded from auto-assign)
    no_city_leads = [l for l in pool_leads if not (l.city or '').strip()]
    assignable_leads = [l for l in pool_leads if (l.city or '').strip()]

    # Group assignable leads by city
    city_counts = {}
    for lead in assignable_leads:
        city = lead.city.strip()
        city_counts[city] = city_counts.get(city, 0) + 1

    # All active Gabay
    gabay_users = User.query.filter_by(role='gabay', is_active=True).all()
    gabay_workload = {}
    for g in gabay_users:
        gabay_workload[g.id] = Lead.query.filter(
            Lead.gabay_id == g.id,
            Lead.status.in_(['assigned', 'attempting', 'negotiation', 'registration'])
        ).count()

    # ── Smart Assignment with load balancing
    # Target: distribute leads as evenly as possible across agents
    total_assignable = len(assignable_leads)
    n_gabay = len(gabay_users)
    # Soft cap: each Gabay should get at most (total / n_gabay * 1.3) leads
    # so no single agent gets more than 30% above average
    soft_cap = int((total_assignable / max(n_gabay, 1)) * 1.4) if n_gabay else 9999

    city_data = []
    workload_copy = dict(gabay_workload)  # tracks projected load during planning
    unmatched_cities = []

    for city, count in sorted(city_counts.items(), key=lambda x: -x[1]):
        city_lower = city.lower()

        # 1. Find Gabay who have this city in their territory
        covering = [g for g in gabay_users if city_lower in g.city_list]

        # 2. Multiple Gabay cover same city → SPLIT leads evenly between them
        if covering:
            matched = True
            if len(covering) == 1:
                splits = [(covering[0], count)]
            else:
                # Sort by current workload (lightest first) so overflow goes to least busy
                covering.sort(key=lambda g: workload_copy.get(g.id, 0))
                base = count // len(covering)
                remainder = count % len(covering)
                splits = []
                for i, g in enumerate(covering):
                    chunk = base + (1 if i < remainder else 0)
                    if chunk > 0:
                        splits.append((g, chunk))
        else:
            # 3. No Gabay owns this city → nearest Gabay by GPS distance + load balance
            matched = False
            unmatched_cities.append(city)

            def fallback_score(g):
                dist = _distance_to_city(g, city)
                load = workload_copy.get(g.id, 0)
                return dist + (10000 if load >= soft_cap else 0)

            if gabay_users:
                splits = [(min(gabay_users, key=fallback_score), count)]
            else:
                continue

        coords = _city_coords(city) or (None, None)
        for gabay, chunk in splits:
            dist_km = round(_distance_to_city(gabay, city), 1) if matched else None
            row_key = f"{city}~~{gabay.id}" if len(splits) > 1 else city
            city_data.append({
                'city': city,
                'row_key': row_key,
                'count': chunk,
                'total_city_count': count,
                'split': len(splits) > 1,
                'split_label': f'{len(splits)}-way split' if len(splits) > 1 else '',
                'lat': coords[0] if coords else None,
                'lng': coords[1] if coords else None,
                'suggested_gabay_id': gabay.id,
                'suggested_gabay_name': gabay.full_name,
                'city_matched': matched,
                'dist_km': dist_km,
                'fallback_reason': f'Nearest: {round(_distance_to_city(gabay, city), 1)} km' if not matched else '',
            })
            workload_copy[gabay.id] = workload_copy.get(gabay.id, 0) + chunk

    # ── BALANCING PASS: redistribute overflow from heavy agents to light ones ────
    # Build initial projections
    projected = {g.id: gabay_workload.get(g.id, 0) for g in gabay_users}
    for row in city_data:
        projected[row['suggested_gabay_id']] = projected.get(row['suggested_gabay_id'], 0) + row['count']

    avg_leads = round(total_assignable / max(n_gabay, 1))
    min_guarantee = int(avg_leads * 0.75)  # no agent should get less than 75% of average
    max_cap = int(avg_leads * 1.25)        # no agent should get more than 125% of average

    # Find under-served agents sorted by how far below minimum they are
    under_served = sorted(
        [(g, projected.get(g.id, 0)) for g in gabay_users if projected.get(g.id, 0) < min_guarantee],
        key=lambda x: x[1]  # most under-served first
    )

    gabay_by_id = {g.id: g for g in gabay_users}

    for light_agent, light_count in under_served:
        needed = min_guarantee - projected.get(light_agent.id, 0)
        if needed <= 0:
            continue
        light_coords = _gabay_base_coords(light_agent)

        # Find city rows assigned to heavy agents within 35 km of light agent's base
        # (or any city if no coords available) — sorted by distance
        candidates = []
        for row in city_data:
            heavy_id = row['suggested_gabay_id']
            if heavy_id == light_agent.id:
                continue
            if projected.get(heavy_id, 0) <= avg_leads:
                continue  # this agent is not heavy, don't take from them
            city_coords = (_city_coords(row['city']) or
                           ((row['lat'], row['lng']) if row['lat'] else None))
            if light_coords and city_coords:
                dist = _haversine_km(light_coords[0], light_coords[1],
                                     city_coords[0], city_coords[1])
            else:
                dist = 50  # unknown → treat as medium distance
            if dist > 40:
                continue  # too far to realistically cover
            candidates.append((row, dist))

        candidates.sort(key=lambda x: x[1])

        for row, dist in candidates:
            if needed <= 0:
                break
            # Take at most half of this row (leave the original agent with their half)
            max_take = max(1, row['count'] * (projected.get(row['suggested_gabay_id'], 0) - avg_leads) // avg_leads)
            take = min(needed, max_take, row['count'] - 1)
            if take <= 0:
                continue

            heavy_id = row['suggested_gabay_id']
            heavy_agent = gabay_by_id[heavy_id]

            # Shrink original row
            row['count'] -= take
            # Ensure original row has a unique row_key (for split)
            if '~~' not in row['row_key']:
                row['row_key'] = f"{row['city']}~~{heavy_id}"

            # Add new overflow row for light agent
            city_data.append({
                'city': row['city'],
                'row_key': f"{row['city']}~~{light_agent.id}",
                'count': take,
                'total_city_count': row.get('total_city_count', row['count'] + take),
                'split': True,
                'split_label': f'Overflow · {round(dist, 0):.0f} km',
                'lat': row['lat'],
                'lng': row['lng'],
                'suggested_gabay_id': light_agent.id,
                'suggested_gabay_name': light_agent.full_name,
                'city_matched': False,
                'dist_km': round(dist, 1),
                'fallback_reason': f'Balanced overflow from {heavy_agent.full_name} ({round(dist,1)}km)',
                'is_overflow': True,
            })
            projected[heavy_id] = projected.get(heavy_id, 0) - take
            projected[light_agent.id] = projected.get(light_agent.id, 0) + take
            needed -= take

    avg_leads = round(total_assignable / max(n_gabay, 1))
    gabay_list = [{
        'id': g.id,
        'name': g.full_name,
        'current_leads': gabay_workload.get(g.id, 0),
        'projected_leads': projected.get(g.id, 0),
        'assigned_city': g.assigned_city or '',
    } for g in gabay_users]
    gabay_list.sort(key=lambda x: -x['projected_leads'])

    return render_template('assign/smart.html',
        city_data=city_data,
        gabay_list=gabay_list,
        pool_count=len(pool_leads),
        no_city_leads=no_city_leads,
        unmatched_cities=unmatched_cities,
        assignable_count=len(assignable_leads),
        soft_cap=soft_cap,
        avg_leads=avg_leads,
        total_assignable=total_assignable)


@app.route('/assign/approve-suggestions', methods=['POST'])
@login_required
def confirm_smart_assign():
    if not current_user.is_supervisor:
        flash('Access restricted.', 'error')
        return redirect(url_for('dashboard'))

    import json as _json
    try:
        # assignments format: list of {city, gabay_id, count} objects
        raw = request.form.get('assignments', '[]')
        assignments = _json.loads(raw)
        # Support old dict format {city: gabay_id} for backwards compat
        if isinstance(assignments, dict):
            assignments = [{'city': c, 'gabay_id': gid, 'count': None} for c, gid in assignments.items()]
    except Exception:
        flash('Invalid assignment data.', 'error')
        return redirect(url_for('smart_assign'))

    total = 0
    # Track how many leads of each city have already been assigned (for splits)
    city_assigned_count = {}

    for item in assignments:
        city = (item.get('city') or '').strip()
        gabay_id = item.get('gabay_id')
        alloc = item.get('count')  # None means assign all

        if not city or not gabay_id:
            continue
        gabay = User.query.get(gabay_id)
        if not gabay or gabay.role != 'gabay':
            continue

        base_q = Lead.query.filter(
            Lead.status == 'pool',
            Lead.city == city,
            Lead.city.isnot(None),
            Lead.city != ''
        ).order_by(Lead.id)

        # For split cities: skip already-assigned leads
        skip = city_assigned_count.get(city, 0)
        if alloc is not None:
            leads = base_q.offset(skip).limit(alloc).all()
        else:
            leads = base_q.all()

        for lead in leads:
            lead.gabay_id = gabay_id
            lead.status = 'assigned'
            lead.assigned_at = datetime.utcnow()
            db.session.add(LeadAssignmentHistory(
                lead_id=lead.id, gabay_id=gabay_id,
                assigned_by=current_user.id, assigned_at=datetime.utcnow()
            ))
            total += 1

        city_assigned_count[city] = skip + len(leads)

    db.session.commit()
    no_city_remaining = Lead.query.filter(
        Lead.status == 'pool',
        (Lead.city == None) | (Lead.city == '')
    ).count()
    msg = f'Smart assignment complete: {total} leads assigned.'
    if no_city_remaining:
        msg += f' {no_city_remaining} leads with no city remain in Pool for manual review.'
    flash(msg, 'success')
    return redirect(url_for('assign_center'))


@app.route('/reports')
@login_required
def reports():
    return render_template('reports/index.html')


@app.route('/reports/daily-ops')
@login_required
def report_daily_ops():
    if not current_user.is_supervisor and not current_user.is_lazada:
        flash('Access denied.', 'danger')
        return redirect(url_for('reports'))
    from datetime import timedelta as _td2
    today = date.today()
    target_date = request.args.get('date', today.isoformat())
    try:
        target_dt = date.fromisoformat(target_date)
    except ValueError:
        target_dt = today

    # Campaign filter — default to P1
    p1 = _priority1_campaign()
    campaign_id = request.args.get('campaign_id', type=int)
    if campaign_id is None and p1:
        campaign_id = p1.id

    # All visits on target date
    visits_q = Visit.query.filter(func.date(Visit.visited_at) == target_dt)
    if campaign_id:
        visits_q = visits_q.join(Lead, Visit.lead_id == Lead.id).filter(Lead.campaign_id == campaign_id)
    visits_today = visits_q.all()

    # Enrich visits with lead/gabay
    for v in visits_today:
        v._lead  = Lead.query.get(v.lead_id)
        v._gabay = User.query.get(v.gabay_id)

    # KPI: total visits
    total_visits = len(visits_today)

    # KPI: registrations created today (Registration records)
    reg_q = Registration.query.filter(func.date(Registration.created_at) == target_dt)
    if campaign_id:
        reg_q = reg_q.join(Lead, Registration.lead_id == Lead.id).filter(Lead.campaign_id == campaign_id)
    registrations_today = reg_q.count()

    # KPI: sellers activated (lead status became 'live') — approximated by visits with registered outcome
    live_today = sum(1 for v in visits_today if v.outcome == 'registered')

    # Platform breakdown — based on lead.project field
    PLATFORMS = ['TikTok', 'Shopee', 'RRLD']
    platform_visits = {}
    for p in PLATFORMS:
        platform_visits[p] = sum(
            1 for v in visits_today
            if v._lead and v._lead.project and p.lower() in v._lead.project.lower()
        )

    # Gabay breakdown
    gabay_map = {}
    for v in visits_today:
        gname = v._gabay.display_name if v._gabay else 'Unknown'
        gid   = v.gabay_id
        if gid not in gabay_map:
            gabay_map[gid] = {'name': gname, 'visits': 0, 'interested': 0,
                              'registered': 0, 'callback': 0, 'follow_up': 0, 'not_home': 0}
        gabay_map[gid]['visits'] += 1
        outcome = v.outcome or ''
        if outcome in gabay_map[gid]:
            gabay_map[gid][outcome] += 1
    gabay_rows = sorted(gabay_map.values(), key=lambda x: -x['visits'])

    campaigns = Campaign.query.order_by(Campaign.priority, Campaign.name).all()
    return render_template('reports/daily_ops.html',
        target_dt=target_dt, today=today,
        total_visits=total_visits,
        registrations_today=registrations_today,
        live_today=live_today,
        platform_visits=platform_visits,
        gabay_rows=gabay_rows,
        visits_today=visits_today,
        campaigns=campaigns, campaign_id=campaign_id,
        now=datetime.utcnow())


@app.route('/reports/daily-field')
@login_required
def report_daily_field():
    if not current_user.is_supervisor and not current_user.is_lazada:
        flash('Access denied.', 'danger')
        return redirect(url_for('reports'))
    today = date.today()
    campaign_id = request.args.get('campaign_id', type=int)
    visits_q = Visit.query.filter(func.date(Visit.visited_at) == today)
    if campaign_id:
        visits_q = visits_q.join(Lead, Visit.lead_id == Lead.id).filter(Lead.campaign_id == campaign_id)
    visits = visits_q.order_by(Visit.gabay_id, Visit.visited_at).all()
    for v in visits:
        v._gabay = User.query.get(v.gabay_id)
        v._lead = Lead.query.get(v.lead_id)
    gabay_summary = {}
    for v in visits:
        gname = v._gabay.full_name if v._gabay else '—'
        gabay_summary.setdefault(gname, {'visits': 0, 'interested': 0, 'registered': 0, 'callback': 0})
        gabay_summary[gname]['visits'] += 1
        if v.outcome in ('interested', 'registered', 'callback'):
            gabay_summary[gname][v.outcome] += 1
    campaigns = Campaign.query.order_by(Campaign.priority, Campaign.name).all()
    return render_template('reports/daily_field.html',
        visits=visits, today=today, gabay_summary=gabay_summary, now=datetime.utcnow(),
        campaigns=campaigns, campaign_id=campaign_id)


@app.route('/reports/gabay-performance')
@login_required
def report_gabay_performance():
    if not current_user.is_supervisor and not current_user.is_lazada:
        flash('Access denied.', 'danger')
        return redirect(url_for('reports'))
    today = date.today()
    campaign_id = request.args.get('campaign_id', type=int)
    campaigns = Campaign.query.order_by(Campaign.priority, Campaign.name).all()
    selected_campaign = Campaign.query.get(campaign_id) if campaign_id else None

    agents = User.query.filter_by(role='gabay', is_active=True).order_by(User.full_name).all()
    rows = []
    for a in agents:
        def lq(**kwargs):
            q = Lead.query.filter_by(gabay_id=a.id, **kwargs)
            if campaign_id:
                q = q.filter_by(campaign_id=campaign_id)
            return q

        total   = lq().count()
        live    = lq(status='live').count()
        matched = lq(status='matched').count()

        # Visits always counted by gabay_id — visit history may live in a different campaign's
        # lead records (e.g. Legacy) but the agent is the same person across campaigns
        visits_month = Visit.query.filter(
            Visit.gabay_id == a.id,
            extract('year', Visit.visited_at) == today.year,
            extract('month', Visit.visited_at) == today.month
        ).count()
        visits_total = Visit.query.filter_by(gabay_id=a.id).count()

        conv = round(live / total * 100, 1) if total else 0
        rows.append({'gabay': a, 'total': total, 'live': live, 'matched': matched,
                     'visits_month': visits_month, 'visits_total': visits_total, 'conv': conv})
    rows.sort(key=lambda x: x['live'], reverse=True)
    return render_template('reports/gabay_performance.html',
        rows=rows, month=today.strftime('%B %Y'), now=datetime.utcnow(),
        campaigns=campaigns, selected_campaign=selected_campaign, campaign_id=campaign_id)


@app.route('/reports/pipeline-detail')
@login_required
def report_pipeline_detail():
    if not current_user.is_supervisor and not current_user.is_lazada:
        flash('Access denied.', 'danger')
        return redirect(url_for('reports'))
    campaign_id = request.args.get('campaign_id', type=int)
    statuses = ['pool', 'assigned', 'attempting', 'negotiation', 'registration', 'live', 'matched', 'closed']
    def _lead_q(**kwargs):
        q = Lead.query.filter_by(**kwargs)
        if campaign_id:
            q = q.filter(Lead.campaign_id == campaign_id)
        return q
    totals = {s: _lead_q(status=s).count() for s in statuses}
    city_raw_q = db.session.query(Lead.city, Lead.status, func.count(Lead.id))
    if campaign_id:
        city_raw_q = city_raw_q.filter(Lead.campaign_id == campaign_id)
    city_raw = city_raw_q.group_by(Lead.city, Lead.status).all()
    cities = {}
    for city, status, count in city_raw:
        c = city or 'Unknown'
        cities.setdefault(c, {s: 0 for s in statuses})
        if status in cities[c]:
            cities[c][status] += count
    cities = sorted(cities.items(), key=lambda x: sum(x[1].values()), reverse=True)[:20]
    campaigns = Campaign.query.order_by(Campaign.priority, Campaign.name).all()
    return render_template('reports/pipeline_detail.html',
        totals=totals, cities=cities, statuses=statuses, now=datetime.utcnow(),
        campaigns=campaigns, campaign_id=campaign_id)


@app.route('/reports/stalled')
@login_required
def report_stalled():
    if not current_user.is_supervisor and not current_user.is_lazada:
        flash('Access denied.', 'danger')
        return redirect(url_for('reports'))
    from datetime import timedelta
    campaign_id = request.args.get('campaign_id', type=int)
    cutoff = datetime.utcnow() - timedelta(days=7)
    stalled_q = Lead.query.filter(
        Lead.status.in_(['assigned', 'attempting']),
        ~Lead.id.in_(db.session.query(Visit.lead_id).filter(Visit.visited_at >= cutoff))
    )
    if campaign_id:
        stalled_q = stalled_q.filter(Lead.campaign_id == campaign_id)
    leads = stalled_q.order_by(Lead.gabay_id, Lead.assigned_at.asc()).all()
    for l in leads:
        l._gabay = User.query.get(l.gabay_id) if l.gabay_id else None
        l._last_visit = Visit.query.filter_by(lead_id=l.id).order_by(Visit.visited_at.desc()).first()
    campaigns = Campaign.query.order_by(Campaign.priority, Campaign.name).all()
    return render_template('reports/stalled.html', leads=leads, now=datetime.utcnow(),
                           campaigns=campaigns, campaign_id=campaign_id)


@app.route('/reports/city-coverage')
@login_required
def report_city_coverage():
    if not current_user.is_supervisor and not current_user.is_lazada:
        flash('Access denied.', 'danger')
        return redirect(url_for('reports'))
    campaign_id = request.args.get('campaign_id', type=int)
    visited_ids = {v.lead_id for v in Visit.query.with_entities(Visit.lead_id).all()}
    city_q = db.session.query(Lead.city, func.count(Lead.id)).filter(Lead.status != 'removed')
    if campaign_id:
        city_q = city_q.filter(Lead.campaign_id == campaign_id)
    city_raw = city_q.group_by(Lead.city).all()
    rows = []
    for city, total in city_raw:
        city_name = city or 'Unknown'
        leads_q = Lead.query.filter(Lead.city == city, Lead.status != 'removed')
        if campaign_id:
            leads_q = leads_q.filter(Lead.campaign_id == campaign_id)
        leads_in = leads_q.with_entities(Lead.id, Lead.status).all()
        visited = sum(1 for l in leads_in if l.id in visited_ids)
        live = sum(1 for l in leads_in if l.status == 'live')
        rows.append({'city': city_name, 'total': total, 'visited': visited,
                     'unvisited': total - visited, 'live': live,
                     'coverage': round(visited / total * 100) if total else 0})
    rows.sort(key=lambda x: x['total'], reverse=True)
    campaigns = Campaign.query.order_by(Campaign.priority, Campaign.name).all()
    return render_template('reports/city_coverage.html', cities=rows, now=datetime.utcnow(),
                           campaigns=campaigns, campaign_id=campaign_id)


@app.route('/reports/registrations-status')
@login_required
def report_registrations_status():
    if not current_user.is_supervisor and not current_user.is_lazada:
        flash('Access denied.', 'danger')
        return redirect(url_for('reports'))
    campaign_id = request.args.get('campaign_id', type=int)
    regs_q = Registration.query
    if campaign_id:
        regs_q = regs_q.join(Lead, Registration.lead_id == Lead.id).filter(Lead.campaign_id == campaign_id)
    regs = regs_q.order_by(Registration.submitted_at.desc()).all()
    for r in regs:
        r._lead = Lead.query.get(r.lead_id) if r.lead_id else None
        r._gabay = User.query.get(r._lead.gabay_id) if r._lead and r._lead.gabay_id else None
    campaigns = Campaign.query.order_by(Campaign.priority, Campaign.name).all()
    return render_template('reports/registrations_status.html',
        regs=regs, now=datetime.utcnow(), campaigns=campaigns, campaign_id=campaign_id)


@app.route('/reports/campaign-roi')
@login_required
def report_campaign_roi():
    if not current_user.is_supervisor and not current_user.is_lazada:
        flash('Access denied.', 'danger')
        return redirect(url_for('reports'))
    batches = db.session.query(
        Lead.batch_ref,
        func.count(Lead.id).label('total'),
        func.min(Lead.imported_at).label('imported_at'),
        func.sum(func.cast(Lead.status.in_(['live', 'matched']), db.Integer)).label('live'),
        func.sum(func.cast(Lead.status == 'matched', db.Integer)).label('matched'),
        func.sum(func.cast(Lead.status == 'closed', db.Integer)).label('closed'),
    ).filter(Lead.batch_ref.isnot(None)).group_by(Lead.batch_ref)\
     .order_by(func.min(Lead.imported_at).desc()).all()
    return render_template('reports/campaign_roi.html', batches=batches, now=datetime.utcnow())


@app.route('/reports/lead-scoring')
@login_required
def report_lead_scoring():
    if not current_user.is_supervisor and not current_user.is_lazada:
        flash('Access denied.', 'danger')
        return redirect(url_for('reports'))

    gabay_filter = request.args.get('gabay', type=int)
    tier_filter  = request.args.get('tier', '')
    status_filter = request.args.get('status', '')
    campaign_id = request.args.get('campaign_id', type=int)

    q = Lead.query.filter(Lead.status.notin_(['pool', 'live', 'matched', 'closed']))
    if campaign_id:
        q = q.filter(Lead.campaign_id == campaign_id)
    if gabay_filter:
        q = q.filter_by(gabay_id=gabay_filter)
    if status_filter:
        q = q.filter_by(status=status_filter)

    leads = q.all()

    # Score and sort in Python (scoring uses visit relationship)
    scored = sorted(leads, key=lambda l: l.conversion_score, reverse=True)

    if tier_filter:
        scored = [l for l in scored if l.conversion_tier[0].lower() == tier_filter.lower()]

    gabay_users = User.query.filter_by(role='gabay', is_active=True).order_by(User.full_name).all()

    tier_counts = {'Hot': 0, 'Warm': 0, 'Cool': 0, 'Cold': 0}
    for l in leads:
        tier_counts[l.conversion_tier[0]] += 1

    campaigns = Campaign.query.order_by(Campaign.priority, Campaign.name).all()
    return render_template('reports/lead_scoring.html',
        leads=scored, gabay_users=gabay_users,
        gabay_filter=gabay_filter, tier_filter=tier_filter,
        status_filter=status_filter, tier_counts=tier_counts,
        campaigns=campaigns, campaign_id=campaign_id,
        now=datetime.utcnow())


@app.route('/reports/gabay-pipeline')
@login_required
def report_gabay_pipeline():
    if not current_user.is_supervisor and not current_user.is_lazada:
        flash('Access denied.', 'danger')
        return redirect(url_for('reports'))
    campaign_id = request.args.get('campaign_id', type=int)
    gabay_users = User.query.filter_by(role='gabay').order_by(User.full_name).all()
    report_rows = []
    for g in gabay_users:
        def lq(**kwargs):
            q = Lead.query.filter_by(gabay_id=g.id, **kwargs)
            if campaign_id:
                q = q.filter(Lead.campaign_id == campaign_id)
            return q
        total  = lq().count()
        visits = Visit.query.filter_by(gabay_id=g.id).count()
        by_status = {}
        for s in ('assigned','attempting','negotiation','registration','live','matched','closed'):
            by_status[s] = lq(status=s).count()
        advanced = by_status['negotiation'] + by_status['registration'] + by_status['live'] + by_status['matched']
        last_visit = Visit.query.filter_by(gabay_id=g.id).order_by(Visit.visited_at.desc()).first()
        report_rows.append({
            'gabay': g,
            'total': total,
            'visits': visits,
            'visit_pct': round(visits / total * 100) if total else 0,
            'adv_pct': round(advanced / total * 100) if total else 0,
            'by_status': by_status,
            'last_visit': last_visit.visited_at if last_visit else None,
        })
    report_rows.sort(key=lambda r: r['visits'], reverse=True)
    campaigns = Campaign.query.order_by(Campaign.priority, Campaign.name).all()
    return render_template('reports/gabay_pipeline.html',
        rows=report_rows, now=datetime.utcnow(),
        total_leads=Lead.query.filter(Lead.campaign_id == campaign_id).count() if campaign_id else Lead.query.count(),
        total_visits=Visit.query.count(),
        campaigns=campaigns, campaign_id=campaign_id)


@app.route('/api/reports/kpi')
@login_required
def api_kpi():
    data = {
        'total_pool': Lead.query.count(),
        'assigned': Lead.query.filter_by(status='assigned').count(),
        'attempting': Lead.query.filter_by(status='attempting').count(),
        'negotiation': Lead.query.filter_by(status='negotiation').count(),
        'registration': Lead.query.filter_by(status='registration').count(),
        'live': Lead.query.filter_by(status='live').count(),
        'matched': Lead.query.filter_by(status='matched').count(),
        'closed': Lead.query.filter_by(status='closed').count(),
        'total_visits': Visit.query.count(),
        'total_gabay': User.query.filter_by(role='gabay', is_active=True).count(),
        'vw': Registration.query.filter_by(is_vw=True).count(),
        'vw_rrld': Registration.query.filter_by(is_vw_rrld=True).count(),
    }
    return jsonify(data)


@app.route('/api/reports/gabay-performance')
@login_required
def api_gabay_performance():
    agents = User.query.filter_by(role='gabay', is_active=True).order_by(User.full_name).all()
    result = []
    for a in agents:
        pool = Lead.query.filter_by(gabay_id=a.id).count()
        assigned = Lead.query.filter_by(gabay_id=a.id, status='assigned').count()
        attempting = Lead.query.filter_by(gabay_id=a.id, status='attempting').count()
        negotiation = Lead.query.filter_by(gabay_id=a.id, status='negotiation').count()
        registration = Lead.query.filter_by(gabay_id=a.id, status='registration').count()
        live = Lead.query.filter_by(gabay_id=a.id, status='live').count()
        matched = Lead.query.filter_by(gabay_id=a.id, status='matched').count()
        visits = Visit.query.filter_by(gabay_id=a.id).count()
        result.append({
            'name': a.full_name, 'pool': pool, 'assigned': assigned,
            'attempting': attempting, 'negotiation': negotiation,
            'registration': registration, 'live': live, 'matched': matched,
            'visits': visits,
            'conv_rate': round(matched / pool * 100, 1) if pool else 0,
        })
    result.sort(key=lambda x: x['matched'], reverse=True)
    return jsonify(result)


@app.route('/api/reports/pipeline')
@login_required
def api_pipeline():
    statuses = ['pool', 'assigned', 'attempting', 'negotiation', 'registration', 'live', 'matched']
    data = {}
    for s in statuses:
        data[s] = Lead.query.filter_by(status=s).count()
    return jsonify(data)


@app.route('/api/reports/visits-trend')
@login_required
def api_visits_trend():
    from sqlalchemy import cast, Date
    results = db.session.query(
        cast(Visit.visited_at, Date).label('day'),
        func.count(Visit.id).label('count')
    ).group_by('day').order_by('day').limit(30).all()
    return jsonify([{'date': str(r.day), 'count': r.count} for r in results])


@app.route('/admin/health')
@login_required
def admin_health():
    if not current_user.is_supervisor:
        abort(403)

    import re, json as _json

    pool_leads = Lead.query.filter_by(status='pool').filter(Lead.is_archived.isnot(True)).all()

    # ── 1. DUPLICATE ADDRESS DETECTION ──────────────────────────────────
    def norm_addr(l):
        parts = [l.barangay or '', l.city or '', l.address or '']
        raw = ' '.join(p.strip() for p in parts if p.strip()).lower()
        return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', '', raw)).strip()

    addr_map = {}
    for l in pool_leads:
        key = norm_addr(l)
        if key:
            addr_map.setdefault(key, []).append(l)

    duplicate_groups = sorted(
        [leads for leads in addr_map.values() if len(leads) >= 2],
        key=lambda g: -len(g)
    )

    # ── 2. WAREHOUSE KEYWORDS ────────────────────────────────────────────
    WH_KEYWORDS = ['warehouse', 'bodega', 'depot', 'hub', 'logistics',
                   'fulfillment', 'centre', 'center', 'storage', 'distribution']
    warehouse_leads = [
        l for l in pool_leads
        if any(kw in (l.address or '').lower() or kw in (l.barangay or '').lower()
               for kw in WH_KEYWORDS)
        or len(addr_map.get(norm_addr(l), [])) >= 3
    ]

    # ── 3. PREVIOUSLY VISITED (same seller name visited in any old lead) ─
    visited_lead_ids = {v.lead_id for v in Visit.query.all()}
    all_leads_with_visits = Lead.query.filter(Lead.id.in_(visited_lead_ids)).all()
    pool_names = {l.seller_name.strip().lower(): l for l in pool_leads}
    prev_visited = []
    for old in all_leads_with_visits:
        match = pool_names.get(old.seller_name.strip().lower())
        if match and old.id != match.id:  # exclude self-match (pool lead's own visits)
            prev_visited.append({'pool_lead': match, 'old_lead': old,
                                  'visit_count': old.visits.count()})

    # ── 4. STRICT BUILDINGS (auto-detected from visit notes) ─────────────
    STRICT_KEYWORDS = ['strict admin', 'strict guard', 'no entry', 'not allowed',
                       'building admin', 'security guard', 'no visitors', 'admin approval',
                       'gated', 'no access', 'bayad sa guard', 'bayad sa admin']
    auto_strict = {}
    for v in Visit.query.filter(Visit.notes.isnot(None)).all():
        note_low = (v.notes or '').lower()
        if any(kw in note_low for kw in STRICT_KEYWORDS):
            lead = Lead.query.get(v.lead_id)
            if lead and lead.barangay:
                key = f"{lead.barangay}, {lead.city or ''}"
                auto_strict[key] = auto_strict.get(key, 0) + 1

    manual_strict = StrictBuilding.query.order_by(StrictBuilding.added_at.desc()).all()
    manual_strict_names = {s.name.lower() for s in manual_strict}

    # ── 5. AI INSPECTION RESULTS ─────────────────────────────────────────
    ai_inspected = [l for l in pool_leads if l.ai_readiness]
    ai_pending = len(pool_leads) - len(ai_inspected)

    # Parse AI results for display
    ai_results = []
    for l in ai_inspected:
        try:
            data = _json.loads(l.ai_readiness)
        except Exception:
            data = {}
        ai_results.append({'lead': l, 'data': data})

    # Sort by reg_readiness: high first
    order = {'high': 0, 'medium': 1, 'low': 2}
    ai_results.sort(key=lambda x: order.get(x['data'].get('reg_readiness', 'low'), 2))

    return render_template('admin/health.html',
        pool_leads=pool_leads,
        duplicate_groups=duplicate_groups,
        warehouse_leads=warehouse_leads,
        prev_visited=prev_visited,
        auto_strict=sorted(auto_strict.items(), key=lambda x: -x[1]),
        manual_strict=manual_strict,
        ai_results=ai_results,
        ai_pending=ai_pending,
        ai_inspected_count=len(ai_inspected),
    )


@app.route('/admin/health/ai-inspect', methods=['POST'])
@login_required
def admin_health_ai_inspect():
    """Run Haiku AI inspection on all unassigned pool leads that haven't been inspected."""
    if not current_user.is_supervisor:
        abort(403)

    import anthropic as _anth, json as _json, threading

    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        flash('ANTHROPIC_API_KEY not set in Railway Variables.', 'danger')
        return redirect(url_for('admin_health'))

    pool_leads = Lead.query.filter_by(status='pool').filter(
        Lead.ai_inspected_at.is_(None)
    ).all()

    if not pool_leads:
        flash('All pool leads have already been inspected.', 'info')
        return redirect(url_for('admin_health'))

    def _inspect_batch(lead_ids):
        with app.app_context():
            client = _anth.Anthropic(api_key=api_key)
            for lid in lead_ids:
                lead = Lead.query.get(lid)
                if not lead:
                    continue
                prompt = f"""Inspect this seller lead for a Lazada onboarding campaign. Return ONLY valid JSON.

Seller: {lead.seller_name}
Category: {lead.category or 'unknown'}
Link: {lead.link or 'none'}
Phone: {lead.contact_number or 'none'}
Email: {lead.email or 'none'}
Social: {lead.social_media_link or 'none'}
Address: {lead.address or 'none'}
Barangay: {lead.barangay or 'none'}
City: {lead.city or 'none'}
Project/Platform: {lead.project or 'none'}

Return JSON with exactly these keys:
{{
  "online_presence": "strong|moderate|weak|none",
  "contact_quality": "complete|partial|missing",
  "reg_readiness": "high|medium|low",
  "business_type": "retail_store|online_only|warehouse|home_based|unknown",
  "has_website": true/false,
  "has_phone": true/false,
  "has_email": true/false,
  "has_social": true/false,
  "flags": ["max 3 short concerns"],
  "summary": "one sentence max 20 words"
}}"""
                try:
                    resp = client.messages.create(
                        model='claude-haiku-4-5-20251001',
                        max_tokens=300,
                        messages=[{'role': 'user', 'content': prompt}]
                    )
                    raw = resp.content[0].text.strip()
                    # Extract JSON if wrapped in markdown
                    if '```' in raw:
                        raw = raw.split('```')[1].strip()
                        if raw.startswith('json'):
                            raw = raw[4:].strip()
                    _json.loads(raw)  # validate
                    lead.ai_readiness = raw
                    lead.ai_inspected_at = datetime.utcnow()
                    db.session.commit()
                except Exception as e:
                    app.logger.warning(f'[Health AI] lead {lid}: {e}')
                    continue

    lead_ids = [l.id for l in pool_leads]
    t = threading.Thread(target=_inspect_batch, args=(lead_ids,), daemon=True)
    t.start()

    flash(f'AI inspection started for {len(lead_ids)} leads. Refresh in ~{max(1, len(lead_ids)//10)} minute(s).', 'info')
    return redirect(url_for('admin_health'))


@app.route('/admin/health/strict/add', methods=['POST'])
@login_required
def admin_health_strict_add():
    if not current_user.is_supervisor:
        abort(403)
    name = request.form.get('name', '').strip()
    city = request.form.get('city', '').strip()
    reason = request.form.get('reason', '').strip()
    if name:
        existing = StrictBuilding.query.filter(
            db.func.lower(StrictBuilding.name) == name.lower()
        ).first()
        if existing:
            existing.times_encountered += 1
            existing.reason = reason or existing.reason
        else:
            db.session.add(StrictBuilding(
                name=name, city=city, reason=reason,
                source='manual', added_by_id=current_user.id
            ))
        db.session.commit()
        flash(f'"{name}" added to strict buildings list.', 'success')
    return redirect(url_for('admin_health') + '#strict')


@app.route('/admin/health/strict/remove/<int:sid>', methods=['POST'])
@login_required
def admin_health_strict_remove(sid):
    if not current_user.is_supervisor:
        abort(403)
    s = StrictBuilding.query.get_or_404(sid)
    db.session.delete(s)
    db.session.commit()
    flash('Removed from strict buildings list.', 'success')
    return redirect(url_for('admin_health') + '#strict')


@app.route('/admin/health/flag-warehouse/<int:lead_id>', methods=['POST'])
@login_required
def admin_health_flag_warehouse(lead_id):
    if not current_user.is_supervisor:
        abort(403)
    l = Lead.query.get_or_404(lead_id)
    l.is_warehouse = not l.is_warehouse
    db.session.commit()
    return jsonify({'is_warehouse': l.is_warehouse})


@app.route('/admin/health/archive-lead/<int:lead_id>', methods=['POST'])
@login_required
def admin_health_archive_lead(lead_id):
    if not current_user.is_supervisor:
        abort(403)
    l = Lead.query.get_or_404(lead_id)
    if l.status != 'pool':
        return jsonify({'error': 'Only unassigned pool leads can be archived.'}), 400
    l.is_archived = not l.is_archived
    db.session.commit()
    return jsonify({'is_archived': l.is_archived})


@app.route('/reports/competitor')
@login_required
def report_competitor():
    if not current_user.is_supervisor and not current_user.is_lazada:
        flash('Access denied.', 'danger')
        return redirect(url_for('reports'))

    from collections import defaultdict

    STATUSES = ['pool','assigned','attempting','negotiation','registration','live','matched','closed']
    STATUS_LABELS = {
        'pool':'Pool','assigned':'Assigned','attempting':'Attempting',
        'negotiation':'Negotiation','registration':'Registration',
        'live':'Live','matched':'Matched','closed':'Closed'
    }

    # All leads with a project (competitor tag)
    comp_leads = Lead.query.filter(Lead.project.isnot(None), Lead.project != '').all()

    # Group by project
    by_project = defaultdict(list)
    for l in comp_leads:
        by_project[l.project.strip()].append(l)

    projects = []
    for proj, leads in sorted(by_project.items(), key=lambda x: -len(x[1])):
        status_dist = defaultdict(int)
        for l in leads:
            status_dist[l.status] += 1
        live = status_dist.get('live', 0) + status_dist.get('matched', 0)
        hot  = sum(1 for l in leads if l.conversion_score >= 60)
        last_visit_leads = [l for l in leads if l.last_visit_days is not None]
        avg_score = round(sum(l.conversion_score for l in leads) / len(leads)) if leads else 0
        projects.append({
            'name': proj,
            'leads': leads,
            'total': len(leads),
            'live': live,
            'hot': hot,
            'avg_score': avg_score,
            'status_dist': dict(status_dist),
            'conv_rate': round(live / len(leads) * 100, 1) if leads else 0,
        })

    total_comp = len(comp_leads)
    total_live  = sum(p['live'] for p in projects)

    return render_template('reports/competitor.html',
        projects=projects,
        statuses=STATUSES,
        status_labels=STATUS_LABELS,
        total_comp=total_comp,
        total_live=total_live,
    )


@app.route('/reports/hot-prospects')
@login_required
def report_hot_prospects():
    if not current_user.is_supervisor and not current_user.is_lazada:
        flash('Access denied.', 'danger')
        return redirect(url_for('reports'))

    import datetime as _dt

    gabay_filter = request.args.get('gabay_id', '', type=str)
    project_filter = request.args.get('project', '')
    campaign_id = request.args.get('campaign_id', type=int)
    today = date.today()
    week_start = today - _dt.timedelta(days=today.weekday())

    # Hot prospects = leads showing positive re-engagement signals
    active_statuses = ['assigned', 'attempting', 'negotiation', 'registration']

    q = Lead.query.filter(Lead.status.in_(active_statuses))
    if campaign_id:
        q = q.filter(Lead.campaign_id == campaign_id)
    if gabay_filter:
        q = q.filter(Lead.gabay_id == int(gabay_filter))
    if project_filter:
        q = q.filter(Lead.project == project_filter)
    all_active = q.all()

    hot_prospects = []
    for lead in all_active:
        last_v = lead.latest_visit
        is_hot = False
        reason = []
        fu_date = None

        if last_v:
            if last_v.outcome in ('interested', 'callback', 'follow_up', 'registered'):
                is_hot = True
                reason.append(f'Last visit: {last_v.outcome.replace("_"," ").title()}')
            if last_v.follow_up_date:
                fu_date = last_v.follow_up_date
                days_to_fu = (fu_date - today).days
                if days_to_fu <= 7:
                    is_hot = True
                    if days_to_fu < 0:
                        reason.append(f'Follow-up OVERDUE by {abs(days_to_fu)}d')
                    elif days_to_fu == 0:
                        reason.append('Follow-up DUE TODAY')
                    else:
                        reason.append(f'Follow-up in {days_to_fu}d')

        if lead.status in ('negotiation', 'registration'):
            is_hot = True
            reason.append(f'Pipeline: {lead.status.title()}')

        if is_hot:
            hot_prospects.append({
                'lead': lead,
                'score': lead.conversion_score,
                'last_visit': last_v,
                'fu_date': fu_date,
                'reasons': reason,
                'is_competitor': bool(lead.project),
                'gabay': lead.assigned_gabay,
            })

    # Sort: overdue follow-ups first, then by score
    def sort_key(p):
        fu = p['fu_date']
        overdue = (fu - today).days if fu else 99
        return (overdue, -p['score'])
    hot_prospects.sort(key=sort_key)

    # Weekly summary
    visits_this_week = Visit.query.filter(
        func.date(Visit.visited_at) >= week_start,
        func.date(Visit.visited_at) <= today,
    ).count()

    # Project list for filter
    proj_rows = db.session.query(Lead.project).filter(
        Lead.project.isnot(None), Lead.project != ''
    ).distinct().order_by(Lead.project).all()
    projects = [r[0] for r in proj_rows]

    gabays = User.query.filter_by(role='gabay', is_active=True).order_by(User.full_name).all()

    campaigns = Campaign.query.order_by(Campaign.priority, Campaign.name).all()
    return render_template('reports/hot_prospects.html',
        hot_prospects=hot_prospects,
        visits_this_week=visits_this_week,
        week_start=week_start,
        today=today,
        projects=projects,
        gabays=gabays,
        gabay_filter=gabay_filter,
        project_filter=project_filter,
        campaigns=campaigns, campaign_id=campaign_id,
    )


@app.route('/reports/forecast')
@login_required
def report_forecast():
    if not current_user.is_supervisor and not current_user.is_lazada:
        flash('Access denied.', 'danger')
        return redirect(url_for('reports'))

    from calendar import monthrange
    import datetime as _dt

    today = date.today()
    month_str = request.args.get('month', today.strftime('%Y-%m'))
    # Force-majeure/suspension dates passed as comma-separated YYYY-MM-DD
    suspended_raw = request.args.get('suspended', '')
    suspended_dates = set()
    suspended_labels = []
    for s in suspended_raw.split(','):
        s = s.strip()
        if s:
            try:
                d = _dt.date.fromisoformat(s)
                suspended_dates.add(d)
                suspended_labels.append(d.strftime('%b %d'))
            except Exception:
                pass

    try:
        year, mon = int(month_str[:4]), int(month_str[5:7])
    except Exception:
        year, mon = today.year, today.month

    month_start = date(year, mon, 1)
    _, days_in_month = monthrange(year, mon)
    month_end = date(year, mon, days_in_month)
    is_current_month = (year == today.year and mon == today.month)

    # ── Philippine Public Holidays ────────────────────────────────────────
    PH_HOLIDAYS = {
        # 2026
        date(2026, 1,  1): "New Year's Day",
        date(2026, 4,  2): "Maundy Thursday",
        date(2026, 4,  3): "Good Friday",
        date(2026, 4,  4): "Black Saturday",
        date(2026, 4,  9): "Araw ng Kagitingan",
        date(2026, 5,  1): "Labor Day",
        date(2026, 6, 12): "Independence Day",
        date(2026, 8, 31): "National Heroes Day",
        date(2026, 11, 1): "All Saints' Day",
        date(2026, 11, 2): "All Souls' Day",
        date(2026, 11,30): "Bonifacio Day",
        date(2026, 12, 8): "Immaculate Conception",
        date(2026, 12,25): "Christmas Day",
        date(2026, 12,30): "Rizal Day",
        date(2026, 12,31): "New Year's Eve",
        # 2025
        date(2025, 1,  1): "New Year's Day",
        date(2025, 4, 17): "Maundy Thursday",
        date(2025, 4, 18): "Good Friday",
        date(2025, 4, 19): "Black Saturday",
        date(2025, 4,  9): "Araw ng Kagitingan",
        date(2025, 5,  1): "Labor Day",
        date(2025, 6, 12): "Independence Day",
        date(2025, 8, 25): "National Heroes Day",
        date(2025, 11, 1): "All Saints' Day",
        date(2025, 11,30): "Bonifacio Day",
        date(2025, 12,25): "Christmas Day",
        date(2025, 12,30): "Rizal Day",
    }

    def count_working_days(start_d, end_d):
        """Count Mon–Sat days excluding PH holidays and suspended dates."""
        count = 0
        holidays_hit = []
        d = start_d
        while d <= end_d:
            if d.weekday() == 6:  # Sunday
                d += _dt.timedelta(days=1)
                continue
            if d in PH_HOLIDAYS:
                holidays_hit.append((d, PH_HOLIDAYS[d]))
                d += _dt.timedelta(days=1)
                continue
            if d in suspended_dates:
                d += _dt.timedelta(days=1)
                continue
            count += 1
            d += _dt.timedelta(days=1)
        return count, holidays_hit

    # Working days elapsed (Mon–Sat, excl. holidays/suspended)
    if is_current_month:
        working_elapsed, _ = count_working_days(month_start, today)
        working_remaining, holidays_in_remaining = count_working_days(
            today + _dt.timedelta(days=1), month_end)
    else:
        working_elapsed, _ = count_working_days(month_start, month_end)
        working_remaining = 0
        holidays_in_remaining = []

    # Also collect holidays that already passed this month (for transparency)
    _, holidays_elapsed = count_working_days(month_start, today if is_current_month else month_end)
    # (holidays_elapsed is unused count, we want the list from second return)
    elapsed_holiday_list = []
    if is_current_month:
        d = month_start
        while d <= today:
            if d in PH_HOLIDAYS:
                elapsed_holiday_list.append((d, PH_HOLIDAYS[d]))
            if d in suspended_dates:
                elapsed_holiday_list.append((d, "⛈️ Suspended / Force Majeure"))
            d += _dt.timedelta(days=1)

    remaining_holiday_list = []
    if is_current_month:
        d = today + _dt.timedelta(days=1)
        while d <= month_end:
            if d in PH_HOLIDAYS:
                remaining_holiday_list.append((d, PH_HOLIDAYS[d]))
            if d in suspended_dates:
                remaining_holiday_list.append((d, "⛈️ Suspended / Force Majeure"))
            if d.weekday() == 6:
                remaining_holiday_list.append((d, "Sunday (non-field day)"))
            d += _dt.timedelta(days=1)
        # Deduplicate sundays that are also holidays
        seen = set()
        unique_remaining = []
        for item in remaining_holiday_list:
            if item[0] not in seen:
                seen.add(item[0])
                unique_remaining.append(item)
        remaining_holiday_list = sorted(unique_remaining, key=lambda x: x[0])

    gabays = User.query.filter_by(role='gabay', is_active=True).order_by(User.full_name).all()

    # Week boundaries for current month
    week_ranges = []
    for w in range(5):
        ws = month_start + _dt.timedelta(days=w*7)
        we = min(month_start + _dt.timedelta(days=(w+1)*7 - 1), month_end)
        if ws <= month_end:
            week_ranges.append((w+1, ws, we))

    # Previous month boundaries
    if mon == 1:
        prev_year, prev_mon = year - 1, 12
    else:
        prev_year, prev_mon = year, mon - 1
    prev_month_str = f'{prev_year:04d}-{prev_mon:02d}'
    _, prev_days = monthrange(prev_year, prev_mon)
    prev_start = date(prev_year, prev_mon, 1)
    prev_end   = date(prev_year, prev_mon, prev_days)
    prev_week_ranges = []
    for w in range(5):
        ws = prev_start + _dt.timedelta(days=w*7)
        we = min(prev_start + _dt.timedelta(days=(w+1)*7 - 1), prev_end)
        if ws <= prev_end:
            prev_week_ranges.append((w+1, ws, we))

    results = []
    for g in gabays:
        target = GabayTarget.query.filter_by(gabay_id=g.id, month=month_str).first()
        target_live   = target.target_live   if target else 0
        target_visits = target.target_visits if target else 0

        visits_this_month = Visit.query.filter(
            Visit.gabay_id == g.id,
            func.date(Visit.visited_at) >= month_start,
            func.date(Visit.visited_at) <= month_end
        ).all()

        # Registrations this month (submitted + activated)
        from models import Registration
        regs_this_month = db.session.query(Registration).join(Lead).filter(
            Lead.gabay_id == g.id,
            Registration.created_at >= _dt.datetime.combine(month_start, _dt.time.min),
            Registration.created_at <= _dt.datetime.combine(month_end, _dt.time.max),
        ).all()
        live_this_month = [r for r in regs_this_month if r.activated_at and
                           month_start <= r.activated_at.date() <= month_end]

        weekly_visits = []
        for w_num, ws, we in week_ranges:
            v_cnt  = sum(1 for v in visits_this_month if ws <= v.visited_at.date() <= we)
            r_cnt  = sum(1 for r in regs_this_month if ws <= r.created_at.date() <= we)
            l_cnt  = sum(1 for r in live_this_month if ws <= r.activated_at.date() <= we)
            weekly_visits.append({
                'week': w_num, 'start': ws, 'end': we,
                'visits': v_cnt, 'registrations': r_cnt, 'live': l_cnt,
                'count': v_cnt,  # kept for backward compat
            })

        # Previous month data for WoW comparison
        prev_visits = Visit.query.filter(
            Visit.gabay_id == g.id,
            func.date(Visit.visited_at) >= prev_start,
            func.date(Visit.visited_at) <= prev_end,
        ).all()
        prev_regs = db.session.query(Registration).join(Lead).filter(
            Lead.gabay_id == g.id,
            Registration.created_at >= _dt.datetime.combine(prev_start, _dt.time.min),
            Registration.created_at <= _dt.datetime.combine(prev_end, _dt.time.max),
        ).all()
        prev_live = [r for r in prev_regs if r.activated_at and
                     prev_start <= r.activated_at.date() <= prev_end]

        prev_weekly = []
        for w_num, ws, we in prev_week_ranges:
            v_cnt = sum(1 for v in prev_visits if ws <= v.visited_at.date() <= we)
            r_cnt = sum(1 for r in prev_regs if ws <= r.created_at.date() <= we)
            l_cnt = sum(1 for r in prev_live if ws <= r.activated_at.date() <= we)
            prev_weekly.append({
                'week': w_num, 'start': ws, 'end': we,
                'visits': v_cnt, 'registrations': r_cnt, 'live': l_cnt,
            })

        total_visits = len(visits_this_month)
        # Use working days elapsed (not calendar) for accurate daily rate
        daily_visit_rate = total_visits / working_elapsed if working_elapsed > 0 else 0
        projected_visits = round(total_visits + daily_visit_rate * working_remaining)

        assigned_leads = Lead.query.filter_by(gabay_id=g.id).all()
        status_counts = {}
        for lead in assigned_leads:
            status_counts[lead.status] = status_counts.get(lead.status, 0) + 1

        live_count    = status_counts.get('live', 0)
        reg_count     = status_counts.get('registration', 0)
        nego_count    = status_counts.get('negotiation', 0)
        attempt_count = status_counts.get('attempting', 0)
        total_assigned = len(assigned_leads)

        conv_rate = (live_count / total_assigned) if total_assigned > 0 else 0.0

        # Working days factor (not calendar days)
        total_working = working_elapsed + working_remaining
        days_factor = working_remaining / total_working if total_working > 0 else 0

        reg_prob  = min(conv_rate * 3.0, 0.35) * days_factor
        nego_prob = min(conv_rate * 1.0, 0.10) * days_factor
        att_prob  = min(conv_rate * 0.3, 0.03) * days_factor
        if conv_rate == 0:
            reg_prob  = 0.15 * days_factor
            nego_prob = 0.05 * days_factor
            att_prob  = 0.01 * days_factor

        hot_forecast   = round(reg_count * reg_prob + nego_count * nego_prob + attempt_count * att_prob)
        projected_live = live_count + hot_forecast
        gap            = target_live - projected_live
        visit_gap      = target_visits - projected_visits

        suggestions = []
        if working_remaining == 0:
            suggestions.append("📅 No working days remaining this month.")
        elif gap > 0:
            if reg_count > 0:
                suggestions.append(f"🔴 Push {reg_count} Registration lead(s) — closest to going Live.")
            if nego_count >= gap * 2:
                suggestions.append(f"⚡ {nego_count} in Negotiation. Focus on top {min(nego_count, gap*3)} to close {gap} more.")
            elif nego_count > 0:
                suggestions.append(f"⚡ Only {nego_count} in Negotiation — move more leads up the pipeline.")
            if attempt_count > 3:
                suggestions.append(f"📞 {attempt_count} still Attempting Contact — re-visit to push to Negotiation.")
            if daily_visit_rate < 2:
                suggestions.append(f"🚶 Visit pace low ({daily_visit_rate:.1f}/working day). Need at least 3/day.")
            if working_remaining <= 5:
                suggestions.append(f"⏰ Only {working_remaining} working days left — prioritize Registration & Negotiation leads NOW.")
            if not suggestions:
                suggestions.append(f"📋 Need {gap} more live seller(s) in {working_remaining} working days.")
        elif gap == 0:
            suggestions.append("🎯 On track to meet target. Maintain current pace.")
        else:
            suggestions.append(f"✅ Projected to EXCEED target by {abs(gap)} seller(s). Keep going!")

        stalled = []
        for lead in assigned_leads:
            if lead.status in ('live', 'matched', 'closed'):
                continue
            lvd = lead.last_visit_days
            if lvd is None or lvd >= 7:
                stalled.append(lead)
        stalled = sorted(stalled, key=lambda l: l.conversion_score, reverse=True)[:5]

        results.append({
            'gabay': g,
            'target_live': target_live,
            'target_visits': target_visits,
            'live_count': live_count,
            'reg_count': reg_count,
            'nego_count': nego_count,
            'attempt_count': attempt_count,
            'total_visits': total_visits,
            'daily_visit_rate': round(daily_visit_rate, 1),
            'projected_visits': projected_visits,
            'projected_live': projected_live,
            'hot_forecast': hot_forecast,
            'gap': gap,
            'visit_gap': visit_gap,
            'weekly_visits': weekly_visits,
            'prev_weekly': prev_weekly,
            'total_regs_month': len(regs_this_month),
            'total_live_month': len(live_this_month),
            'prev_total_visits': len(prev_visits),
            'prev_total_regs': len(prev_regs),
            'prev_total_live': len(prev_live),
            'suggestions': suggestions,
            'stalled': stalled,
            'conv_rate': round(conv_rate * 100, 1),
            'reg_prob': round(reg_prob * 100, 1),
            'nego_prob': round(nego_prob * 100, 1),
            'att_prob': round(att_prob * 100, 1),
        })

    results.sort(key=lambda r: r['gap'], reverse=True)

    return render_template('reports/forecast.html',
        results=results,
        month_str=month_str,
        month_label=month_start.strftime('%B %Y'),
        prev_month_label=prev_start.strftime('%B %Y'),
        days_in_month=days_in_month,
        working_elapsed=working_elapsed,
        working_remaining=working_remaining,
        elapsed_holiday_list=elapsed_holiday_list,
        remaining_holiday_list=remaining_holiday_list,
        suspended_raw=suspended_raw,
        suspended_labels=suspended_labels,
        is_current_month=is_current_month,
        week_ranges=week_ranges,
        prev_week_ranges=prev_week_ranges,
        today=today,
    )


@app.route('/reports/wow')
@login_required
def report_wow():
    if not current_user.is_supervisor and not current_user.is_lazada:
        flash('Access denied.', 'danger')
        return redirect(url_for('reports'))

    from calendar import monthrange
    import datetime as _dt

    today = date.today()
    month_str = request.args.get('month', today.strftime('%Y-%m'))
    view = request.args.get('view', 'gabay')  # gabay | project | overall

    try:
        year, mon = int(month_str[:4]), int(month_str[5:7])
    except Exception:
        year, mon = today.year, today.month
        month_str = f'{year:04d}-{mon:02d}'

    _, days_in_month = monthrange(year, mon)
    month_start = date(year, mon, 1)
    month_end   = date(year, mon, days_in_month)

    # Previous month
    if mon == 1:
        prev_year, prev_mon = year - 1, 12
    else:
        prev_year, prev_mon = year, mon - 1
    _, prev_days = monthrange(prev_year, prev_mon)
    prev_start = date(prev_year, prev_mon, 1)
    prev_end   = date(prev_year, prev_mon, prev_days)

    # Week ranges (current month: calendar weeks 1-5 aligned to month start)
    week_ranges = []
    for w in range(5):
        ws = month_start + _dt.timedelta(days=w * 7)
        we = min(month_start + _dt.timedelta(days=(w + 1) * 7 - 1), month_end)
        if ws <= month_end:
            week_ranges.append((w + 1, ws, we))

    prev_week_ranges = []
    for w in range(5):
        ws = prev_start + _dt.timedelta(days=w * 7)
        we = min(prev_start + _dt.timedelta(days=(w + 1) * 7 - 1), prev_end)
        if ws <= prev_end:
            prev_week_ranges.append((w + 1, ws, we))

    gabays = User.query.filter_by(role='gabay', is_active=True).order_by(User.full_name).all()

    # Registration = visits with outcome 'registered' (lead reached registration/live stage)
    # Live = leads in status 'live' or 'matched' with a visit in that period
    # This uses actual visit data since Registration table is populated separately

    # Build set of live/matched lead IDs for fast lookup
    live_lead_ids = {l.id for l in Lead.query.filter(Lead.status.in_(['live', 'matched'])).all()}

    def week_stats(visits_list, ranges):
        rows = []
        for w_num, ws, we in ranges:
            pv = [v for v in visits_list if ws <= v.visited_at.date() <= we]
            rows.append({
                'week': w_num, 'start': ws, 'end': we,
                'visits': len(pv),
                'registrations': sum(1 for v in pv if v.outcome == 'registered'),
                'live': sum(1 for v in pv if v.outcome == 'registered' and v.lead_id in live_lead_ids),
            })
        return rows

    def period_totals(visits_list):
        regs = sum(1 for v in visits_list if v.outcome == 'registered')
        live = sum(1 for v in visits_list if v.outcome == 'registered' and v.lead_id in live_lead_ids)
        return {'visits': len(visits_list), 'registrations': regs, 'live': live}

    gabay_rows = []
    for g in gabays:
        curr_vis = Visit.query.filter(
            Visit.gabay_id == g.id,
            func.date(Visit.visited_at) >= month_start,
            func.date(Visit.visited_at) <= month_end,
        ).all()
        prev_vis = Visit.query.filter(
            Visit.gabay_id == g.id,
            func.date(Visit.visited_at) >= prev_start,
            func.date(Visit.visited_at) <= prev_end,
        ).all()
        gabay_rows.append({
            'gabay': g,
            'curr_weekly': week_stats(curr_vis, week_ranges),
            'prev_weekly': week_stats(prev_vis, prev_week_ranges),
            'curr_total': period_totals(curr_vis),
            'prev_total': period_totals(prev_vis),
        })

    # Overall team totals across all gabays
    def sum_weeks(rows_list, n_weeks):
        totals = [{'week': i+1, 'visits': 0, 'registrations': 0, 'live': 0} for i in range(n_weeks)]
        for row in rows_list:
            for i, w in enumerate(row):
                if i < n_weeks:
                    totals[i]['visits'] += w['visits']
                    totals[i]['registrations'] += w['registrations']
                    totals[i]['live'] += w['live']
        return totals

    n_curr = len(week_ranges)
    n_prev = len(prev_week_ranges)
    overall_curr_weekly = sum_weeks([r['curr_weekly'] for r in gabay_rows], n_curr)
    overall_prev_weekly = sum_weeks([r['prev_weekly'] for r in gabay_rows], n_prev)
    overall_curr_total = {
        'visits': sum(r['curr_total']['visits'] for r in gabay_rows),
        'registrations': sum(r['curr_total']['registrations'] for r in gabay_rows),
        'live': sum(r['curr_total']['live'] for r in gabay_rows),
    }
    overall_prev_total = {
        'visits': sum(r['prev_total']['visits'] for r in gabay_rows),
        'registrations': sum(r['prev_total']['registrations'] for r in gabay_rows),
        'live': sum(r['prev_total']['live'] for r in gabay_rows),
    }

    # Per-project breakdown
    project_leads = Lead.query.filter(Lead.project.isnot(None), Lead.project != '').all()
    projects_set = sorted(set(l.project for l in project_leads))
    project_rows = []
    for proj in projects_set:
        p_leads = [l for l in project_leads if l.project == proj]
        lead_ids = [l.id for l in p_leads]

        curr_vis = Visit.query.filter(
            Visit.lead_id.in_(lead_ids),
            func.date(Visit.visited_at) >= month_start,
            func.date(Visit.visited_at) <= month_end,
        ).all()
        prev_vis = Visit.query.filter(
            Visit.lead_id.in_(lead_ids),
            func.date(Visit.visited_at) >= prev_start,
            func.date(Visit.visited_at) <= prev_end,
        ).all()
        project_rows.append({
            'name': proj,
            'total_leads': len(p_leads),
            'curr_weekly': week_stats(curr_vis, week_ranges),
            'prev_weekly': week_stats(prev_vis, prev_week_ranges),
            'curr_total': period_totals(curr_vis),
            'prev_total': period_totals(prev_vis),
        })

    return render_template('reports/wow.html',
        month_str=month_str,
        month_label=month_start.strftime('%B %Y'),
        prev_month_label=prev_start.strftime('%B %Y'),
        week_ranges=week_ranges,
        prev_week_ranges=prev_week_ranges,
        gabay_rows=gabay_rows,
        overall_curr_weekly=overall_curr_weekly,
        overall_prev_weekly=overall_prev_weekly,
        overall_curr_total=overall_curr_total,
        overall_prev_total=overall_prev_total,
        project_rows=project_rows,
        view=view,
        today=today,
    )


@app.route('/reports/wow/week')
@login_required
def report_wow_week():
    """Week drill-down: all visits for a specific week vs same week previous month."""
    if not current_user.is_supervisor and not current_user.is_lazada:
        flash('Access denied.', 'danger')
        return redirect(url_for('reports'))

    from calendar import monthrange
    import datetime as _dt

    today = date.today()
    month_str  = request.args.get('month', today.strftime('%Y-%m'))
    week_num   = int(request.args.get('week', 1))
    scope      = request.args.get('scope', 'overall')   # overall | gabay_ID | project_NAME
    back_view  = request.args.get('view', 'overall')

    try:
        year, mon = int(month_str[:4]), int(month_str[5:7])
    except Exception:
        year, mon = today.year, today.month
        month_str = f'{year:04d}-{mon:02d}'

    _, days_in_month = monthrange(year, mon)
    month_start = date(year, mon, 1)
    month_end   = date(year, mon, days_in_month)

    if mon == 1:
        prev_year, prev_mon = year - 1, 12
    else:
        prev_year, prev_mon = year, mon - 1
    _, prev_days = monthrange(prev_year, prev_mon)
    prev_start = date(prev_year, prev_mon, 1)
    prev_end   = date(prev_year, prev_mon, prev_days)

    # Current week boundaries
    w_idx = week_num - 1
    curr_ws = month_start + _dt.timedelta(days=w_idx * 7)
    curr_we = min(month_start + _dt.timedelta(days=(w_idx + 1) * 7 - 1), month_end)

    # Same week number in previous month
    prev_ws = prev_start + _dt.timedelta(days=w_idx * 7)
    prev_we = min(prev_start + _dt.timedelta(days=(w_idx + 1) * 7 - 1), prev_end)

    live_lead_ids = {l.id for l in Lead.query.filter(Lead.status.in_(['live', 'matched'])).all()}

    def enrich(visits):
        result = []
        for v in visits:
            lead = Lead.query.get(v.lead_id)
            gabay = User.query.get(v.gabay_id)
            result.append({
                'visit': v,
                'lead': lead,
                'gabay': gabay,
                'is_reg': v.outcome == 'registered',
                'is_live': v.outcome == 'registered' and v.lead_id in live_lead_ids,
            })
        result.sort(key=lambda x: x['visit'].visited_at, reverse=True)
        return result

    # Build base query filter depending on scope
    def visits_in(ws, we, extra_filters):
        q = Visit.query.filter(
            func.date(Visit.visited_at) >= ws,
            func.date(Visit.visited_at) <= we,
        )
        for f in extra_filters:
            q = q.filter(f)
        return q.order_by(Visit.visited_at.desc()).all()

    scope_label = 'All Gabays'
    extra = []
    gabay_filter = None
    project_filter = None

    if scope.startswith('gabay_'):
        gabay_id = int(scope.split('_', 1)[1])
        gabay_filter = User.query.get(gabay_id)
        scope_label = gabay_filter.display_name if gabay_filter else scope
        extra = [Visit.gabay_id == gabay_id]
    elif scope.startswith('project_'):
        project_filter = scope[8:]
        scope_label = project_filter
        proj_lead_ids = [l.id for l in Lead.query.filter_by(project=project_filter).all()]
        extra = [Visit.lead_id.in_(proj_lead_ids)] if proj_lead_ids else [Visit.id == -1]

    curr_visits = enrich(visits_in(curr_ws, curr_we, extra))
    prev_visits = enrich(visits_in(prev_ws, prev_we, extra))

    def totals(enriched):
        return {
            'visits': len(enriched),
            'registrations': sum(1 for e in enriched if e['is_reg']),
            'live': sum(1 for e in enriched if e['is_live']),
        }

    return render_template('reports/wow_week.html',
        month_str=month_str,
        month_label=month_start.strftime('%B %Y'),
        prev_month_label=prev_start.strftime('%B %Y'),
        week_num=week_num,
        curr_ws=curr_ws, curr_we=curr_we,
        prev_ws=prev_ws, prev_we=prev_we,
        curr_visits=curr_visits,
        prev_visits=prev_visits,
        curr_totals=totals(curr_visits),
        prev_totals=totals(prev_visits),
        scope=scope,
        scope_label=scope_label,
        back_view=back_view,
        today=today,
    )


@app.route('/reports/export/leads')
@login_required
def export_leads():
    if not current_user.is_supervisor and not current_user.is_lazada:
        flash('Access denied.', 'danger')
        return redirect(url_for('reports'))
    leads = Lead.query.all()
    rows = []
    for l in leads:
        rows.append({
            'ID': l.id,
            'Seller Name': l.seller_name,
            'Lazada ID': l.lazada_id or '',
            'Contact': l.contact_number or '',
            'Email': l.email or '',
            'Barangay': l.barangay or '',
            'City': l.city or '',
            'Province': l.province or '',
            'Category': l.category or '',
            'Priority Tier': l.priority_tier or '',
            'Status': l.status_label,
            'Gabay': l.assigned_gabay.full_name if l.assigned_gabay else '',
            'Assigned At': l.assigned_at.strftime('%Y-%m-%d') if l.assigned_at else '',
            'Imported': l.imported_at.strftime('%Y-%m-%d') if l.imported_at else '',
            'Batch Ref': l.batch_ref or '',
            'Notes': l.notes or '',
        })
    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Leads')
    buf.seek(0)
    return send_file(buf, download_name='LSAMS_Leads_Export.xlsx',
                     as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


# ─── INIT DB ─────────────────────────────────────────────────────────────────

def seed_demo_data():
    if User.query.count() > 0:
        return
    # Superadmin — overrides all
    superadmin = User(username='superadmin', full_name='Sir Abbie (Power User)',
                      email='superadmin@lsams.local', role='superadmin')
    superadmin.set_password('Super@2026')
    db.session.add(superadmin)
    # Create default admin
    admin = User(username='admin', full_name='System Administrator', email='admin@lsams.local', role='admin')
    admin.set_password('Admin@2026')
    db.session.add(admin)
    # Create manager
    mgr = User(username='manager', full_name='Operations Manager', email='manager@lsams.local', role='manager')
    mgr.set_password('Manager@2026')
    db.session.add(mgr)
    # Lazada read-only users
    for uname, fname, email in [
        ('lance', 'Lance (Lazada)', 'lance@lazada.com'),
        ('grace', 'Grace (Lazada)', 'grace@lazada.com'),
        ('lazadamgr', 'LazadaMGR', 'mgr@lazada.com'),
    ]:
        u = User(username=uname, full_name=fname, email=email, role='lazada')
        u.set_password('Lazada@2026')
        db.session.add(u)
    # Create sample Gabay
    gabay_data = [
        ('abigail.bulasco', 'Abigail Bulasco', 'abigail@lsams.local'),
        ('arvie.bagalando', 'Arvie Bagalando', 'arvie@lsams.local'),
        ('ellen.remandiman', 'Ellen Remandiman', 'ellen@lsams.local'),
        ('jenerous.sonio', 'Jenerous Sonio', 'jenerous@lsams.local'),
        ('jenca.sunio', 'Jenca Sunio', 'jenca@lsams.local'),
        ('karen.villarama', 'Karen Krizel Villarama', 'karen@lsams.local'),
        ('karl.mirabuenas', 'Karl Michael Mirabuenas', 'karl@lsams.local'),
        ('kaycee.labial', 'Kaycee Joyce Labial', 'kaycee@lsams.local'),
        ('mariecris.nicolas', 'Marie Cris Nicolas', 'mariecris@lsams.local'),
    ]
    gabay_users = []
    for uname, fname, email in gabay_data:
        u = User(username=uname, full_name=fname, email=email, role='gabay')
        u.set_password('Gabay@2026')
        db.session.add(u)
        gabay_users.append(u)
    db.session.commit()
    # Leads table starts empty — import real data via the Import Leads page.


# ─── DATA IMPORT (for Railway migration, superadmin only) ────────────────────

@app.route('/admin/import-data', methods=['GET', 'POST'])
@login_required
def import_data():
    if not current_user.is_superadmin:
        return 'Superadmin only', 403
    if request.method == 'GET':
        return '''<html><body style="font-family:sans-serif;padding:40px;max-width:600px">
        <h2>Import Data to Cloud Database</h2>
        <p>Upload your <code>data_export.json</code> file to populate the cloud database.</p>
        <form method="POST" enctype="multipart/form-data">
          <input type="file" name="datafile" accept=".json" required style="margin-bottom:16px;display:block">
          <button type="submit" style="background:#1F3864;color:white;border:none;padding:10px 24px;
                  border-radius:8px;font-size:14px;cursor:pointer">Import All Data</button>
        </form></body></html>'''

    f = request.files.get('datafile')
    if not f:
        return 'No file uploaded', 400
    data = json.loads(f.read().decode('utf-8'))

    from werkzeug.security import generate_password_hash
    imported = {'users': 0, 'leads': 0, 'visits': 0}

    # Users
    for u in data.get('users', []):
        if not User.query.filter_by(username=u['username']).first():
            obj = User(username=u['username'], full_name=u['full_name'],
                       email=u['email'] or None, role=u['role'],
                       password_hash=u['password_hash'],
                       assigned_city=u['assigned_city'] or None,
                       is_active=u.get('is_active', True))
            db.session.add(obj)
            imported['users'] += 1

    db.session.flush()

    # Build id mapping (old_id -> new_id) for users
    user_map = {u['id']: User.query.filter_by(username=u['username']).first().id
                for u in data.get('users', [])}

    # Leads
    for l in data.get('leads', []):
        if not Lead.query.filter_by(id=l['id']).first():
            from datetime import datetime
            obj = Lead(
                seller_name=l['seller_name'], contact_number=l['contact_number'],
                city=l['city'], category=l['category'], status=l['status'],
                gabay_id=user_map.get(l['gabay_id']) if l['gabay_id'] else None,
                address=l['address'], link=l['link'], notes=l['notes'],
                project=l['project'], cluster=l['cluster'],
                priority_tier=l['priority_tier'],
                assigned_at=datetime.fromisoformat(l['assigned_at']) if l['assigned_at'] else None,
                imported_at=datetime.fromisoformat(l['imported_at']) if l['imported_at'] else None,
            )
            db.session.add(obj)
            imported['leads'] += 1

    db.session.flush()

    # Visits
    lead_map = {l['id']: Lead.query.filter_by(seller_name=l['seller_name'], city=l['city']).first()
                for l in data.get('leads', [])}
    for v in data.get('visits', []):
        from datetime import datetime, date
        lead_obj = lead_map.get(v['lead_id'])
        if lead_obj:
            obj = Visit(
                lead_id=lead_obj.id,
                gabay_id=user_map.get(v['gabay_id']),
                visited_at=datetime.fromisoformat(v['visited_at']) if v['visited_at'] else datetime.utcnow(),
                outcome=v['outcome'], notes=v['notes'],
                gps_lat=v['gps_lat'], gps_lng=v['gps_lng'],
                gps_address=v['gps_address'],
                follow_up_date=date.fromisoformat(v['follow_up_date']) if v['follow_up_date'] else None,
                photos=v['photos'] or None,
            )
            db.session.add(obj)
            imported['visits'] += 1

    db.session.commit()
    return f'''<html><body style="font-family:sans-serif;padding:40px">
    <h2 style="color:#15803d">✅ Import Complete!</h2>
    <p>Users: <b>{imported["users"]}</b> imported</p>
    <p>Leads: <b>{imported["leads"]}</b> imported</p>
    <p>Visits: <b>{imported["visits"]}</b> imported</p>
    <a href="/" style="color:#1F3864;font-weight:700">→ Go to Dashboard</a>
    </body></html>'''


# ─── SUPERADMIN USER MANAGEMENT ──────────────────────────────────────────────

# ── WhatsApp Webhook ──────────────────────────────────────────────────────────

@app.route('/webhook/whatsapp', methods=['GET'])
def whatsapp_verify():
    """Meta calls this GET to verify the webhook URL."""
    verify_token = os.environ.get('WHATSAPP_VERIFY_TOKEN', 'lsams_webhook_2026')
    mode      = request.args.get('hub.mode')
    token     = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    if mode == 'subscribe' and token == verify_token:
        return challenge, 200
    return 'Forbidden', 403


@app.route('/webhook/whatsapp', methods=['POST'])
def whatsapp_incoming():
    """Meta POSTs incoming messages here."""
    import threading
    data = request.get_json(silent=True) or {}
    app.logger.info(f'[WA] Incoming payload: {data}')
    def _process():
        with app.app_context():
            try:
                from whatsapp import handle_incoming
                handle_incoming(data)
            except Exception as e:
                app.logger.error(f'[WA] handle_incoming error: {e}', exc_info=True)
    threading.Thread(target=_process, daemon=True).start()
    return 'OK', 200


@app.route('/admin/whatsapp-test')
@login_required
def whatsapp_test():
    if not current_user.is_supervisor:
        return 'Access denied', 403
    import requests as _req
    token     = os.environ.get('WHATSAPP_TOKEN', '')
    phone_id  = os.environ.get('WHATSAPP_PHONE_ID', '1125313127339997')
    to_number = request.args.get('to', '639561331809')
    url       = f'https://graph.facebook.com/v25.0/{phone_id}/messages'
    payload   = {'messaging_product':'whatsapp','to':to_number,'type':'text','text':{'body':'✅ LSAMS bot test — working!'}}
    headers   = {'Authorization':f'Bearer {token}','Content-Type':'application/json'}
    try:
        r = _req.post(url, json=payload, headers=headers, timeout=10)
        return f'<pre>Status: {r.status_code}\nToken set: {"YES" if token else "NO (empty!)"}\nPhone ID: {phone_id}\nResponse: {r.text}</pre>'
    except Exception as e:
        return f'<pre>Exception: {e}\nToken set: {"YES" if token else "NO"}</pre>'


# ── Telegram Webhook ──────────────────────────────────────────────────────────

@app.route('/webhook/telegram', methods=['POST'])
def telegram_incoming():
    """Telegram POSTs incoming updates here."""
    import threading
    data = request.get_json(silent=True) or {}
    app.logger.info(f'[TG] Incoming update: {str(data)[:200]}')
    def _process():
        with app.app_context():
            try:
                from telegram_bot import handle_update
                handle_update(data)
            except Exception as e:
                app.logger.error(f'[TG] handle_update error: {e}', exc_info=True)
    threading.Thread(target=_process, daemon=True).start()
    return 'OK', 200


@app.route('/admin/telegram-setup')
@login_required
def telegram_setup():
    """Register the Telegram webhook with Telegram's servers (run once after deploy)."""
    if not current_user.is_supervisor:
        return 'Access denied', 403
    import requests as _req
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    if not token:
        return '<pre>❌ TELEGRAM_BOT_TOKEN not set in Railway environment variables.</pre>'
    base_url = f'https://{request.host}'
    webhook_url = f'{base_url}/webhook/telegram'
    try:
        r = _req.post(
            f'https://api.telegram.org/bot{token}/setWebhook',
            json={'url': webhook_url, 'allowed_updates': ['message', 'edited_message']},
            timeout=10,
        )
        result = r.json()
        status = '✅ Webhook registered!' if result.get('ok') else '❌ Failed'
        return (
            f'<pre>{status}\n\n'
            f'Webhook URL: {webhook_url}\n\n'
            f'Telegram response:\n{json.dumps(result, indent=2)}\n\n'
            f'Next step: Have Gabay agents open the bot and send:\n'
            f'  /start their_lsams_username\n\n'
            f'Managers can also link their Telegram to receive visit alerts.</pre>'
        )
    except Exception as e:
        return f'<pre>Exception: {e}</pre>'


@app.route('/admin/telegram-test')
@login_required
def telegram_test():
    """Send a test message to the current user's linked Telegram."""
    if not current_user.is_supervisor:
        return 'Access denied', 403
    from telegram_bot import send_message as tg_send
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    if not token:
        return '<pre>❌ TELEGRAM_BOT_TOKEN not set in Railway environment variables.</pre>'
    chat_id = current_user.telegram_chat_id
    if not chat_id:
        return (
            '<pre>⚠️ Your account has no Telegram linked.\n\n'
            'Open the bot on your phone and send: /start your_lsams_username\n'
            'Then come back here and refresh.</pre>'
        )
    result = tg_send(chat_id, '✅ LSAMS Telegram bot test — working!')
    return f'<pre>Sent to chat_id {chat_id}\nResult: {json.dumps(result, indent=2)}</pre>'


@app.route('/admin/telegram-report-now')
@login_required
def telegram_report_now():
    """Send the daily report immediately (for testing or manual trigger)."""
    if not current_user.is_supervisor:
        return 'Access denied', 403
    from datetime import timezone, timedelta as _td
    _PHT = timezone(_td(hours=8))
    hour = datetime.now(_PHT).hour
    period = 'morning' if hour < 12 else 'evening'
    _send_daily_report(period)
    return f'<pre>✅ Report sent to all linked managers!\n\nPeriod: {period}\n\nRefresh and check Telegram.</pre>'


@app.route('/admin/telegram-unlink/<int:user_id>', methods=['POST'])
@login_required
def telegram_unlink(user_id):
    """Unlink a user's Telegram account (superadmin only)."""
    if not current_user.is_supervisor:
        abort(403)
    u = User.query.get_or_404(user_id)
    u.telegram_chat_id = None
    db.session.commit()
    return jsonify({'ok': True, 'name': u.full_name})


@app.route('/admin/send-gabay-briefings', methods=['POST'])
@login_required
def admin_send_gabay_briefings():
    """Send a morning WhatsApp briefing to every active Gabay."""
    if not current_user.is_supervisor:
        return jsonify({'error': 'Access denied'}), 403
    from whatsapp import send_message
    from datetime import timedelta
    gabays = User.query.filter_by(role='gabay', is_active=True).all()
    sent, skipped = 0, 0
    stalled_cutoff = datetime.utcnow() - timedelta(days=7)
    for g in gabays:
        if not g.mobile:
            skipped += 1
            continue
        stats = _gabay_stats(g.id)
        high_priority = Lead.query.filter(
            Lead.gabay_id == g.id,
            Lead.status.in_(['negotiation', 'registration'])
        ).count()
        stalled = Lead.query.filter(
            Lead.gabay_id == g.id,
            Lead.status.in_(['assigned', 'attempting']),
            ~Lead.id.in_(
                db.session.query(Visit.lead_id).filter(Visit.visited_at >= stalled_cutoff)
            )
        ).count()
        msg = (
            f"🌸 Good morning, {g.full_name.split()[0]}!\n"
            f"Here's your Maria briefing for today:\n\n"
            f"📋 {stats['total']} sellers assigned\n"
            f"🔥 {high_priority} in negotiation/registration\n"
            f"⚠️ {stalled} stalled leads (no visit in 7 days)\n"
            f"✅ {stats['live']} live sellers total\n\n"
            f"Tip: Focus on your high-priority leads first!\n"
            f"Good luck today! 💪 — LSAMS Maria"
        )
        to = g.mobile.replace('+', '').replace(' ', '').replace('-', '')
        if not to.startswith('63'):
            to = '63' + to.lstrip('0')
        try:
            send_message(to, msg)
            sent += 1
        except Exception:
            skipped += 1
    return jsonify({'sent': sent, 'skipped': skipped})


@app.route('/admin/send-manager-digest', methods=['POST'])
@login_required
def admin_send_manager_digest():
    """Send a daily performance digest to all active managers/supervisors."""
    if not current_user.is_supervisor:
        return jsonify({'error': 'Access denied'}), 403
    from whatsapp import send_message
    from datetime import timedelta
    yesterday_start = (datetime.utcnow() - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_end = yesterday_start + timedelta(days=1)
    visits_yesterday = Visit.query.filter(
        Visit.visited_at >= yesterday_start,
        Visit.visited_at < yesterday_end
    ).count()
    live_yesterday = Lead.query.filter(
        Lead.status == 'live',
        Lead.assigned_at >= yesterday_start,
        Lead.assigned_at < yesterday_end
    ).count()
    total_live = Lead.query.filter_by(status='live').count()
    total_pool = Lead.query.count()
    gabays = User.query.filter_by(role='gabay', is_active=True).all()
    top_performers = []
    for g in gabays:
        g_live = Lead.query.filter_by(gabay_id=g.id, status='live').count()
        top_performers.append((g.full_name.split()[0], g_live))
    top_performers.sort(key=lambda x: -x[1])

    top_lines = '\n'.join(
        f"  {'🥇' if i==0 else '🥈' if i==1 else '🥉'} {name}: {cnt} live"
        for i, (name, cnt) in enumerate(top_performers[:3])
    ) if top_performers else '  (no data)'

    today_str = datetime.now().strftime('%B %d, %Y')
    msg = (
        f"📊 Good morning! Maria's Daily Digest\n"
        f"📅 {today_str}\n\n"
        f"Yesterday's Performance:\n"
        f"👣 {visits_yesterday} visits logged\n"
        f"✅ {live_yesterday} new live sellers\n"
        f"📈 Total live: {total_live} / {total_pool} pool\n\n"
        f"Top Performers (all-time live):\n{top_lines}\n\n"
        f"— LSAMS Maria 🌸"
    )
    managers = User.query.filter(
        User.role.in_(['manager', 'supervisor', 'admin']),
        User.is_active == True,
        User.mobile.isnot(None)
    ).all()
    sent, skipped = 0, 0
    for m in managers:
        to = m.mobile.replace('+', '').replace(' ', '').replace('-', '')
        if not to.startswith('63'):
            to = '63' + to.lstrip('0')
        try:
            send_message(to, msg)
            sent += 1
        except Exception:
            skipped += 1
    return jsonify({'sent': sent, 'skipped': skipped})


@app.route('/admin/ml/train', methods=['GET', 'POST'])
@login_required
def admin_ml_train():
    if not current_user.is_supervisor:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))

    from models import MLModelRun
    import threading

    if request.method == 'POST':
        run = MLModelRun(trained_by=current_user.id, status='pending')
        db.session.add(run)
        db.session.commit()

        def _bg_train(run_id, app_ref):
            import ml_engine
            ml_engine.train(app_ref, run_id=run_id)

        t = threading.Thread(target=_bg_train, args=(run.id, app), daemon=True)
        t.start()
        flash(f'Model training started (Run #{run.id}). Refresh in 30 seconds to see results.', 'info')
        return redirect(url_for('admin_ml_train'))

    # GET — show history and current model status
    import json as _json
    import os as _os
    runs = MLModelRun.query.order_by(MLModelRun.trained_at.desc()).limit(10).all()
    latest = next((r for r in runs if r.status == 'success'), None)
    top_features = []
    if latest and latest.top_features:
        try:
            top_features = _json.loads(latest.top_features)
        except Exception:
            pass

    from ml_engine import MODEL_PATH, MIN_POSITIVE
    model_exists = _os.path.exists(MODEL_PATH)

    live_count = Lead.query.filter(Lead.status.in_(['live', 'matched'])).count()
    total_scored = Lead.query.filter(Lead.ml_score.isnot(None)).count()

    return render_template('admin/ml_train.html',
        runs=runs,
        latest=latest,
        top_features=top_features,
        model_exists=model_exists,
        live_count=live_count,
        min_positive=MIN_POSITIVE,
        total_scored=total_scored,
    )


@app.route('/admin/db-status')
@login_required
def admin_db_status():
    if not current_user.is_superadmin:
        return 'Superadmin only', 403
    from sqlalchemy import func
    total = Lead.query.count()
    by_status = db.session.query(Lead.status, func.count(Lead.id))\
        .group_by(Lead.status).order_by(func.count(Lead.id).desc()).all()
    # Find duplicates by seller_name + city
    dup_query = db.session.query(
        Lead.seller_name, Lead.city, func.count(Lead.id).label('cnt')
    ).group_by(Lead.seller_name, Lead.city)\
     .having(func.count(Lead.id) > 1)\
     .order_by(func.count(Lead.id).desc()).limit(20).all()
    rows_html = ''.join(
        f'<tr><td>{s}</td><td style="text-align:right;font-weight:700;color:#1F3864">{c}</td></tr>'
        for s, c in by_status
    )
    dup_html = ''.join(
        f'<tr><td>{name}</td><td>{city or "—"}</td>'
        f'<td style="color:#b91c1c;font-weight:700;text-align:center">{cnt}x</td></tr>'
        for name, city, cnt in dup_query
    ) or '<tr><td colspan="3" style="color:#15803d;text-align:center">No duplicates found</td></tr>'
    with_lazada_id = Lead.query.filter(Lead.lazada_id != None).count()
    without_lazada_id = Lead.query.filter(Lead.lazada_id == None).count()
    return f'''<html><head><style>
        body{{font-family:sans-serif;padding:32px;max-width:700px}}
        table{{width:100%;border-collapse:collapse;margin-bottom:24px}}
        th{{background:#1F3864;color:white;padding:8px 12px;text-align:left}}
        td{{padding:8px 12px;border-bottom:1px solid #e5e7eb}}
        h2{{color:#1F3864}} h3{{color:#4a5568;margin-top:28px}}
        .warn{{background:#FEF2F2;border:1px solid #fca5a5;border-radius:8px;padding:14px;margin:16px 0}}
        .ok{{background:#F0FDF4;border:1px solid #86efac;border-radius:8px;padding:14px;margin:16px 0}}
    </style></head><body>
    <h2>Database Status</h2>
    <p>Total leads in database: <strong style="font-size:20px;color:#1F3864">{total}</strong></p>
    <div class="ok">
      ✅ <strong>Leads WITH lazada_id (Excel imports):</strong> {with_lazada_id}<br>
      ✅ <strong>Leads WITHOUT lazada_id (original/manual):</strong> {without_lazada_id}
    </div>
    <h3>Leads by Current Status</h3>
    <table><tr><th>Status</th><th style="text-align:right">Count</th></tr>{rows_html}</table>
    <h3>Possible Duplicates (same name + city, top 20)</h3>
    <table><tr><th>Seller Name</th><th>City</th><th style="text-align:center">Copies</th></tr>
    {dup_html}</table>
    <div class="warn">
      ⚠️ <strong>If Excel imports are all duplicates</strong>, use the button below to delete them.<br>
      This will remove all {with_lazada_id} leads that have a lazada_id (came from Excel import).<br>
      Your original {without_lazada_id} leads will NOT be touched.<br><br>
      <form method="POST" action="/admin/delete-excel-imports"
            onsubmit="return confirm('Delete {with_lazada_id} Excel-imported leads? This cannot be undone.')">
        <button type="submit" style="background:#b91c1c;color:white;border:none;
                padding:10px 20px;border-radius:8px;font-size:14px;cursor:pointer;font-weight:700">
          🗑️ Delete All Excel-Imported Leads ({with_lazada_id})
        </button>
      </form>
    </div>
    <a href="/dashboard" style="color:#1F3864;font-weight:700">← Back to Dashboard</a>
    </body></html>'''


@app.route('/admin/migrate-gabay-name')
@login_required
def migrate_gabay_name():
    if not current_user.is_superadmin:
        return 'Superadmin only', 403
    try:
        # Add column safely
        db.session.execute(text(
            "ALTER TABLE users ADD COLUMN gabay_name VARCHAR(100)"
        ))
        db.session.commit()

        # Map by username (reliable) → full_name + gabay_name
        mappings = [
            # username, full_name,             gabay_name
            ('karen',     'Karen Villarama',   'Karen'),
            ('Karl',      'Karl Mirabuenos',   'Karl'),
            ('Kaycee',    'Kaycee Labial',     'Kaycee'),
            ('Jenica',    'Jenica Sunio',      'Jenica'),
            ('Jenerous',  'Jenerous Sonio',    'Jenerous'),
            ('Abi',       'Abigail Bulacso',   'Abigail'),
            ('Mariecris', 'Marie Cris Nicolas','Marie Cris'),
            ('Ellen',     'Ellen Remandiman',  'Ellen'),
            ('Arvie',     'Arvie Bagalando',   'Arvie'),
        ]
        updated = 0
        for uname, full, gname in mappings:
            result = db.session.execute(text(
                "UPDATE users SET full_name = :full, gabay_name = :gname "
                "WHERE username = :uname"
            ), {'full': full, 'gname': gname, 'uname': uname})
            updated += result.rowcount
        db.session.commit()

        rows = ''.join(
            f'<tr><td>{uname}</td><td>{full}</td>'
            f'<td style="color:#15803d;font-weight:700">{gname}</td></tr>'
            for uname, full, gname in mappings
        )
        return f'''<html><body style="font-family:sans-serif;padding:32px;max-width:700px">
        <h2 style="color:#15803d">✅ Migration done! ({updated} users updated)</h2>
        <table style="width:100%;border-collapse:collapse;font-family:sans-serif">
        <tr style="background:#1F3864;color:white">
          <th style="padding:8px">Username</th>
          <th style="padding:8px">Full Name</th>
          <th style="padding:8px">Gabay Name (shown in system)</th>
        </tr>{rows}</table>
        <br>
        <p>Next step: <a href="/admin/full-reset" style="color:#b91c1c;font-weight:700">
        Delete all leads → /admin/full-reset</a></p>
        </body></html>'''
    except Exception as e:
        db.session.rollback()
        return f'<h2 style="color:red">Error: {e}</h2><pre>{e}</pre>'


@app.route('/admin/full-reset', methods=['GET', 'POST'])
@login_required
def admin_full_reset():
    if not current_user.is_superadmin:
        return 'Superadmin only', 403

    total_leads = Lead.query.count()

    # Correct name mapping: username → proper full_name
    name_fixes = {
        'karen':    'Karen Villarama',
        'Karl':     'Karl Mirabuenos',
        'Kaycee':   'Kaycee Labial',
        'Jenica':   'Jenica Sunio',
        'Jenerous': 'Jenerous Sonio',
        'Abi':      'Abigail Bulacso',
        'Mariecris':'Marie Cris Nicolas',
        'Ellen':    'Ellen Remandiman',
        'Arvie':    'Arvie Bagalando',
    }

    if request.method == 'GET':
        gabay_rows = ''.join(
            f'<tr><td>{old}</td><td style="color:#15803d;font-weight:700">→ {new}</td></tr>'
            for old, new in name_fixes.items()
        )
        return f'''<html><head><style>
        body{{font-family:sans-serif;padding:32px;max-width:680px}}
        table{{width:100%;border-collapse:collapse;margin:12px 0}}
        th{{background:#1F3864;color:white;padding:8px 12px;text-align:left}}
        td{{padding:8px 12px;border-bottom:1px solid #e5e7eb}}
        h2{{color:#1F3864}} .warn{{background:#FEF2F2;border:1px solid #fca5a5;
        border-radius:8px;padding:14px;margin:16px 0}}
        </style></head><body>
        <h2>🗑️ Full Lead Reset + Name Fix</h2>
        <div class="warn">
          <strong>This will:</strong><br>
          1. Delete ALL {total_leads} leads (and their visits, registrations, notifications)<br>
          2. Fix the 9 gabay agent names to proper full names<br><br>
          <strong>This cannot be undone. Make sure you have your Excel file ready to re-upload.</strong>
        </div>
        <h3>Gabay Name Updates</h3>
        <table><tr><th>Current Name</th><th>Will be updated to</th></tr>{gabay_rows}</table>
        <form method="POST" onsubmit="return confirm('Delete ALL {total_leads} leads and fix names? This cannot be undone.')">
          <button type="submit" style="background:#b91c1c;color:white;border:none;
                  padding:14px 32px;border-radius:8px;font-size:16px;
                  cursor:pointer;font-weight:800;margin-top:16px">
            ✅ Yes — Delete All Leads & Fix Names
          </button>
        </form>
        <br><a href="/dashboard" style="color:#4a5568;font-weight:700">← Cancel, go back</a>
        </body></html>'''

    # POST — delete everything then fix names
    try:
        db.session.execute(text("DELETE FROM notifications"))
        db.session.execute(text("DELETE FROM lead_assignment_history"))
        db.session.execute(text("DELETE FROM visits"))
        db.session.execute(text("DELETE FROM registrations"))
        db.session.execute(text("DELETE FROM leads"))

        # Delete fake gabay accounts (full Excel names)
        fake_names = [
            'VILLARAMA, MA. KAREN KRIZE', 'MIRABUENOS, KARL MICHAEL',
            'LABIAL, KAYCEE JOYCE', 'SUNIO, MARIA JENICA', 'SONIO, JENEROUS',
            'BULACSO, ABIGAIL', 'NICOLAS, MARIE CRIS', 'REMANDIMAN, ELLEN',
            'BAGALANDO,ROXAN'
        ]
        for fn in fake_names:
            db.session.execute(text(
                "DELETE FROM users WHERE full_name = :fn AND role = 'gabay'"
            ), {'fn': fn})

        # Fix real gabay names and set gabay_name
        gabay_name_map = {
            'Karen Villarama':   'Karen',
            'Karl Mirabuenos':   'Karl',
            'Kaycee Labial':     'Kaycee',
            'Jenica Sunio':      'Jenica',
            'Jenerous Sonio':    'Jenerous',
            'Abigail Bulacso':   'Abigail',
            'Marie Cris Nicolas':'Marie Cris',
            'Ellen Remandiman':  'Ellen',
            'Arvie Bagalando':   'Arvie',
        }
        for old_name, new_name in name_fixes.items():
            gname = gabay_name_map.get(new_name, new_name)
            db.session.execute(text(
                "UPDATE users SET full_name = :new, gabay_name = :gname "
                "WHERE full_name = :old AND role = 'gabay'"
            ), {'new': new_name, 'gname': gname, 'old': old_name})

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return f'<h2 style="color:red">Error: {e}</h2><a href="/admin/full-reset">Back</a>'

    gabay_count = User.query.filter_by(role='gabay', is_active=True).count()
    return f'''<html><body style="font-family:sans-serif;padding:32px;max-width:600px">
    <h2 style="color:#15803d">✅ Done!</h2>
    <p>All leads deleted. Leads remaining: <strong>0</strong></p>
    <p>Gabay agents in system: <strong style="color:#1F3864">{gabay_count}</strong></p>
    <p>Names updated to proper full names.</p>
    <p style="color:#b45309">Now go to <strong>Data Entry → Import</strong> to upload your Excel file fresh.</p>
    <a href="/dashboard" style="color:#1F3864;font-weight:700">→ Go to Dashboard</a>
    </body></html>'''


@app.route('/admin/import-pipeline', methods=['GET', 'POST'])
@login_required
def admin_import_pipeline():
    """Import pipeline CSV: update lead status + gabay assignment + cities. No duplicates."""
    if not current_user.is_superadmin:
        return 'Superadmin only', 403

    if request.method == 'GET':
        return '''<html><body style="font-family:sans-serif;padding:32px;max-width:640px">
        <h2>📥 Import Pipeline CSV</h2>
        <p>Upload the <strong>pipeline CSV file</strong>. This will:</p>
        <ul>
          <li>Match each lead by <strong>Leads ID (lazada_id)</strong></li>
          <li>Update <strong>status</strong> and <strong>gabay assignment</strong></li>
          <li>Set <strong>assigned_city</strong> per gabay based on their leads</li>
          <li>Skip rows with no valid Leads ID — no duplicates created</li>
        </ul>
        <form method="POST" enctype="multipart/form-data">
          <input type="file" name="csv_file" accept=".csv" required
                 style="display:block;margin-bottom:16px;font-size:15px">
          <button type="submit"
                  style="background:#1F3864;color:white;border:none;padding:12px 28px;
                         border-radius:8px;font-size:15px;cursor:pointer;font-weight:700">
            ✅ Upload & Update
          </button>
        </form>
        <br><a href="/dashboard" style="color:#4a5568">← Back to Dashboard</a>
        </body></html>'''

    # POST — process the CSV
    import csv, io
    from datetime import datetime

    f = request.files.get('csv_file')
    if not f:
        return 'No file uploaded', 400

    # Agent name (as written in CSV) → DB username
    AGENT_MAP = {
        'ARVIE':     'Arvie',
        'JENEROUS':  'Jenerous',
        'KAREN':     'karen',
        'KARL':      'Karl',
        'KAYCEE':    'Kaycee',
        'JENICA':    'Jenica',
        'JENICA SUNIO': 'Jenica',
        'ABI':       'Abi',
        'ABIGAIL':   'Abi',
        'MARIECRIS': 'Mariecris',
        'MARIE CRIS':'Mariecris',
        'MARIE':     'Mariecris',
        'ELLEN':     'Ellen',
    }

    STATUS_MAP = {
        'negotiation':         'negotiation',
        'assigned':            'assigned',
        'attempting to contact':'attempting',
        'attempting':          'attempting',
        'registration':        'registration',
        'live':                'live',
        'matched':             'matched',
        'closed':              'closed',
        'pool':                'pool',
    }

    # Pre-load gabay users — index by every possible name variant (uppercase)
    all_gabays = User.query.filter_by(role='gabay').all()
    gabay_by_key = {}
    for u in all_gabays:
        gabay_by_key[u.username.upper()] = u
        if u.gabay_name:
            for word in u.gabay_name.split():
                gabay_by_key[word.upper()] = u
        if u.full_name:
            for word in u.full_name.split():
                gabay_by_key[word.upper()] = u

    # Debug: show all keys built (only visible in GET response)
    _debug_keys = sorted(gabay_by_key.keys())

    content = f.read().decode('utf-8-sig', errors='replace')
    reader = csv.reader(io.StringIO(content))

    rows = list(reader)
    # Skip first 4 rows (3 header rows + possible blank/section rows)
    data_rows = rows[4:]

    updated = 0
    skipped_no_id = 0
    skipped_no_lead = 0
    skipped_no_agent = 0
    errors = []

    # Track cities per gabay user id → set of cities
    gabay_cities = {}

    for row in data_rows:
        if len(row) < 19:
            continue
        lazada_id = row[1].strip()
        if not lazada_id or len(lazada_id) < 10:
            skipped_no_id += 1
            continue

        agent_raw = row[15].strip().upper()
        status_raw = row[18].strip().lower()
        city_raw   = row[8].strip()

        # Find lead
        lead = Lead.query.filter_by(lazada_id=lazada_id).first()
        if not lead:
            skipped_no_lead += 1
            continue

        # Map status
        db_status = STATUS_MAP.get(status_raw)
        if not db_status:
            db_status = 'assigned' if agent_raw else 'pool'

        # Find gabay user — try AGENT_MAP first, then direct key lookup
        username_key = AGENT_MAP.get(agent_raw, agent_raw)
        gabay = gabay_by_key.get(username_key.upper()) or gabay_by_key.get(agent_raw)

        if gabay:
            lead.gabay_id = gabay.id
            lead.status = db_status
            if not lead.assigned_at:
                lead.assigned_at = datetime.utcnow()
            if city_raw and city_raw not in ('0', ''):
                gabay_cities.setdefault(gabay.id, set()).add(city_raw.title())
            updated += 1
        elif agent_raw:
            skipped_no_agent += 1
            errors.append(f"Unknown agent '{agent_raw}' for lead {lazada_id}")
        else:
            lead.status = 'pool'
            updated += 1

    # Commit lead updates
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return f'<h2 style="color:red">DB Error: {e}</h2>'

    # Update assigned_city per gabay
    city_updates = []
    gabay_by_id = {u.id: u for u in all_gabays}
    for gid, cities in gabay_cities.items():
        user = gabay_by_id.get(gid)
        if user:
            user.assigned_city = ', '.join(sorted(cities))
            city_updates.append(f"{user.display_name}: {user.assigned_city}")
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()

    error_html = ''
    if errors[:10]:
        error_html = '<h4 style="color:#b91c1c">Unknown agents (first 10):</h4><ul>' + \
                     ''.join(f'<li>{e}</li>' for e in errors[:10]) + '</ul>'

    city_html = '<br>'.join(city_updates) if city_updates else 'None'
    debug_html = f'<details><summary style="cursor:pointer;color:#6b7280;font-size:12px">Debug: DB keys built ({len(_debug_keys)})</summary>' \
                 f'<pre style="font-size:11px">{", ".join(_debug_keys)}</pre></details>'

    return f'''<html><body style="font-family:sans-serif;padding:32px;max-width:640px">
    <h2 style="color:#15803d">✅ Import Complete</h2>
    <table style="border-collapse:collapse;width:100%">
      <tr style="background:#f0fdf4"><td style="padding:8px 12px;border:1px solid #d1fae5"><strong>Leads updated</strong></td>
          <td style="padding:8px 12px;border:1px solid #d1fae5;color:#15803d;font-weight:800">{updated}</td></tr>
      <tr><td style="padding:8px 12px;border:1px solid #e2e8f0">No Leads ID (skipped)</td>
          <td style="padding:8px 12px;border:1px solid #e2e8f0">{skipped_no_id}</td></tr>
      <tr><td style="padding:8px 12px;border:1px solid #e2e8f0">Lead not in DB (skipped)</td>
          <td style="padding:8px 12px;border:1px solid #e2e8f0">{skipped_no_lead}</td></tr>
      <tr><td style="padding:8px 12px;border:1px solid #e2e8f0">Unknown agent (skipped)</td>
          <td style="padding:8px 12px;border:1px solid #e2e8f0">{skipped_no_agent}</td></tr>
    </table>
    <h3 style="margin-top:24px">Cities assigned per Gabay:</h3>
    <p style="font-size:13px;color:#374151;line-height:1.8">{city_html}</p>
    {error_html}
    {debug_html}
    <br><a href="/dashboard" style="color:#1F3864;font-weight:700">→ Go to Dashboard</a>
    &nbsp;&nbsp;<a href="/admin/import-pipeline" style="color:#6b7280">Upload another file</a>
    </body></html>'''


@app.route('/admin/delete-excel-imports', methods=['GET', 'POST'])
@login_required
def admin_delete_excel_imports():
    if not current_user.is_superadmin:
        return 'Superadmin only', 403

    count = Lead.query.filter(Lead.lazada_id != None).count()

    # Fake gabay usernames created by Excel import (full names)
    fake_names = [
        'VILLARAMA, MA. KAREN KRIZE', 'MIRABUENOS, KARL MICHAEL',
        'LABIAL, KAYCEE JOYCE', 'SUNIO, MARIA JENICA', 'SONIO, JENEROUS',
        'BULACSO, ABIGAIL', 'NICOLAS, MARIE CRIS', 'REMANDIMAN, ELLEN',
        'BAGALANDO,ROXAN'
    ]
    fake_users = User.query.filter(User.full_name.in_(fake_names)).all()
    fake_ids = [u.id for u in fake_users]
    leads_from_fake = Lead.query.filter(Lead.gabay_id.in_(fake_ids)).count() if fake_ids else 0
    leads_no_lazada_id = Lead.query.filter(Lead.lazada_id == None, Lead.gabay_id.in_(fake_ids) if fake_ids else False).count()

    if request.method == 'GET':
        return f'''<html><body style="font-family:sans-serif;padding:32px;max-width:700px">
        <h2 style="color:#1F3864">Database Cleanup</h2>
        <p>Leads with lazada_id (already deleted or remaining): <strong>{count}</strong></p>
        <p>Fake gabay accounts found: <strong style="color:#b91c1c">{len(fake_ids)}</strong>
           — {", ".join([u.full_name for u in fake_users])}</p>
        <p>Leads assigned to fake gabay accounts: <strong style="color:#b91c1c">{leads_from_fake}</strong></p>
        <hr style="margin:20px 0">
        <p><strong>Step 1:</strong> Delete leads with lazada_id ({count} leads)</p>
        <form method="POST" action="?step=lazada">
          <button type="submit" style="background:#b91c1c;color:white;border:none;
                  padding:10px 20px;border-radius:8px;font-size:14px;cursor:pointer;font-weight:700">
            Delete {count} leads with lazada_id
          </button>
        </form>
        <br>
        <p><strong>Step 2:</strong> Delete leads assigned to fake gabay accounts ({leads_from_fake} leads) + delete fake accounts</p>
        <form method="POST" action="?step=fake_users">
          <button type="submit" style="background:#7c3aed;color:white;border:none;
                  padding:10px 20px;border-radius:8px;font-size:14px;cursor:pointer;font-weight:700">
            Delete {leads_from_fake} fake-assigned leads + {len(fake_ids)} fake accounts
          </button>
        </form>
        <br>
        <a href="/dashboard" style="color:#4a5568;font-weight:700">← Back to Dashboard</a>
        </body></html>'''

    step = request.args.get('step', 'lazada')
    try:
        if step == 'lazada':
            sub = "(SELECT id FROM leads WHERE lazada_id IS NOT NULL)"
            db.session.execute(text(f"DELETE FROM notifications WHERE related_lead_id IN {sub}"))
            db.session.execute(text(f"DELETE FROM visits WHERE lead_id IN {sub}"))
            db.session.execute(text(f"DELETE FROM registrations WHERE lead_id IN {sub}"))
            db.session.execute(text(f"DELETE FROM lead_assignment_history WHERE lead_id IN {sub}"))
            db.session.execute(text("DELETE FROM leads WHERE lazada_id IS NOT NULL"))
            db.session.commit()
            msg = f"Deleted {count} leads with lazada_id."
        elif step == 'fake_users' and fake_ids:
            ids_str = ','.join(str(i) for i in fake_ids)
            sub = f"(SELECT id FROM leads WHERE gabay_id IN ({ids_str}))"
            db.session.execute(text(f"DELETE FROM notifications WHERE related_lead_id IN {sub}"))
            db.session.execute(text(f"DELETE FROM visits WHERE lead_id IN {sub}"))
            db.session.execute(text(f"DELETE FROM registrations WHERE lead_id IN {sub}"))
            db.session.execute(text(f"DELETE FROM lead_assignment_history WHERE lead_id IN {sub}"))
            db.session.execute(text(f"DELETE FROM leads WHERE gabay_id IN ({ids_str})"))
            # Delete fake user accounts
            db.session.execute(text(f"DELETE FROM users WHERE id IN ({ids_str})"))
            db.session.commit()
            msg = f"Deleted {leads_from_fake} leads and {len(fake_ids)} fake gabay accounts."
        else:
            msg = "Nothing to do."
    except Exception as e:
        db.session.rollback()
        return f'<h2>Error: {e}</h2><a href="/admin/delete-excel-imports">Back</a>'

    remaining = Lead.query.count()
    return f'''<html><body style="font-family:sans-serif;padding:32px;max-width:600px">
    <h2 style="color:#15803d">✅ Done!</h2>
    <p>{msg}</p>
    <p>Leads remaining: <strong style="font-size:20px;color:#1F3864">{remaining}</strong></p>
    <a href="/admin/delete-excel-imports" style="color:#1F3864;font-weight:700">→ Continue Cleanup</a>
    &nbsp;&nbsp;
    <a href="/dashboard" style="color:#1F3864;font-weight:700">→ Dashboard</a>
    </body></html>'''


@app.route('/admin/scout-activity')
@login_required
def admin_scout_activity():
    if not current_user.is_supervisor:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    page = request.args.get('page', 1, type=int)
    logs = (ScoutLog.query
            .order_by(ScoutLog.searched_at.desc())
            .paginate(page=page, per_page=50, error_out=False))
    return render_template('admin/scout_activity.html', logs=logs)


@app.route('/admin/users')
@login_required
def admin_users():
    if not current_user.is_superadmin:
        flash('Superadmin access required.', 'danger')
        return redirect(url_for('dashboard'))
    users = User.query.order_by(User.role, User.full_name).all()
    for u in users:
        u.lead_count = Lead.query.filter_by(gabay_id=u.id).count() if u.role == 'gabay' else 0
        u.visit_count = Visit.query.filter_by(gabay_id=u.id).count() if u.role == 'gabay' else 0
        if u.role == 'gabay':
            gv = (Visit.query
                  .filter(Visit.gabay_id == u.id, Visit.gps_address.isnot(None), Visit.gps_address != '')
                  .order_by(Visit.visited_at.desc())
                  .first())
            u.latest_gps = gv.gps_address if gv else None
        else:
            u.latest_gps = None
    now_utc = datetime.utcnow()
    online_count  = sum(1 for u in users if u.last_seen and (now_utc - u.last_seen).total_seconds() < 900)
    active_today  = sum(1 for u in users if u.last_seen and (now_utc - u.last_seen).total_seconds() < 86400)
    gabay_count   = sum(1 for u in users if u.role == 'gabay' and u.is_active)
    return render_template('admin/users.html', users=users, now_utc=now_utc,
                           online_count=online_count, active_today=active_today, gabay_count=gabay_count)


@app.route('/admin/users/new', methods=['GET', 'POST'])
@login_required
def admin_new_user():
    if not current_user.is_superadmin:
        flash('Superadmin access required.', 'danger')
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip()
        role = request.form.get('role', 'gabay')
        password = request.form.get('password', '')
        if User.query.filter_by(username=username).first():
            flash(f'Username "{username}" already exists.', 'danger')
        elif User.query.filter_by(email=email).first():
            flash(f'Email "{email}" already in use.', 'danger')
        else:
            u = User(username=username, full_name=full_name, email=email, role=role)
            u.set_password(password)
            if role == 'gabay':
                u.assigned_city = request.form.get('assigned_city', '').strip() or None
                u.can_scout = 'can_scout' in request.form
            db.session.add(u)
            db.session.commit()
            flash(f'User {full_name} ({role}) created.', 'success')
            return redirect(url_for('admin_users'))
    return render_template('admin/user_form.html', user=None)


@app.route('/admin/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_edit_user(user_id):
    if not current_user.is_superadmin:
        flash('Superadmin access required.', 'danger')
        return redirect(url_for('dashboard'))
    u = User.query.get_or_404(user_id)
    if request.method == 'POST':
        u.full_name = request.form.get('full_name', u.full_name).strip()
        u.email = request.form.get('email', u.email).strip()
        u.role = request.form.get('role', u.role)
        u.is_active = 'is_active' in request.form
        if u.role == 'gabay':
            u.assigned_city = request.form.get('assigned_city', '').strip() or None
            u.mobile = request.form.get('mobile', '').strip() or None
            u.can_scout = 'can_scout' in request.form
        else:
            u.assigned_city = None
            u.can_scout = False
        new_pw = request.form.get('password', '').strip()
        if new_pw:
            u.set_password(new_pw)
        db.session.commit()
        flash(f'User {u.full_name} updated.', 'success')
        return redirect(url_for('admin_users'))
    return render_template('admin/user_form.html', user=u)


@app.route('/admin/users/<int:user_id>/toggle', methods=['POST'])
@login_required
def admin_toggle_user(user_id):
    if not current_user.is_superadmin:
        return jsonify({'error': 'forbidden'}), 403
    u = User.query.get_or_404(user_id)
    if u.id == current_user.id:
        return jsonify({'error': 'Cannot deactivate yourself'}), 400
    u.is_active = not u.is_active
    db.session.commit()
    return jsonify({'active': u.is_active, 'name': u.full_name})


@app.route('/admin/users/<int:user_id>/toggle-wa-alerts', methods=['POST'])
@login_required
def admin_toggle_wa_alerts(user_id):
    if not current_user.is_superadmin:
        return jsonify({'error': 'forbidden'}), 403
    u = User.query.get_or_404(user_id)
    u.whatsapp_alerts_enabled = not u.whatsapp_alerts_enabled
    db.session.commit()
    return jsonify({'enabled': u.whatsapp_alerts_enabled, 'name': u.full_name})


# ─── LAZADA READ-ONLY PORTAL ──────────────────────────────────────────────────

@app.route('/lazada')
@login_required
def lazada_portal():
    if not current_user.is_lazada and not current_user.is_superadmin:
        flash('Access restricted to Lazada users.', 'danger')
        return redirect(url_for('dashboard'))
    total_leads = Lead.query.count()
    live = Lead.query.filter_by(status='live').count()
    matched = Lead.query.filter_by(status='matched').count()
    pipeline = {s: Lead.query.filter_by(status=s).count()
                for s in ['pool','assigned','attempting','negotiation','registration','live','matched','closed']}
    conversion = round((live + matched) / total_leads * 100, 1) if total_leads else 0
    total_visits = Visit.query.count()
    active_gabay = User.query.filter_by(role='gabay', is_active=True).count()
    regs_approved = Registration.query.filter_by(status='approved').count()
    # Top 5 cities by live sellers
    city_live = db.session.query(Lead.city, func.count(Lead.id).label('cnt'))\
        .filter(Lead.status.in_(['live','matched']))\
        .group_by(Lead.city).order_by(func.count(Lead.id).desc()).limit(8).all()
    # Category breakdown
    cat_data = db.session.query(Lead.category, func.count(Lead.id).label('cnt'))\
        .filter(Lead.status.in_(['live','matched','registration']))\
        .group_by(Lead.category).order_by(func.count(Lead.id).desc()).limit(8).all()
    # Monthly visits trend (last 6 months)
    from datetime import timedelta
    today = date.today()
    monthly = []
    for i in range(5, -1, -1):
        d = today.replace(day=1) - timedelta(days=30*i)
        vc = Visit.query.filter(
            extract('year', Visit.visited_at) == d.year,
            extract('month', Visit.visited_at) == d.month
        ).count()
        lc = Lead.query.filter(
            Lead.status.in_(['live','matched']),
            extract('year', Lead.assigned_at) == d.year,
            extract('month', Lead.assigned_at) == d.month
        ).count()
        monthly.append({'label': d.strftime('%b %Y'), 'visits': vc, 'live': lc})
    return render_template('lazada/portal.html',
        total_leads=total_leads, live=live, matched=matched, conversion=conversion,
        total_visits=total_visits, active_gabay=active_gabay, regs_approved=regs_approved,
        pipeline=pipeline, city_live=city_live, cat_data=cat_data, monthly=monthly)


# ─── NOTIFICATIONS ───────────────────────────────────────────────────────────

def generate_notifications(user):
    """Generate fresh notifications for a user — stalled leads, follow-ups, etc."""
    from datetime import timedelta
    today = date.today()
    cutoff_stalled = datetime.utcnow() - timedelta(days=7)

    if user.role == 'gabay':
        # 1. Stalled leads: assigned/attempting, no visit in 7+ days
        stalled = Lead.query.filter(
            Lead.gabay_id == user.id,
            Lead.status.in_(['assigned', 'attempting']),
            ~Lead.id.in_(
                db.session.query(Visit.lead_id).filter(Visit.visited_at >= cutoff_stalled)
            )
        ).all()
        for lead in stalled:
            exists = Notification.query.filter_by(
                user_id=user.id, type='stalled', related_lead_id=lead.id, is_read=False
            ).first()
            if not exists:
                db.session.add(Notification(
                    user_id=user.id, type='stalled',
                    title=f'Stalled: {lead.seller_name}',
                    message=f'No visit in 7+ days. Needs immediate follow-up.',
                    link=f'/gabay/app/lead/{lead.id}',
                    related_lead_id=lead.id
                ))

        # 2. Follow-ups due today
        followup_visits = Visit.query.filter(
            Visit.gabay_id == user.id,
            Visit.follow_up_date == today
        ).all()
        for v in followup_visits:
            exists = Notification.query.filter_by(
                user_id=user.id, type='followup_due', related_lead_id=v.lead_id, is_read=False
            ).first()
            if not exists:
                lead = Lead.query.get(v.lead_id)
                db.session.add(Notification(
                    user_id=user.id, type='followup_due',
                    title=f'Follow-up due: {lead.seller_name if lead else "Unknown"}',
                    message='Scheduled follow-up is today.',
                    link=f'/gabay/app/lead/{v.lead_id}',
                    related_lead_id=v.lead_id
                ))

    if user.is_manager:
        # 3. Registrations pending review
        pending_regs = Registration.query.filter_by(status='pending').all()
        for reg in pending_regs:
            exists = Notification.query.filter_by(
                user_id=user.id, type='reg_pending', related_lead_id=reg.lead_id, is_read=False
            ).first()
            if not exists:
                db.session.add(Notification(
                    user_id=user.id, type='reg_pending',
                    title=f'Registration pending review',
                    message=f'{reg.lead.seller_name if reg.lead else "Seller"} awaits approval.',
                    link=f'/registrations/{reg.id}',
                    related_lead_id=reg.lead_id
                ))

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


@app.route('/notifications')
@login_required
def notifications():
    generate_notifications(current_user)
    notifs = Notification.query.filter_by(user_id=current_user.id)\
        .order_by(Notification.created_at.desc()).limit(50).all()
    return render_template('notifications/index.html', notifs=notifs)


@app.route('/notifications/mark-read', methods=['POST'])
@login_required
def mark_notifications_read():
    notif_id = request.form.get('id')
    if notif_id == 'all':
        Notification.query.filter_by(user_id=current_user.id, is_read=False)\
            .update({'is_read': True})
    else:
        n = Notification.query.filter_by(id=notif_id, user_id=current_user.id).first()
        if n:
            n.is_read = True
    db.session.commit()
    return ('', 204)


@app.route('/api/notifications/unread')
@login_required
def api_unread_notifications():
    generate_notifications(current_user)
    notifs = Notification.query.filter_by(user_id=current_user.id, is_read=False)\
        .order_by(Notification.created_at.desc()).limit(10).all()
    return jsonify([{
        'id': n.id, 'type': n.type, 'title': n.title,
        'message': n.message, 'link': n.link,
        'icon': n.icon, 'color': n.color, 'age': n.age_label
    } for n in notifs])


# ─── SMART HOVER CARDS ────────────────────────────────────────────────────────
@app.route('/api/hover/gabay/<int:uid>')
@login_required
def hover_gabay(uid):
    from datetime import date as _date
    u = User.query.get_or_404(uid)
    today = _date.today()
    visits_month = Visit.query.filter(
        Visit.gabay_id == uid,
        extract('year',  Visit.visited_at) == today.year,
        extract('month', Visit.visited_at) == today.month
    ).count()
    visits_total = Visit.query.filter_by(gabay_id=uid).count()
    last_v = Visit.query.filter_by(gabay_id=uid).order_by(Visit.visited_at.desc()).first()
    last_visit = last_v.visited_at.strftime('%b %d, %Y') if last_v else None
    days_ago = (today - last_v.visited_at.date()).days if last_v else None

    leads_q = Lead.query.filter(Lead.gabay_id == uid, Lead.status != 'removed')
    assigned     = leads_q.count()
    live         = leads_q.filter_by(status='live').count()
    matched      = leads_q.filter_by(status='matched').count()
    negotiation  = leads_q.filter_by(status='negotiation').count()
    registration = leads_q.filter_by(status='registration').count()
    conv = round((live + matched) / assigned * 100, 1) if assigned else 0

    return jsonify({
        'id': u.id, 'name': u.full_name, 'role': u.role,
        'assigned': assigned, 'live': live, 'matched': matched,
        'negotiation': negotiation, 'registration': registration,
        'visits_month': visits_month, 'visits_total': visits_total,
        'last_visit': last_visit, 'days_ago': days_ago, 'conversion': conv,
    })


@app.route('/api/hover/lead/<int:lid>')
@login_required
def hover_lead(lid):
    from datetime import date as _date
    lead = Lead.query.get_or_404(lid)
    today = _date.today()
    last_v = Visit.query.filter_by(lead_id=lid).order_by(Visit.visited_at.desc()).first()
    last_visit = last_v.visited_at.strftime('%b %d, %Y') if last_v else None
    days_since = (today - last_v.visited_at.date()).days if last_v else None
    visits_total = Visit.query.filter_by(lead_id=lid).count()

    # health signal
    if days_since is None:
        health = 'danger'
    elif days_since <= 7:
        health = 'good'
    elif days_since <= 14:
        health = 'warning'
    else:
        health = 'danger'

    gabay_name = lead.assigned_gabay.full_name if lead.assigned_gabay else None
    gabay_id   = lead.gabay_id
    platform   = _mask_shopee(lead.project) if lead.project else None
    assigned_days = (today - lead.assigned_at.date()).days if lead.assigned_at else None

    return jsonify({
        'id': lead.id, 'seller_name': lead.seller_name,
        'status': lead.status, 'status_label': lead.status_label,
        'city': lead.city, 'platform': platform,
        'gabay': gabay_name, 'gabay_id': gabay_id,
        'visits': visits_total, 'last_visit': last_visit,
        'days_since': days_since, 'health': health,
        'assigned_days': assigned_days,
    })


@app.route('/api/hover/campaign/<int:cid>')
@login_required
def hover_campaign(cid):
    c = Campaign.query.get_or_404(cid)
    total  = Lead.query.filter_by(campaign_id=cid).filter(Lead.status != 'removed').count()
    asgnd  = Lead.query.filter_by(campaign_id=cid).filter(Lead.gabay_id.isnot(None), Lead.status != 'removed').count()
    live   = Lead.query.filter_by(campaign_id=cid, status='live').count()
    matched= Lead.query.filter_by(campaign_id=cid, status='matched').count()
    active_gabay = db.session.query(func.count(func.distinct(Lead.gabay_id))).filter(
        Lead.campaign_id == cid, Lead.gabay_id.isnot(None), Lead.status != 'removed'
    ).scalar() or 0
    pct_assigned = round(asgnd / total * 100, 1) if total else 0
    pct_live     = round(live  / total * 100, 1) if total else 0
    return jsonify({
        'name': c.name, 'status': c.status, 'priority': c.priority,
        'total': total, 'assigned': asgnd, 'live': live, 'matched': matched,
        'pct_assigned': pct_assigned, 'pct_live': pct_live,
        'active_gabay': active_gabay,
    })


@app.route('/api/hover/city')
@login_required
def hover_city():
    city = request.args.get('name', '').strip()
    cid  = request.args.get('campaign_id', type=int)
    if not city:
        return jsonify({}), 400
    sq = db.session.query(Lead.id).filter(Lead.city == city, Lead.status != 'removed')
    if cid:
        sq = sq.filter(Lead.campaign_id == cid)
    total    = db.session.query(func.count()).select_from(Lead).filter(Lead.city == city, Lead.status != 'removed')
    if cid:
        total = total.filter(Lead.campaign_id == cid)
    total = total.scalar() or 0
    visited  = db.session.query(func.count(func.distinct(Visit.lead_id))).filter(Visit.lead_id.in_(sq)).scalar() or 0
    live     = db.session.query(func.count()).select_from(Lead).filter(Lead.city == city, Lead.status == 'live')
    if cid:
        live = live.filter(Lead.campaign_id == cid)
    live = live.scalar() or 0
    coverage = round(visited / total * 100, 1) if total else 0
    return jsonify({
        'city': city, 'total': total, 'visited': visited,
        'live': live, 'coverage': coverage,
    })


# ─── MANAGER DAILY DIGEST ─────────────────────────────────────────────────────

@app.route('/digest')
@login_required
def daily_digest():
    if not current_user.is_manager:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    today = date.today()
    from datetime import timedelta
    # Today's activity
    visits_today = Visit.query.filter(func.date(Visit.visited_at) == today).all()
    new_live = Lead.query.filter(
        Lead.status == 'live',
        func.date(Lead.assigned_at) == today  # approximation
    ).count()
    regs_submitted = Registration.query.filter(func.date(Registration.submitted_at) == today).count()
    regs_approved = Registration.query.filter(func.date(Registration.activated_at) == today).count()
    regs_pending = Registration.query.filter_by(status='pending').count()
    # Gabay activity summary
    gabay_users = User.query.filter_by(role='gabay', is_active=True).all()
    gabay_summary = []
    for g in gabay_users:
        v_today = Visit.query.filter(Visit.gabay_id == g.id, func.date(Visit.visited_at) == today).count()
        active = Lead.query.filter(Lead.gabay_id == g.id, Lead.status.in_(['assigned','attempting','negotiation','registration'])).count()
        live = Lead.query.filter_by(gabay_id=g.id, status='live').count()
        gabay_summary.append({'gabay': g, 'visits_today': v_today, 'active': active, 'live': live})
    gabay_summary.sort(key=lambda x: -x['visits_today'])
    # No-activity Gabay
    inactive = [g for g in gabay_summary if g['visits_today'] == 0]
    # Stalled leads count
    cutoff = datetime.utcnow() - timedelta(days=7)
    stalled_count = Lead.query.filter(
        Lead.status.in_(['assigned', 'attempting']),
        ~Lead.id.in_(db.session.query(Visit.lead_id).filter(Visit.visited_at >= cutoff))
    ).count()
    # Pipeline snapshot
    pipeline = {s: Lead.query.filter_by(status=s).count()
                for s in ['pool','assigned','attempting','negotiation','registration','live','matched','closed']}
    return render_template('digest.html',
        today=today.strftime('%A, %B %d, %Y'),
        visits_today=visits_today, regs_submitted=regs_submitted,
        regs_approved=regs_approved, regs_pending=regs_pending,
        gabay_summary=gabay_summary, inactive=inactive,
        stalled_count=stalled_count, pipeline=pipeline)


# ─── GABAY PERFORMANCE SCORECARD ─────────────────────────────────────────────

@app.route('/gabay/<int:gabay_id>/scorecard')
@login_required
def gabay_scorecard(gabay_id):
    gabay = User.query.get_or_404(gabay_id)
    from datetime import timedelta
    today = date.today()
    months = []
    for i in range(5, -1, -1):
        d = today.replace(day=1) - timedelta(days=30*i)
        v = Visit.query.filter(
            Visit.gabay_id == gabay_id,
            extract('year', Visit.visited_at) == d.year,
            extract('month', Visit.visited_at) == d.month
        ).count()
        live = Lead.query.filter(
            Lead.gabay_id == gabay_id,
            Lead.status == 'live',
            extract('year', Lead.assigned_at) == d.year,
            extract('month', Lead.assigned_at) == d.month
        ).count()
        months.append({'label': d.strftime('%b %Y'), 'visits': v, 'live': live})

    total = Lead.query.filter_by(gabay_id=gabay_id).count()
    live_total = Lead.query.filter_by(gabay_id=gabay_id, status='live').count()
    conversion = round(live_total / total * 100, 1) if total else 0
    visits_total = Visit.query.filter_by(gabay_id=gabay_id).count()
    avg_days_to_live = None  # future: calculate from assignment_at to live status change

    pipeline = {s: Lead.query.filter_by(gabay_id=gabay_id, status=s).count()
                for s in ['assigned','attempting','negotiation','registration','live','closed']}

    recent_visits = Visit.query.filter_by(gabay_id=gabay_id)\
        .order_by(Visit.visited_at.desc()).limit(10).all()

    outcome_counts = {}
    for v in Visit.query.filter_by(gabay_id=gabay_id).all():
        outcome_counts[v.outcome] = outcome_counts.get(v.outcome, 0) + 1

    return render_template('gabay/scorecard.html',
        gabay=gabay, months=months, conversion=conversion,
        total=total, live_total=live_total, visits_total=visits_total,
        pipeline=pipeline, recent_visits=recent_visits, outcome_counts=outcome_counts)


# ─── CAMPAIGN / BATCH TRACKING ────────────────────────────────────────────────

@app.route('/campaigns')
@login_required
def campaigns():
    if not current_user.is_supervisor:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    batches = db.session.query(
        Lead.batch_ref,
        func.count(Lead.id).label('total'),
        func.min(Lead.imported_at).label('imported_at'),
        func.sum(func.cast(Lead.status == 'pool', db.Integer)).label('pool'),
        func.sum(func.cast(Lead.status == 'live', db.Integer)).label('live'),
        func.sum(func.cast(Lead.status == 'closed', db.Integer)).label('closed'),
    ).filter(Lead.batch_ref.isnot(None))\
     .group_by(Lead.batch_ref)\
     .order_by(func.min(Lead.imported_at).desc())\
     .all()
    campaign_data = []
    for b in batches:
        total = b.total or 1
        live = b.live or 0
        conversion = round(live / total * 100, 1)
        active = total - (b.pool or 0) - (b.closed or 0) - live
        campaign_data.append({
            'batch_ref': b.batch_ref,
            'total': b.total,
            'imported_at': b.imported_at,
            'pool': b.pool or 0,
            'active': max(active, 0),
            'live': live,
            'closed': b.closed or 0,
            'conversion': conversion
        })
    return render_template('campaigns/index.html', campaigns=campaign_data)


@app.route('/campaigns/<path:batch_ref>')
@login_required
def campaign_detail(batch_ref):
    leads = Lead.query.filter_by(batch_ref=batch_ref)\
        .order_by(Lead.status, Lead.seller_name).all()
    return render_template('campaigns/detail.html', batch_ref=batch_ref, leads=leads)


# ─── CAMPAIGN MANAGEMENT (Priority System) ────────────────────────────────────

@app.route('/campaigns/manage')
@login_required
def campaign_manage():
    if not current_user.is_manager:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    campaigns = Campaign.query.order_by(Campaign.priority, Campaign.name).all()
    for c in campaigns:
        c._metrics = c.metrics()
    unassigned_count = Lead.query.filter(
        Lead.campaign_id.is_(None), Lead.status != 'removed'
    ).count()
    return render_template('campaigns/manage.html', campaigns=campaigns, unassigned_count=unassigned_count)


@app.route('/campaigns/<int:campaign_id>/status-breakdown')
@login_required
def campaign_status_breakdown(campaign_id):
    if not current_user.is_manager:
        return jsonify({'error': 'Access denied'}), 403
    campaign = Campaign.query.get_or_404(campaign_id)
    statuses = ['pool', 'assigned', 'attempting', 'negotiation', 'registration', 'live', 'matched', 'closed', 'removed']
    breakdown = {}
    for s in statuses:
        breakdown[s] = Lead.query.filter_by(campaign_id=campaign_id, status=s).count()
    with_gabay = Lead.query.filter(
        Lead.campaign_id == campaign_id,
        Lead.gabay_id.isnot(None),
        Lead.status != 'removed'
    ).count()
    no_gabay = Lead.query.filter(
        Lead.campaign_id == campaign_id,
        Lead.gabay_id.is_(None),
        Lead.status != 'removed'
    ).count()
    # Per-gabay count
    from sqlalchemy import func
    gabay_counts = db.session.query(
        User.full_name, func.count(Lead.id)
    ).join(Lead, Lead.gabay_id == User.id)\
     .filter(Lead.campaign_id == campaign_id, Lead.status != 'removed')\
     .group_by(User.full_name).order_by(func.count(Lead.id).desc()).all()

    return jsonify({
        'campaign': campaign.name,
        'total': sum(v for k,v in breakdown.items() if k != 'removed'),
        'status_breakdown': breakdown,
        'with_gabay': with_gabay,
        'no_gabay_pool': no_gabay,
        'per_gabay': [{'gabay': g, 'count': c} for g, c in gabay_counts]
    })


@app.route('/campaigns/set-migration-priority', methods=['POST'])
@login_required
def campaign_set_migration_priority():
    if not current_user.is_manager:
        return jsonify({'error': 'Access denied'}), 403
    data = request.get_json()
    wave2 = Campaign.query.get_or_404(data.get('wave2_id'))
    legacy = Campaign.query.get_or_404(data.get('legacy_id'))
    wave2.priority = 1
    wave2.status = 'active'
    legacy.priority = 99
    legacy.status = 'archived'
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/campaigns/manage/rename', methods=['POST'])
@login_required
def campaign_rename():
    if not current_user.is_manager:
        return jsonify({'error': 'Access denied'}), 403
    data = request.get_json()
    campaign = Campaign.query.get_or_404(data.get('campaign_id'))
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Name cannot be empty'}), 400
    campaign.name = name
    db.session.commit()
    return jsonify({'ok': True, 'name': name})


@app.route('/campaigns/manage/bulk-assign', methods=['POST'])
@login_required
def campaign_bulk_assign():
    """Assign all campaign-less leads to a selected campaign."""
    if not current_user.is_manager:
        return jsonify({'error': 'Access denied'}), 403
    campaign_id = request.json.get('campaign_id')
    if not campaign_id:
        return jsonify({'error': 'No campaign selected'}), 400
    campaign = Campaign.query.get_or_404(campaign_id)
    updated = Lead.query.filter(
        Lead.campaign_id.is_(None), Lead.status != 'removed'
    ).update({'campaign_id': campaign_id}, synchronize_session=False)
    db.session.commit()
    return jsonify({'updated': updated, 'campaign': campaign.name})


@app.route('/campaigns/overlap-report')
@login_required
def campaign_overlap_report():
    """Compare two campaigns — find leads that exist in both (by phone or lazada_id)."""
    if not current_user.is_manager:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    campaigns = Campaign.query.order_by(Campaign.priority, Campaign.name).all()
    camp_a_id = request.args.get('camp_a', type=int)
    camp_b_id = request.args.get('camp_b', type=int)
    results = None

    if camp_a_id and camp_b_id and camp_a_id != camp_b_id:
        leads_a = Lead.query.filter_by(campaign_id=camp_a_id).filter(Lead.status != 'removed').all()
        leads_b = Lead.query.filter_by(campaign_id=camp_b_id).filter(Lead.status != 'removed').all()

        phones_b = {l.contact_number: l for l in leads_b if l.contact_number}
        ids_b    = {l.lazada_id: l for l in leads_b if l.lazada_id}

        overlap = []
        for la in leads_a:
            match = None
            if la.contact_number and la.contact_number in phones_b:
                match = phones_b[la.contact_number]
            elif la.lazada_id and la.lazada_id in ids_b:
                match = ids_b[la.lazada_id]
            if match:
                visit_count = match.visits.count()
                overlap.append({
                    'seller': la.seller_name,
                    'phone': la.contact_number or '—',
                    'status_a': la.status,
                    'status_b': match.status,
                    'visit_count': visit_count,
                    'visited': visit_count > 0,
                    'lead_id_a': la.id,      # Wave 2 lead ID
                    'lead_id_b': match.id,   # Legacy lead ID
                    'gabay': match.assigned_gabay.full_name if match.assigned_gabay else '—'
                })

        visited   = [o for o in overlap if o['visited']]
        unvisited = [o for o in overlap if not o['visited']]
        results = {
            'total_a': len(leads_a),
            'total_b': len(leads_b),
            'overlap': len(overlap),
            'visited': len(visited),
            'unvisited': len(unvisited),
            'rows': overlap
        }

    # Sync: copy gabay + status from camp_b (Legacy) → camp_a (Wave 2) using stored lead IDs
    if request.args.get('sync') == '1' and results and camp_a_id and camp_b_id:
        synced = 0
        for r in results['rows']:
            dest_lead = Lead.query.get(r['lead_id_a'])  # Wave 2 lead (direct by ID)
            src_lead  = Lead.query.get(r['lead_id_b'])  # Legacy lead (direct by ID)
            if dest_lead and src_lead:
                if src_lead.gabay_id:
                    dest_lead.gabay_id    = src_lead.gabay_id
                    dest_lead.assigned_at = src_lead.assigned_at
                if src_lead.status not in ('pool', 'removed'):
                    dest_lead.status = src_lead.status
                synced += 1
        db.session.commit()
        return jsonify({'synced': synced})

    # CSV download
    if request.args.get('download') == '1' and results:
        import csv, io
        camp_a = Campaign.query.get(camp_a_id)
        camp_b = Campaign.query.get(camp_b_id)
        si = io.StringIO()
        w = csv.writer(si)
        w.writerow(['Seller', 'Phone', f'Status in {camp_b.name}', 'Assigned Gabay', 'Visit Count', 'Visited?'])
        for r in sorted(results['rows'], key=lambda x: x['visit_count'], reverse=True):
            w.writerow([r['seller'], r['phone'], r['status_b'], r['gabay'],
                        r['visit_count'], 'Yes' if r['visited'] else 'No'])
        output = si.getvalue().encode('utf-8-sig')
        filename = f"overlap_{camp_a.name}_vs_{camp_b.name}.csv".replace(' ', '_')
        from flask import Response
        return Response(output, mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename="{filename}"'})

    return render_template('campaigns/overlap_report.html',
        campaigns=campaigns, results=results,
        camp_a_id=camp_a_id, camp_b_id=camp_b_id)


@app.route('/campaigns/manage/set-priority', methods=['POST'])
@login_required
def campaign_set_priority():
    if not current_user.is_manager:
        return jsonify({'error': 'Access denied'}), 403
    data = request.get_json()
    campaign_id = data.get('campaign_id')
    new_priority = data.get('priority')
    reason = data.get('reason', '').strip() or None
    campaign = Campaign.query.get_or_404(campaign_id)
    prev = campaign.priority
    campaign.priority = int(new_priority)
    log = CampaignPriorityLog(
        campaign_id=campaign.id,
        changed_by=current_user.id,
        prev_priority=prev,
        new_priority=int(new_priority),
        reason=reason
    )
    db.session.add(log)
    db.session.commit()
    return jsonify({'ok': True, 'name': campaign.name, 'priority': campaign.priority})


@app.route('/campaigns/manage/remove-leads/<int:campaign_id>/preview', methods=['GET'])
@login_required
def campaign_remove_leads_preview(campaign_id):
    """Return a breakdown of what would be removed — used by the modal before confirmation."""
    if not current_user.is_supervisor:
        return jsonify({'error': 'Access denied'}), 403
    campaign = Campaign.query.get_or_404(campaign_id)
    visited_ids = {v.lead_id for v in Visit.query.with_entities(Visit.lead_id).all()}

    pool_leads = Lead.query.filter(
        Lead.campaign_id == campaign_id,
        Lead.status == 'pool',
        ~Lead.id.in_(db.session.query(Visit.lead_id))
    ).all()

    assigned_leads = Lead.query.filter(
        Lead.campaign_id == campaign_id,
        Lead.status == 'assigned',
        ~Lead.id.in_(db.session.query(Visit.lead_id))
    ).all()

    # Group assigned leads by agent
    agent_breakdown = {}
    for lead in assigned_leads:
        if lead.gabay_id:
            agent = User.query.get(lead.gabay_id)
            name = agent.full_name if agent else 'Unknown'
            agent_breakdown[name] = agent_breakdown.get(name, 0) + 1

    # Leads that have visits — will be kept
    visited_count = Lead.query.filter(
        Lead.campaign_id == campaign_id,
        Lead.id.in_(db.session.query(Visit.lead_id))
    ).count()

    return jsonify({
        'campaign': campaign.name,
        'pool': len(pool_leads),
        'assigned': len(assigned_leads),
        'agent_breakdown': [{'name': k, 'count': v} for k, v in agent_breakdown.items()],
        'visited_kept': visited_count,
        'total_removable': len(pool_leads) + len(assigned_leads),
    })


@app.route('/campaigns/manage/remove-leads/<int:campaign_id>', methods=['POST'])
@login_required
def campaign_remove_leads(campaign_id):
    """Soft-remove unvisited leads from a campaign. Leads with visits are always kept."""
    if not current_user.is_supervisor:
        return jsonify({'error': 'Access denied'}), 403
    campaign = Campaign.query.get_or_404(campaign_id)
    removable = Lead.query.filter(
        Lead.campaign_id == campaign_id,
        Lead.status.in_(['pool', 'assigned']),
        ~Lead.id.in_(db.session.query(Visit.lead_id))
    ).all()
    count = len(removable)
    for lead in removable:
        lead.status = 'removed'
        lead.gabay_id = None
    db.session.commit()
    return jsonify({'ok': True, 'removed': count, 'campaign': campaign.name})


@app.route('/campaigns/manage/archive/<int:campaign_id>', methods=['POST'])
@login_required
def campaign_archive(campaign_id):
    if not current_user.is_manager:
        return jsonify({'error': 'Access denied'}), 403
    campaign = Campaign.query.get_or_404(campaign_id)
    campaign.status = 'archived' if campaign.status == 'active' else 'active'
    db.session.commit()
    return jsonify({'ok': True, 'status': campaign.status})


@app.route('/campaigns/dashboard')
@login_required
def campaign_dashboard():
    if not current_user.is_manager:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    campaigns = Campaign.query.order_by(Campaign.priority, Campaign.name).all()
    campaign_data = []
    for c in campaigns:
        m = c.metrics()
        gabay_stats = db.session.query(
            User.full_name,
            func.count(Lead.id).label('assigned'),
            func.sum(func.cast(Lead.status.in_(['live', 'matched']), db.Integer)).label('completed'),
            func.sum(func.cast(Lead.status == 'pool', db.Integer)).label('unvisited'),
        ).join(Lead, Lead.gabay_id == User.id)\
         .filter(Lead.campaign_id == c.id, User.role == 'gabay')\
         .group_by(User.id, User.full_name)\
         .order_by(func.count(Lead.id).desc())\
         .all()
        # Phase 2: aggregate AI intel for this campaign
        intel_done = db.session.query(func.count(LeadIntelligence.id))\
            .join(Lead, Lead.id == LeadIntelligence.lead_id)\
            .filter(Lead.campaign_id == c.id, LeadIntelligence.scan_status == 'done').scalar() or 0
        intel_pending = db.session.query(func.count(LeadIntelligence.id))\
            .join(Lead, Lead.id == LeadIntelligence.lead_id)\
            .filter(Lead.campaign_id == c.id, LeadIntelligence.scan_status.in_(['pending', 'running'])).scalar() or 0
        avg_score = db.session.query(func.avg(LeadIntelligence.ai_score))\
            .join(Lead, Lead.id == LeadIntelligence.lead_id)\
            .filter(Lead.campaign_id == c.id, LeadIntelligence.scan_status == 'done').scalar()
        high_potential = db.session.query(func.count(LeadIntelligence.id))\
            .join(Lead, Lead.id == LeadIntelligence.lead_id)\
            .filter(Lead.campaign_id == c.id, LeadIntelligence.ai_score >= 70).scalar() or 0
        already_lazada = db.session.query(func.count(LeadIntelligence.id))\
            .join(Lead, Lead.id == LeadIntelligence.lead_id)\
            .filter(Lead.campaign_id == c.id, LeadIntelligence.is_on_lazada == True).scalar() or 0
        campaign_data.append({
            'campaign': c, 'metrics': m, 'gabay_stats': gabay_stats,
            'intel': {
                'done': intel_done,
                'pending': intel_pending,
                'total': m.get('total', 0) if isinstance(m, dict) else 0,
                'avg_score': round(float(avg_score), 1) if avg_score else None,
                'high_potential': high_potential,
                'already_lazada': already_lazada,
            }
        })
    return render_template('campaigns/dashboard.html', campaign_data=campaign_data)


@app.route('/campaigns/audit-log')
@login_required
def campaign_audit_log():
    if not current_user.is_manager:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    logs = CampaignPriorityLog.query\
        .order_by(CampaignPriorityLog.changed_at.desc())\
        .limit(200).all()
    return render_template('campaigns/audit_log.html', logs=logs)


# ─── GABAY MOBILE APP ────────────────────────────────────────────────────────

def _gabay_stats(gabay_id):
    today = date.today()
    total = Lead.query.filter_by(gabay_id=gabay_id).count()
    assigned = Lead.query.filter_by(gabay_id=gabay_id, status='assigned').count()
    attempting = Lead.query.filter_by(gabay_id=gabay_id, status='attempting').count()
    negotiation = Lead.query.filter_by(gabay_id=gabay_id, status='negotiation').count()
    registration = Lead.query.filter_by(gabay_id=gabay_id, status='registration').count()
    live = Lead.query.filter_by(gabay_id=gabay_id, status='live').count()
    visited_today = Visit.query.filter(
        Visit.gabay_id == gabay_id,
        func.date(Visit.visited_at) == today
    ).count()
    visits_this_month = Visit.query.filter(
        Visit.gabay_id == gabay_id,
        extract('year', Visit.visited_at) == today.year,
        extract('month', Visit.visited_at) == today.month
    ).count()
    live_total = Lead.query.filter_by(gabay_id=gabay_id, status='live').count()
    total_assigned_ever = Lead.query.filter(Lead.gabay_id == gabay_id).count()
    conversion_rate = round(live_total / total_assigned_ever * 100) if total_assigned_ever else 0
    return dict(total=total, assigned=assigned, attempting=attempting, negotiation=negotiation,
                registration=registration, live=live, visited_today=visited_today,
                visits_this_month=visits_this_month, conversion_rate=conversion_rate)


def _priority1_campaign():
    """Return the active campaign with the lowest priority number (P1 = most important)."""
    return (Campaign.query
            .filter_by(status='active')
            .order_by(Campaign.priority.asc())
            .first())


@app.route('/gabay/app')
@login_required
def gabay_home():
    if current_user.role not in ('gabay', 'admin', 'manager', 'supervisor'):
        return redirect(url_for('dashboard'))
    gid = current_user.id
    p1 = _priority1_campaign()
    p1_id = p1.id if p1 else None
    stats = _gabay_stats(gid)
    hour = datetime.now().hour
    greeting = 'Good morning' if hour < 12 else ('Good afternoon' if hour < 18 else 'Good evening')
    today_str = datetime.now().strftime('%A, %B %d, %Y')
    followup_q = Lead.query.filter(
        Lead.gabay_id == gid,
        Lead.status.in_(['assigned', 'attempting', 'negotiation'])
    )
    if p1_id:
        followup_q = followup_q.filter(Lead.campaign_id == p1_id)
    followups = followup_q.join(Visit, Lead.id == Visit.lead_id).filter(
        func.date(Visit.follow_up_date) == date.today()
    ).limit(5).all()
    priority_leads_q = (Lead.query
        .outerjoin(Campaign, Lead.campaign_id == Campaign.id)
        .filter(
            Lead.gabay_id == gid,
            Lead.status.in_(['negotiation', 'attempting', 'assigned'])
        ))
    if p1_id:
        priority_leads_q = priority_leads_q.filter(Lead.campaign_id == p1_id)
    priority_leads = priority_leads_q.order_by(
            Campaign.priority.asc().nullslast(),
            Lead.ai_score.desc().nullslast(),
            Lead.assigned_at.asc()
        ).limit(8).all()
    stalled_cutoff = datetime.utcnow().replace(hour=0, minute=0, second=0) - \
        __import__('datetime').timedelta(days=7)
    stalled_q = Lead.query.filter(
        Lead.gabay_id == gid,
        Lead.status.in_(['assigned', 'attempting']),
        ~Lead.id.in_(
            db.session.query(Visit.lead_id).filter(Visit.visited_at >= stalled_cutoff)
        )
    )
    if p1_id:
        stalled_q = stalled_q.filter(Lead.campaign_id == p1_id)
    stalled_count = stalled_q.count()

    # Smart suggestions: group active leads by city, rank by never-visited then stalled
    from collections import defaultdict
    active_leads_q = Lead.query.filter(
        Lead.gabay_id == gid,
        Lead.status.in_(['assigned', 'attempting', 'negotiation'])
    )
    if p1_id:
        active_leads_q = active_leads_q.filter(Lead.campaign_id == p1_id)
    active_leads = active_leads_q.all()
    # Mark each lead with last_visit info
    visited_lead_ids = {v.lead_id for v in Visit.query.filter_by(gabay_id=gid).all()}
    city_groups = defaultdict(list)
    for lead in active_leads:
        score = 0 if lead.id not in visited_lead_ids else 1
        city_groups[lead.city or 'Unknown'].append((score, lead))
    # Pick city with most unvisited leads
    def city_priority(item):
        city, items = item
        unvisited = sum(1 for s, _ in items if s == 0)
        return -unvisited
    sorted_cities = sorted(city_groups.items(), key=city_priority)
    suggested_leads = []
    for city, items in sorted_cities[:2]:
        items_sorted = sorted(items, key=lambda x: x[0])
        for _, lead in items_sorted[:3]:
            last_v = Visit.query.filter_by(lead_id=lead.id).order_by(Visit.visited_at.desc()).first()
            lead.last_visit_date = last_v.visited_at.strftime('%b %d') if last_v else None
            lead.never_visited = lead.id not in visited_lead_ids
            suggested_leads.append(lead)
        if len(suggested_leads) >= 4:
            break

    # Traffic hint based on time
    traffic_msg = None
    traffic_level = None
    if 7 <= hour <= 9:
        traffic_msg = 'Morning rush hour (7–9 AM). Heavy traffic expected. Visit sellers close to you first.'
        traffic_level = 'danger'
    elif 11 <= hour <= 13:
        traffic_msg = 'Lunch time. Sellers may be on break. Good time for phone follow-ups.'
        traffic_level = 'warning'
    elif 17 <= hour <= 19:
        traffic_msg = 'Evening rush (5–7 PM). Heavy traffic. Wrap up nearby visits and head home safely.'
        traffic_level = 'danger'
    elif 9 <= hour <= 11 or 14 <= hour <= 17:
        traffic_msg = 'Good time to travel. Light traffic expected — great for visiting farther sellers!'
        traffic_level = 'success'

    pending_photos = Visit.query.filter_by(gabay_id=gid, photo_pending=True).order_by(Visit.visited_at.desc()).all()

    # Gamification badges
    from datetime import timedelta
    badges = []
    # 🥇 Conversion Champion — has any live sellers
    live_count = Lead.query.filter_by(gabay_id=gid, status='live').count()
    if live_count >= 1:
        badges.append({'icon': '🥇', 'label': 'Conversion Champion', 'desc': f'{live_count} seller{"s" if live_count>1 else ""} live', 'color': '#d97706'})
    # 🔥 7-Day Streak — visited at least one seller every day for 7 consecutive days
    streak_days = 0
    for d in range(7):
        day_start = (datetime.utcnow() - timedelta(days=d)).replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        if Visit.query.filter(Visit.gabay_id == gid, Visit.visited_at >= day_start, Visit.visited_at < day_end).first():
            streak_days += 1
        else:
            break
    if streak_days >= 7:
        badges.append({'icon': '🔥', 'label': '7-Day Streak', 'desc': '7 days in a row!', 'color': '#dc2626'})
    # ⭐ Perfect Visit — has a visit logged today
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    visits_today_count = Visit.query.filter(Visit.gabay_id == gid, Visit.visited_at >= today_start).count()
    if visits_today_count >= 3:
        badges.append({'icon': '⭐', 'label': 'Perfect Visit Day', 'desc': f'{visits_today_count} visits today', 'color': '#7c3aed'})
    # 🚀 Fast Activator — has a live lead assigned within the last 14 days
    fast_cutoff = datetime.utcnow() - timedelta(days=14)
    fast_live = Lead.query.filter(
        Lead.gabay_id == gid, Lead.status == 'live',
        Lead.assigned_at >= fast_cutoff
    ).first()
    if fast_live:
        badges.append({'icon': '🚀', 'label': 'Fast Activator', 'desc': 'Activated in ≤14 days', 'color': '#0891b2'})

    return render_template('gabay_app/home.html',
        stats=stats, greeting=greeting, today=today_str,
        followups=followups, priority_leads=priority_leads, stalled_count=stalled_count,
        suggested_leads=suggested_leads, traffic_msg=traffic_msg, traffic_level=traffic_level,
        pending_photos=pending_photos, badges=badges)


@app.route('/gabay/app/leads')
@login_required
def gabay_app_leads():
    gid = current_user.id
    p1 = _priority1_campaign()
    p1_id = p1.id if p1 else None
    active_status = request.args.get('status', 'all')
    q = request.args.get('q', '')

    def _c(status=None):
        qry = Lead.query.filter_by(gabay_id=gid)
        if p1_id:
            qry = qry.filter(Lead.campaign_id == p1_id)
        if status:
            qry = qry.filter_by(status=status)
        return qry.count()

    status_tabs = [
        ('All', 'all', _c()),
        ('Assigned', 'assigned', _c('assigned')),
        ('Attempting', 'attempting', _c('attempting')),
        ('Negotiation', 'negotiation', _c('negotiation')),
        ('Registration', 'registration', _c('registration')),
        ('Live', 'live', _c('live')),
    ]
    query = Lead.query.filter_by(gabay_id=gid)
    if p1_id:
        query = query.filter(Lead.campaign_id == p1_id)
    if active_status != 'all':
        query = query.filter_by(status=active_status)
    leads = query.order_by(Lead.assigned_at.desc()).all()
    for lead in leads:
        last = Visit.query.filter_by(lead_id=lead.id).order_by(Visit.visited_at.desc()).first()
        lead.last_visit_date = last.visited_at.strftime('%b %d') if last else None
    return render_template('gabay_app/leads.html',
        leads=leads, total=_c(),
        status_tabs=status_tabs, active_status=active_status)


@app.route('/gabay/app/lead/<int:lead_id>')
@login_required
def gabay_lead_detail(lead_id):
    lead = Lead.query.get_or_404(lead_id)
    visits = Visit.query.filter_by(lead_id=lead_id).order_by(Visit.visited_at.desc()).all()
    return render_template('gabay_app/lead_detail.html', lead=lead, visits=visits)


@app.route('/gabay/app/checkin', methods=['GET', 'POST'])
@login_required
def gabay_quick_checkin():
    gid = current_user.id
    my_leads = Lead.query.filter(
        Lead.gabay_id == gid,
        Lead.status.in_(['assigned', 'attempting', 'negotiation', 'registration'])
    ).order_by(Lead.seller_name).all()
    selected_lead = None
    preselect = request.args.get('lead_id')
    if preselect:
        selected_lead = Lead.query.get(preselect)
    if request.method == 'POST':
        lead_id = request.form.get('lead_id')
        if not lead_id:
            flash('Please select a seller before checking in.', 'danger')
            return redirect(url_for('gabay_quick_checkin'))
        outcome = request.form.get('outcome')
        notes = request.form.get('notes', '')
        gps_lat = request.form.get('gps_lat')
        gps_lng = request.form.get('gps_lng')
        gps_address = request.form.get('gps_address', '')
        follow_up_str = request.form.get('follow_up_date', '')
        new_status = request.form.get('new_status', '')
        follow_up_date = None
        if follow_up_str:
            try:
                follow_up_date = datetime.strptime(follow_up_str, '%Y-%m-%d').date()
            except ValueError:
                pass
        # Handle photo uploads
        import uuid
        photo_filenames = []
        visit_upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'visits')
        os.makedirs(visit_upload_dir, exist_ok=True)
        for field_name in ('photo_selfie', 'photo_proof'):
            f = request.files.get(field_name)
            if f and f.filename:
                ext = os.path.splitext(secure_filename(f.filename))[1].lower() or '.jpg'
                fname = f'{gid}_{lead_id}_{field_name}_{uuid.uuid4().hex[:8]}{ext}'
                f.save(os.path.join(visit_upload_dir, fname))
                photo_filenames.append(fname)

        visit = Visit(
            lead_id=lead_id, gabay_id=gid, visited_at=datetime.utcnow(),
            gps_lat=float(gps_lat) if gps_lat else None,
            gps_lng=float(gps_lng) if gps_lng else None,
            gps_address=gps_address, outcome=outcome, notes=notes,
            follow_up_date=follow_up_date,
            photos=json.dumps(photo_filenames) if photo_filenames else None,
            photo_pending=(len(photo_filenames) == 0)
        )
        db.session.add(visit)
        lead = Lead.query.get(lead_id)
        if lead:
            if new_status:
                lead.status = new_status
            # ── Competitor visit alert ────────────────────────────────────
            if lead.project:
                supervisors = User.query.filter(
                    User.role.in_(['supervisor', 'admin', 'manager', 'superadmin']),
                    User.is_active == True
                ).all()
                gabay_name = current_user.display_name
                for sup in supervisors:
                    notif = Notification(
                        user_id=sup.id,
                        type='competitor_visit',
                        title=f'🏴 Competitor Lead Visited — {lead.project}',
                        message=(
                            f'{gabay_name} visited {lead.seller_name} '
                            f'(currently on {lead.project}). '
                            f'Outcome: {outcome or "—"}. '
                            f'These sellers know the process — fast-track if interested!'
                        ),
                        link=f'/leads/{lead.id}',
                        related_lead_id=lead.id,
                    )
                    db.session.add(notif)
        db.session.commit()

        # Notify managers via WhatsApp on every Gabay visit
        if lead:
            outcome_emoji = {
                'interested':'🟢','not_interested':'🔴','callback':'🔵',
                'follow_up':'🟡','not_home':'⚪','rejected':'🔴','registered':'✅',
            }.get(outcome,'📋')
            status_line = f"\n📊 Lead status → *{lead.status_label}*" if new_status else ''
            _visit_msg = (
                f"{outcome_emoji} *Visit Logged*\n"
                f"👤 Agent: {current_user.full_name}\n"
                f"🏪 Seller: {lead.seller_name}\n"
                f"📋 Outcome: {(outcome or '').replace('_',' ').title()}"
                f"{status_line}\n"
                f"📍 {gps_address[:60] if gps_address else 'No GPS'}"
            )
            _notify_managers_whatsapp(_visit_msg)
            _notify_managers_telegram(_visit_msg)

        if visit.photo_pending:
            flash('Visit logged! 📷 Don\'t forget to upload your selfie proof photo when you\'re back online.', 'warning')
        else:
            flash('Visit logged successfully!', 'success')
        return redirect(url_for('gabay_home'))
    return render_template('gabay_app/checkin.html', my_leads=my_leads, selected_lead=selected_lead)


@app.route('/api/gabay/sync', methods=['POST'])
@login_required
def gabay_offline_sync():
    """Accept offline-queued visits from the Service Worker background sync."""
    gid = current_user.id
    lead_id = request.form.get('lead_id')
    if not lead_id:
        return jsonify({'ok': False, 'error': 'missing lead_id'}), 400

    outcome      = request.form.get('outcome')
    notes        = request.form.get('notes', '')
    gps_lat      = request.form.get('gps_lat')
    gps_lng      = request.form.get('gps_lng')
    gps_address  = request.form.get('gps_address', '')
    follow_up_str= request.form.get('follow_up_date', '')
    new_status   = request.form.get('new_status', '')
    offline_ts   = request.form.get('offline_visited_at', '')

    # Parse the timestamp the Gabay agent recorded offline (ISO 8601)
    visited_at = datetime.utcnow()
    if offline_ts:
        try:
            # Strip fractional seconds and timezone, parse as naive, convert from PHT (+8) to UTC
            ts_clean = offline_ts[:19]  # "2026-06-23T14:30:00"
            dt_local = datetime.strptime(ts_clean, '%Y-%m-%dT%H:%M:%S')
            visited_at = dt_local - timedelta(hours=8)
        except Exception:
            pass

    follow_up_date = None
    if follow_up_str:
        try:
            follow_up_date = datetime.strptime(follow_up_str, '%Y-%m-%d').date()
        except ValueError:
            pass

    import uuid as _uuid
    photo_filenames = []
    visit_upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'visits')
    os.makedirs(visit_upload_dir, exist_ok=True)
    for field_name in ('photo_selfie', 'photo_proof'):
        f = request.files.get(field_name)
        if f and f.filename:
            ext = os.path.splitext(secure_filename(f.filename))[1].lower() or '.jpg'
            fname = f'{gid}_{lead_id}_{field_name}_{_uuid.uuid4().hex[:8]}{ext}'
            f.save(os.path.join(visit_upload_dir, fname))
            photo_filenames.append(fname)

    try:
        visit = Visit(
            lead_id=lead_id, gabay_id=gid,
            visited_at=visited_at,
            gps_lat=float(gps_lat) if gps_lat else None,
            gps_lng=float(gps_lng) if gps_lng else None,
            gps_address=gps_address, outcome=outcome, notes=notes,
            follow_up_date=follow_up_date,
            photos=json.dumps(photo_filenames) if photo_filenames else None,
            photo_pending=(len(photo_filenames) == 0)
        )
        db.session.add(visit)
        lead = Lead.query.get(lead_id)
        if lead and new_status:
            lead.status = new_status
        db.session.commit()
        return jsonify({'ok': True, 'visit_id': visit.id})
    except Exception as ex:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(ex)}), 500


@app.route('/gabay/app/visit/<int:visit_id>/upload-photo', methods=['GET', 'POST'])
@login_required
def gabay_upload_photo(visit_id):
    visit = Visit.query.get_or_404(visit_id)
    if visit.gabay_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('gabay_home'))
    lead = Lead.query.get(visit.lead_id)

    if request.method == 'POST':
        import uuid
        visit_upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'visits')
        os.makedirs(visit_upload_dir, exist_ok=True)
        existing = json.loads(visit.photos) if visit.photos else []
        added = 0
        for field_name in ('photo_selfie', 'photo_proof'):
            f = request.files.get(field_name)
            if f and f.filename:
                ext = os.path.splitext(secure_filename(f.filename))[1].lower() or '.jpg'
                fname = f'{current_user.id}_{visit.lead_id}_{field_name}_{uuid.uuid4().hex[:8]}{ext}'
                f.save(os.path.join(visit_upload_dir, fname))
                existing.append(fname)
                added += 1
        if added:
            visit.photos = json.dumps(existing)
            visit.photo_pending = False
            db.session.commit()
            flash(f'✅ {added} photo(s) uploaded — visit proof complete!', 'success')
        else:
            flash('No photos received. Please select at least one photo.', 'warning')
        return redirect(url_for('gabay_upload_photo', visit_id=visit_id))

    return render_template('gabay_app/upload_photo.html', visit=visit, lead=lead)


@app.route('/gabay/app/tutorial')
@login_required
def gabay_tutorial():
    if current_user.role not in ('gabay', 'superadmin', 'admin', 'manager', 'supervisor'):
        return redirect(url_for('dashboard'))
    return render_template('gabay_app/tutorial.html')


@app.route('/admin/tutorial')
@login_required
def supervisor_tutorial():
    if not current_user.is_supervisor:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    return render_template('tutorial_supervisor.html')


@app.route('/admin/tutorial/print')
@login_required
def supervisor_tutorial_print():
    if not current_user.is_supervisor:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    return render_template('tutorial_supervisor_print.html')


@app.route('/gabay/offline')
def gabay_offline():
    """Offline fallback page — served by SW when network is unavailable."""
    return render_template('gabay_app/offline.html')


@app.route('/gabay/app/tutorial/print')
@login_required
def gabay_tutorial_print():
    if current_user.role not in ('gabay', 'superadmin', 'admin', 'manager', 'supervisor'):
        return redirect(url_for('dashboard'))
    return render_template('gabay_tutorial_print.html')


@app.route('/campaigns/slide')
@login_required
def campaign_slide():
    if not current_user.is_supervisor:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    return render_template('campaign_slide.html')


@app.route('/privacy-policy')
def privacy_policy():
    return render_template('privacy_policy.html')


@app.route('/ai-intelligence/brochure')
@login_required
def ai_intel_brochure():
    if not current_user.is_supervisor:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    return render_template('ai_intel_brochure.html')


@app.route('/uploads/visits/<path:filename>')
@login_required
def visit_photo(filename):
    visit_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'visits')
    return send_file(os.path.join(visit_dir, filename))


@app.route('/gabay/app/visits')
@login_required
def gabay_app_visits():
    visits = Visit.query.filter_by(gabay_id=current_user.id)\
        .order_by(Visit.visited_at.desc()).limit(60).all()
    for v in visits:
        v.lead  # eager load
    return render_template('gabay_app/visits.html', visits=visits)


@app.route('/gabay/app/profile', methods=['GET', 'POST'])
@login_required
def gabay_app_profile():
    if request.method == 'POST':
        photo = request.files.get('profile_photo')
        if photo and photo.filename:
            import os, uuid
            ext = os.path.splitext(photo.filename)[1].lower()
            if ext in ('.jpg', '.jpeg', '.png', '.webp', '.gif'):
                fname = f"profile_{current_user.id}_{uuid.uuid4().hex[:8]}{ext}"
                upload_dir = os.path.join(app.root_path, 'static', 'uploads', 'profiles')
                os.makedirs(upload_dir, exist_ok=True)
                photo.save(os.path.join(upload_dir, fname))
                if current_user.profile_photo:
                    old = os.path.join(upload_dir, current_user.profile_photo)
                    if os.path.exists(old):
                        os.remove(old)
                current_user.profile_photo = fname
                db.session.commit()
                flash('Profile photo updated!', 'success')
            else:
                flash('Only JPG, PNG, WEBP or GIF allowed.', 'danger')
        return redirect(url_for('gabay_app_profile'))
    stats = _gabay_stats(current_user.id)
    return render_template('gabay_app/profile.html',
        stats=stats, conversion_rate=stats['conversion_rate'])


@app.route('/gabay/app/leads-json')
@login_required
def gabay_leads_json_offline():
    gid = current_user.id
    leads = Lead.query.filter(
        Lead.gabay_id == gid,
        Lead.status.in_(['assigned', 'attempting', 'negotiation', 'registration'])
    ).order_by(Lead.seller_name).all()
    return jsonify([{
        'id': l.id, 'seller_name': l.seller_name, 'city': l.city or '',
        'contact_number': l.contact_number or '', 'address': l.address or '',
        'status': l.status, 'category': l.category or ''
    } for l in leads])


@app.route('/gabay/app/batch-checkin', methods=['GET', 'POST'])
@login_required
def gabay_batch_checkin():
    if current_user.role not in ('gabay', 'admin', 'manager', 'supervisor'):
        return redirect(url_for('dashboard'))
    gid = current_user.id
    my_leads = Lead.query.filter(
        Lead.gabay_id == gid,
        Lead.status.in_(['assigned', 'attempting', 'negotiation'])
    ).order_by(Lead.city, Lead.seller_name).all()
    if request.method == 'POST':
        lead_ids = request.form.getlist('lead_ids')
        outcome = request.form.get('outcome')
        notes = request.form.get('notes', '')
        gps_lat = request.form.get('gps_lat')
        gps_lng = request.form.get('gps_lng')
        gps_address = request.form.get('gps_address', '')
        count = 0
        for lid in lead_ids:
            lead = Lead.query.get(int(lid))
            if lead and lead.gabay_id == gid:
                visit = Visit(
                    lead_id=int(lid), gabay_id=gid, visited_at=datetime.utcnow(),
                    gps_lat=float(gps_lat) if gps_lat else None,
                    gps_lng=float(gps_lng) if gps_lng else None,
                    gps_address=gps_address, outcome=outcome, notes=notes
                )
                db.session.add(visit)
                count += 1
        db.session.commit()
        flash(f'{count} visit{"s" if count != 1 else ""} logged!', 'success')
        return redirect(url_for('gabay_home'))
    return render_template('gabay_app/batch_checkin.html', my_leads=my_leads)


@app.route('/targets', methods=['GET', 'POST'])
@login_required
def targets():
    if not current_user.is_manager:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    from datetime import timedelta
    today = date.today()
    month_str = today.strftime('%Y-%m')
    gabay_users = User.query.filter_by(role='gabay', is_active=True).order_by(User.full_name).all()

    if request.method == 'POST':
        for g in gabay_users:
            tv = request.form.get(f'visits_{g.id}', 0, type=int)
            tl = request.form.get(f'live_{g.id}', 0, type=int)
            t = GabayTarget.query.filter_by(gabay_id=g.id, month=month_str).first()
            if t:
                t.target_visits = tv
                t.target_live = tl
            else:
                db.session.add(GabayTarget(gabay_id=g.id, month=month_str,
                                           target_visits=tv, target_live=tl,
                                           set_by=current_user.id))
        db.session.commit()
        flash('Targets saved for ' + today.strftime('%B %Y') + '.', 'success')
        return redirect(url_for('targets'))

    rows = []
    for g in gabay_users:
        t = GabayTarget.query.filter_by(gabay_id=g.id, month=month_str).first()
        actual_visits = Visit.query.filter(
            Visit.gabay_id == g.id,
            extract('year', Visit.visited_at) == today.year,
            extract('month', Visit.visited_at) == today.month
        ).count()
        actual_live = Lead.query.filter_by(gabay_id=g.id, status='live').count()
        rows.append({
            'gabay': g,
            'target_visits': t.target_visits if t else 0,
            'target_live': t.target_live if t else 0,
            'actual_visits': actual_visits,
            'actual_live': actual_live,
        })
    return render_template('targets.html', rows=rows, month=today.strftime('%B %Y'))


@app.route('/activity')
@login_required
def activity_log():
    if not current_user.is_manager:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))
    from datetime import timedelta

    gabay_filter = request.args.get('gabay', '', type=str)
    days = request.args.get('days', 7, type=int)
    action_type = request.args.get('type', 'all')
    cutoff = datetime.utcnow() - timedelta(days=days)

    gabay_users = User.query.filter_by(role='gabay', is_active=True).order_by(User.full_name).all()

    events = []

    # Visits
    if action_type in ('all', 'visits'):
        vq = Visit.query.filter(Visit.visited_at >= cutoff)
        if gabay_filter:
            vq = vq.filter(Visit.gabay_id == int(gabay_filter))
        for v in vq.order_by(Visit.visited_at.desc()).limit(200).all():
            lead = Lead.query.get(v.lead_id)
            gabay = User.query.get(v.gabay_id)
            events.append({
                'type': 'visit', 'ts': v.visited_at,
                'gabay': gabay.full_name if gabay else '—',
                'detail': f'Visited {lead.seller_name if lead else "unknown"} — {v.outcome_label}',
                'meta': lead.city if lead else '',
                'link': f'/gabay/app/lead/{v.lead_id}' if lead else None,
                'color': '#2E75B6',
            })

    # Assignments
    if action_type in ('all', 'assignments'):
        aq = LeadAssignmentHistory.query.filter(LeadAssignmentHistory.assigned_at >= cutoff)
        if gabay_filter:
            aq = aq.filter(LeadAssignmentHistory.gabay_id == int(gabay_filter))
        for h in aq.order_by(LeadAssignmentHistory.assigned_at.desc()).limit(200).all():
            lead = Lead.query.get(h.lead_id)
            gabay = User.query.get(h.gabay_id)
            assigner = User.query.get(h.assigned_by)
            events.append({
                'type': 'assignment', 'ts': h.assigned_at,
                'gabay': gabay.full_name if gabay else '—',
                'detail': f'Lead assigned: {lead.seller_name if lead else "unknown"}',
                'meta': f'by {assigner.full_name if assigner else "system"}',
                'link': f'/leads/{h.lead_id}' if lead else None,
                'color': '#15803d',
            })

    events.sort(key=lambda e: e['ts'], reverse=True)
    events = events[:300]

    return render_template('activity.html',
        events=events, gabay_users=gabay_users,
        gabay_filter=gabay_filter, days=days, action_type=action_type)


# ── Cloudinary helper ────────────────────────────────────────────────────────
def _cloudinary_upload(file_obj, folder='lsams/presentations', resource_type='raw'):
    import cloudinary
    import cloudinary.uploader
    cloudinary.config(
        cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
        api_key=os.environ.get('CLOUDINARY_API_KEY'),
        api_secret=os.environ.get('CLOUDINARY_API_SECRET'),
    )
    result = cloudinary.uploader.upload(
        file_obj,
        folder=folder,
        resource_type=resource_type,
        use_filename=True,
        unique_filename=True,
    )
    return result  # keys: public_id, secure_url, format, bytes


# ── Presentations library ─────────────────────────────────────────────────────
@app.route('/presentations')
@login_required
def presentations_list():
    cat = request.args.get('cat', '')
    q   = request.args.get('q', '').strip()
    role = current_user.role

    query = Presentation.query
    # Visibility filter
    if role in ('gabay',):
        query = query.filter(Presentation.visible_to == 'all')
    elif role in ('supervisor',):
        query = query.filter(Presentation.visible_to.in_(['all', 'supervisor']))
    # managers/admins see everything

    if cat:
        query = query.filter(Presentation.category == cat)
    if q:
        query = query.filter(Presentation.title.ilike(f'%{q}%'))

    items = query.order_by(Presentation.uploaded_at.desc()).all()
    can_upload = role in ('supervisor', 'manager', 'admin', 'superadmin')
    return render_template('presentations/list.html',
                           items=items, cat=cat, q=q, can_upload=can_upload)


@app.route('/presentations/upload', methods=['GET', 'POST'])
@login_required
def presentations_upload():
    if current_user.role not in ('supervisor', 'manager', 'admin', 'superadmin'):
        flash('Access denied.', 'danger')
        return redirect(url_for('presentations_list'))

    if request.method == 'POST':
        title      = request.form.get('title', '').strip()
        description= request.form.get('description', '').strip()
        category   = request.form.get('category', 'general')
        visible_to = request.form.get('visible_to', 'all')
        f          = request.files.get('file')

        if not title or not f or not f.filename:
            flash('Title and file are required.', 'danger')
            return redirect(url_for('presentations_upload'))

        ext = f.filename.rsplit('.', 1)[-1].lower()
        if ext not in ('pdf', 'pptx', 'ppt'):
            flash('Only PDF and PPTX files are allowed.', 'danger')
            return redirect(url_for('presentations_upload'))

        cld_key = os.environ.get('CLOUDINARY_API_KEY', '')
        if not cld_key:
            flash('Cloudinary not configured. Contact admin.', 'danger')
            return redirect(url_for('presentations_upload'))

        try:
            result = _cloudinary_upload(f, folder='lsams/presentations', resource_type='raw')
            pres = Presentation(
                title=title, description=description, category=category,
                file_type=ext, visible_to=visible_to,
                cloudinary_id=result['public_id'],
                cloudinary_url=result['secure_url'],
                uploaded_by=current_user.id,
            )
            db.session.add(pres)
            db.session.commit()
            flash(f'"{title}" uploaded successfully!', 'success')
            return redirect(url_for('presentations_list'))
        except Exception as ex:
            flash(f'Upload failed: {str(ex)}', 'danger')
            return redirect(url_for('presentations_upload'))

    return render_template('presentations/upload.html')


@app.route('/presentations/view/<int:pid>')
@login_required
def presentations_view(pid):
    pres = Presentation.query.get_or_404(pid)
    role = current_user.role
    if pres.visible_to == 'supervisor' and role not in ('supervisor','manager','admin','superadmin'):
        flash('Access denied.', 'danger')
        return redirect(url_for('presentations_list'))
    if pres.visible_to == 'manager' and role not in ('manager','admin','superadmin'):
        flash('Access denied.', 'danger')
        return redirect(url_for('presentations_list'))
    return render_template('presentations/view.html', pres=pres)


@app.route('/presentations/download/<int:pid>')
@login_required
def presentations_download(pid):
    pres = Presentation.query.get_or_404(pid)
    role = current_user.role
    if pres.visible_to == 'supervisor' and role not in ('supervisor','manager','admin','superadmin'):
        flash('Access denied.', 'danger')
        return redirect(url_for('presentations_list'))
    if pres.visible_to == 'manager' and role not in ('manager','admin','superadmin'):
        flash('Access denied.', 'danger')
        return redirect(url_for('presentations_list'))
    import urllib.request
    import re
    safe_title = re.sub(r'[^\w\s-]', '', pres.title).strip()
    safe_title = re.sub(r'[\s]+', '-', safe_title).lower()[:60] or 'presentation'
    filename = f'{safe_title}.{pres.file_type}'
    content_type = 'application/pdf' if pres.file_type == 'pdf' else \
                   'application/vnd.openxmlformats-officedocument.presentationml.presentation'
    try:
        with urllib.request.urlopen(pres.cloudinary_url) as resp:
            data = resp.read()
        from flask import Response
        return Response(
            data,
            status=200,
            headers={
                'Content-Type': content_type,
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Length': str(len(data)),
            }
        )
    except Exception as ex:
        flash(f'Download failed: {str(ex)}', 'danger')
        return redirect(url_for('presentations_list'))


@app.route('/presentations/delete/<int:pid>', methods=['POST'])
@login_required
def presentations_delete(pid):
    if current_user.role not in ('manager', 'admin', 'superadmin'):
        flash('Access denied.', 'danger')
        return redirect(url_for('presentations_list'))
    pres = Presentation.query.get_or_404(pid)
    try:
        import cloudinary, cloudinary.uploader
        cloudinary.config(
            cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
            api_key=os.environ.get('CLOUDINARY_API_KEY'),
            api_secret=os.environ.get('CLOUDINARY_API_SECRET'),
        )
        cloudinary.uploader.destroy(pres.cloudinary_id, resource_type='raw')
    except Exception:
        pass
    db.session.delete(pres)
    db.session.commit()
    flash(f'"{pres.title}" deleted.', 'success')
    return redirect(url_for('presentations_list'))


# ─── CITY NORMALIZATION ───────────────────────────────────────────────────────

def _norm_key(city):
    """Return a lowercase, stripped, accent-free, suffix-stripped key for grouping."""
    import unicodedata, re
    if not city:
        return ''
    # Remove accents / special chars (ñ→n, etc.)
    s = unicodedata.normalize('NFKD', str(city)).encode('ascii', 'ignore').decode('ascii')
    s = s.lower().strip()
    # Remove trailing district qualifiers so "Tondo Manila" groups with "Tondo"
    s = re.sub(r'\s+(manila|city|i{1,3}(/i{1,2})?)$', '', s).strip()
    # Collapse whitespace
    s = re.sub(r'\s+', ' ', s)
    return s


# Known Manila district/barangay names that should map to "Manila"
_MANILA_DISTRICTS = {
    'tondo', 'binondo', 'quiapo', 'san nicolas', 'santa cruz', 'sta. cruz',
    'sta cruz', 'sampaloc', 'san miguel', 'san migu', 'ermita', 'malate',
    'paco', 'pandacan', 'santa ana', 'sta. ana', 'port area', 'intramuros',
}

# Explicit alias overrides: normalized_key → canonical name
_EXPLICIT = {
    'quezon': 'Quezon City',
    'caloocan': 'Caloocan',
    'pasay': 'Pasay',
    'paranaque': 'Paranaque',
    'parañaque': 'Paranaque',
    'makati': 'Makati',
    'taguig': 'Taguig',
    'marikina': 'Marikina',
    'malabon': 'Malabon',
    'navotas': 'Navotas',
    'mandaluyong': 'Mandaluyong',
    'valenzuela': 'Valenzuela',
    'las pinas': 'Las Pinas',
    'muntinlupa': 'Muntinlupa',
    'san juan': 'San Juan',
    'pasig': 'Pasig',
    'bacoor': 'Bacoor',
    'imus': 'Imus',
    'dasmarinas': 'Dasmarinas',
    'general trias': 'General Trias',
    'gen. mariano alvarez': 'General Mariano Alvarez',
    'gma': 'General Mariano Alvarez',
    'general mariano alvarez': 'General Mariano Alvarez',
    'trece martires': 'Trece Martires',
    'trese martires': 'Trece Martires',
    'tanza': 'Tanza',
    'naic': 'Naic',
    'kawit': 'Kawit',
    'noveleta': 'Noveleta',
    'rosario': 'Rosario',
    'carmona': 'Carmona',
    'silang': 'Silang',
    'indang': 'Indang',
    'taytay': 'Taytay',
    'cainta': 'Cainta',
    'san mateo': 'San Mateo',
    'rodriguez': 'Rodriguez',
    'binangonan': 'Binangonan',
    'angono': 'Angono',
    'antipolo': 'Antipolo',
    'cogeo': 'Antipolo',
    'pilila': 'Pilila',
    'morong': 'Morong',
}


def _suggest_canonical(norm_key, raw_values):
    """Return the best canonical city name for a group."""
    # Manila districts override
    if norm_key in _MANILA_DISTRICTS:
        return 'Manila'
    if norm_key in _EXPLICIT:
        return _EXPLICIT[norm_key]
    # Pick the most-frequent raw value, title-cased, strip trailing City
    import re
    best = max(raw_values, key=lambda x: x[1])[0] if raw_values else norm_key
    best = best.strip().title()
    return best


_PROVINCE_TO_CITY = {
    'metro manila': 'Manila',
    'ncr': 'Manila',
    'national capital region': 'Manila',
    'rizal': 'Antipolo',
    'bulacan': 'Malolos',
    'cavite': 'Bacoor',
    'laguna': 'Santa Rosa',
    'pampanga': 'San Fernando',
    'batangas': 'Batangas City',
    'quezon': 'Quezon City',
    'nueva ecija': 'Cabanatuan',
    'pangasinan': 'Dagupan',
    'cebu': 'Cebu City',
    'davao del sur': 'Davao City',
    'davao': 'Davao City',
    'iloilo': 'Iloilo City',
    'negros occidental': 'Bacolod',
}

def _suggest_city_from_province(province):
    """Return a suggested city name based on province."""
    key = _norm_key(province)
    if key in _PROVINCE_TO_CITY:
        return _PROVINCE_TO_CITY[key]
    # If province is actually a city name (e.g. "Quezon City"), return it directly
    if 'city' in key:
        return province.strip().title()
    return ''


@app.route('/admin/city-mapping', methods=['GET', 'POST'])
@login_required
def city_mapping():
    if not current_user.is_superadmin:
        flash('Superadmin access required.', 'danger')
        return redirect(url_for('dashboard'))

    from sqlalchemy import func

    if request.method == 'POST':
        action = request.form.get('action', 'rename')

        if action == 'province_fill':
            updated = 0
            for key, val in request.form.items():
                if key.startswith('prov_city_'):
                    province = key[len('prov_city_'):]
                    city = val.strip()
                    if city:
                        result = Lead.query.filter(
                            (Lead.city == None) | (Lead.city == ''),
                            Lead.province == province
                        ).update({'city': city}, synchronize_session=False)
                        updated += result
            # Individual lead city assignments
            for key, val in request.form.items():
                if key.startswith('lead_city_'):
                    lead_id = key[len('lead_city_'):]
                    city = val.strip()
                    if city:
                        Lead.query.filter_by(id=lead_id).update({'city': city})
                        updated += 1
            db.session.commit()
            flash(f'Done! {updated} leads now have a city assigned.', 'success')
            return redirect(url_for('city_mapping') + '?tab=missing')

        if action == 'gabay_assign':
            # Assign cities to gabay agents
            saved = 0
            for key, val in request.form.items():
                if key.startswith('gabay_cities_'):
                    gabay_id = key[len('gabay_cities_'):]
                    cities = val.strip()
                    User.query.filter_by(id=gabay_id).update({'assigned_city': cities})
                    saved += 1
            db.session.commit()
            flash(f'Gabay city assignments saved for {saved} agents.', 'success')
            return redirect(url_for('city_mapping') + '?tab=gabay')

        # Default: rename city variants
        mappings = {}
        for key, val in request.form.items():
            if key.startswith('canon_'):
                raw = key[6:]
                canonical = val.strip()
                if canonical:
                    mappings[raw] = canonical
        updated = 0
        for raw, canonical in mappings.items():
            if raw != canonical:
                updated += Lead.query.filter(Lead.city == raw).update({'city': canonical})
        db.session.commit()
        flash(f'City names fixed: {updated} leads updated.', 'success')
        return redirect(url_for('city_mapping') + '?tab=names')

    # Build groups
    rows = db.session.query(Lead.city, func.count(Lead.id))\
        .group_by(Lead.city).order_by(func.count(Lead.id).desc()).all()

    # Group by normalized key
    from collections import defaultdict
    groups = defaultdict(list)
    for city, cnt in rows:
        key = _norm_key(city) if city else '__no_city__'
        groups[key].append((city, cnt))

    # Build display groups sorted by total leads desc
    display = []
    for key, variants in groups.items():
        total = sum(c for _, c in variants)
        suggested = _suggest_canonical(key, variants) if key != '__no_city__' else None
        # Determine if this group needs attention (more than 1 variant OR differs from canonical)
        needs_fix = bool(len(variants) > 1 or (
            variants[0][0] and variants[0][0] != suggested
        ))
        display.append({
            'key': key,
            'variants': sorted(variants, key=lambda x: -x[1]),
            'total': total,
            'suggested': suggested,
            'needs_fix': needs_fix,
            'is_no_city': key == '__no_city__',
        })

    # Build gabay city coverage map
    gabay_users = User.query.filter_by(role='gabay').all()
    gabay_city_map = {}  # city_lower → gabay display_name
    for u in gabay_users:
        for c in u.city_list:
            gabay_city_map[c.lower()] = u.full_name or u.username

    for g in display:
        if g['is_no_city']:
            g['has_gabay'] = False
            g['gabay_name'] = None
            g['is_clean'] = False
            g['is_straggler'] = False
        else:
            city_lower = (g['suggested'] or '').lower()
            g['has_gabay'] = city_lower in gabay_city_map
            g['gabay_name'] = gabay_city_map.get(city_lower)
            g['is_straggler'] = (not g['is_no_city']) and g['total'] <= 3
            g['is_clean'] = (not g['is_no_city']) and (not g['is_straggler']) and (not g['needs_fix'])

    display.sort(key=lambda x: (-x['is_no_city'], -x['needs_fix'], x['is_straggler'], -x['total']))

    no_city_count = sum(c for city, c in rows if not city)

    # Province breakdown for no-city leads
    prov_rows = db.session.query(Lead.province, func.count(Lead.id))\
        .filter((Lead.city == None) | (Lead.city == ''))\
        .group_by(Lead.province)\
        .order_by(func.count(Lead.id).desc()).all()

    no_city_provinces = []
    no_city_no_province = 0
    # Leads that have no city and no province (need individual edit)
    no_city_no_prov_leads = Lead.query.filter(
        (Lead.city == None) | (Lead.city == ''),
        (Lead.province == None) | (Lead.province == '')
    ).order_by(Lead.seller_name).all()

    for prov, cnt in prov_rows:
        if prov and prov.strip():
            prov_clean = prov.strip()
            suggested_city = _suggest_city_from_province(prov_clean)
            # For Metro Manila, fetch individual leads so user can assign per-lead
            prov_lower = prov_clean.lower().strip()
            is_metro = prov_lower in ('metro manila', 'ncr', 'national capital region',
                                      'metro manila ncr', 'metro', 'ncr / metro manila')
            indiv_leads = []
            if is_metro:
                indiv_leads = Lead.query.filter(
                    (Lead.city == None) | (Lead.city == ''),
                    Lead.province == prov_clean
                ).order_by(Lead.seller_name).all()
            no_city_provinces.append({
                'province': prov_clean,
                'count': cnt,
                'suggested_city': suggested_city,
                'is_metro': is_metro,
                'indiv_leads': indiv_leads,
            })
        else:
            no_city_no_province += cnt

    # All known cities for dropdown
    known_cities = sorted(set(
        g['suggested'] for g in display
        if not g['is_no_city'] and g['suggested']
    ))

    # Gabay list with their current cities for Tab 3
    gabay_list = [{
        'id': u.id,
        'name': u.full_name or u.username,
        'username': u.username,
        'cities': u.assigned_city or '',
    } for u in gabay_users]

    active_tab = request.args.get('tab', 'names')

    return render_template('admin/city_mapping.html',
        groups=display,
        total_leads=sum(c for _, c in rows),
        no_city_count=no_city_count,
        needs_fix_count=sum(1 for g in display if g['needs_fix'] and not g['is_no_city']),
        no_city_provinces=no_city_provinces,
        no_city_no_province=no_city_no_province,
        no_city_no_prov_leads=no_city_no_prov_leads,
        gabay_city_map=gabay_city_map,
        gabay_list=gabay_list,
        known_cities=known_cities,
        active_tab=active_tab)


@app.route('/admin/city-mapping/auto', methods=['POST'])
@login_required
def city_mapping_auto():
    """One-click: apply all auto-suggested canonical names."""
    if not current_user.is_superadmin:
        return jsonify({'error': 'forbidden'}), 403

    from sqlalchemy import func
    from collections import defaultdict

    rows = db.session.query(Lead.city, func.count(Lead.id))\
        .group_by(Lead.city).all()

    groups = defaultdict(list)
    for city, cnt in rows:
        key = _norm_key(city) if city else '__no_city__'
        groups[key].append((city, cnt))

    updated = 0
    for key, variants in groups.items():
        if key == '__no_city__':
            continue
        canonical = _suggest_canonical(key, variants)
        for raw, _ in variants:
            if raw and raw != canonical:
                Lead.query.filter(Lead.city == raw).update({'city': canonical})
                updated += 1

    db.session.commit()
    return jsonify({'updated': updated})


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # Auto-migrate new columns
        _migrate_cols = [
            ("leads", "ai_readiness", "TEXT"),
            ("leads", "ai_inspected_at", "TIMESTAMP"),
            ("leads", "is_warehouse", "BOOLEAN DEFAULT FALSE"),
            ("leads", "is_duplicate_addr", "BOOLEAN DEFAULT FALSE"),
        ]
        for tbl, col, typ in _migrate_cols:
            try:
                db.session.execute(db.text(f'ALTER TABLE {tbl} ADD COLUMN {col} {typ}'))
                db.session.commit()
            except Exception:
                db.session.rollback()
        seed_demo_data()
    app.run(host='0.0.0.0', port=5001, debug=True)
