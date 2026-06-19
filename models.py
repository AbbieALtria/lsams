import json
from datetime import datetime, date, timedelta
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(30), nullable=False, default='gabay')  # admin, manager, supervisor, gabay
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    last_seen  = db.Column(db.DateTime)   # updated on every page load
    # Gabay territory — city or cities this agent covers (comma-separated for multi-city)
    assigned_city = db.Column(db.String(300))

    # WhatsApp alert preference (manager/admin only — superadmin can toggle per user)
    whatsapp_alerts_enabled = db.Column(db.Boolean, default=True)

    # Contact info
    mobile = db.Column(db.String(20))
    mobile2 = db.Column(db.String(20))
    viber = db.Column(db.String(20))
    facebook = db.Column(db.String(200))

    # Full address
    house_number = db.Column(db.String(50))
    street = db.Column(db.String(200))
    barangay = db.Column(db.String(100))
    city_address = db.Column(db.String(100))

    # Gabay display name (nickname used in leads, reports, Lazada — different from full_name)
    gabay_name = db.Column(db.String(100))

    # Profile
    profile_photo = db.Column(db.String(200))
    deactivated_at = db.Column(db.DateTime)

    leads_assigned = db.relationship('Lead', backref='assigned_gabay', lazy='dynamic', foreign_keys='Lead.gabay_id')
    visits = db.relationship('Visit', backref='gabay', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def display_name(self):
        """Gabay name for reports/leads/Lazada. Falls back to full_name."""
        try:
            return self.gabay_name or self.full_name
        except Exception:
            return self.full_name

    @property
    def city_list(self):
        """Returns list of assigned cities (normalized, lowercase) for matching."""
        if not self.assigned_city:
            return []
        return [c.strip().lower() for c in self.assigned_city.split(',') if c.strip()]

    @property
    def is_superadmin(self):
        return self.role == 'superadmin'

    @property
    def is_admin(self):
        return self.role in ('superadmin', 'admin')

    @property
    def is_manager(self):
        return self.role in ('superadmin', 'admin', 'manager')

    @property
    def is_supervisor(self):
        return self.role in ('superadmin', 'admin', 'manager', 'supervisor')

    @property
    def is_lazada(self):
        return self.role == 'lazada'

    def __repr__(self):
        return f'<User {self.username}>'


class Campaign(db.Model):
    __tablename__ = 'campaigns'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    priority = db.Column(db.Integer, default=99)   # lower number = higher priority (1 = top)
    status = db.Column(db.String(20), default='active')  # active, archived
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    leads = db.relationship('Lead', backref='campaign', lazy='dynamic')
    priority_logs = db.relationship('CampaignPriorityLog', backref='campaign', lazy='dynamic',
                                    foreign_keys='CampaignPriorityLog.campaign_id')
    creator = db.relationship('User', foreign_keys=[created_by])

    @property
    def lead_count(self):
        return self.leads.count()

    @property
    def active_lead_count(self):
        return self.leads.filter(Lead.status.notin_(['closed'])).count()

    def metrics(self):
        from sqlalchemy import func as _func
        q = db.session.query(
            Lead.status, _func.count(Lead.id)
        ).filter(Lead.campaign_id == self.id).group_by(Lead.status).all()
        counts = {s: c for s, c in q}
        total = sum(counts.values())
        completed = counts.get('live', 0) + counts.get('matched', 0)
        closed = counts.get('closed', 0)
        unvisited = counts.get('pool', 0)
        in_progress = total - completed - closed - unvisited
        avg_age = db.session.query(
            _func.avg(_func.extract('epoch', _func.now()) - _func.extract('epoch', Lead.imported_at)) / 86400
        ).filter(Lead.campaign_id == self.id).scalar() or 0
        return {
            'total': total, 'completed': completed, 'closed': closed,
            'unvisited': unvisited, 'in_progress': in_progress,
            'avg_age_days': round(avg_age, 1)
        }


class CampaignPriorityLog(db.Model):
    __tablename__ = 'campaign_priority_log'
    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaigns.id'), nullable=False)
    changed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    prev_priority = db.Column(db.Integer)
    new_priority = db.Column(db.Integer)
    reason = db.Column(db.Text)
    changed_at = db.Column(db.DateTime, default=datetime.utcnow)

    changer = db.relationship('User', foreign_keys=[changed_by])


class Lead(db.Model):
    __tablename__ = 'leads'
    id = db.Column(db.Integer, primary_key=True)
    # Seller info — matches Lazada Excel export columns
    seller_name = db.Column(db.String(200), nullable=False)   # Shop Name
    lazada_id = db.Column(db.String(100))                       # Leads ID (UUID) — unique per campaign, not globally
    priority_tier = db.Column(db.String(10))                   # P0, P1, P2 …
    project = db.Column(db.String(100))                        # TIKTOK (TTS), TOP COFFEE (TCS) …
    cluster = db.Column(db.String(50))                         # FMCG, FA, EL …
    category = db.Column(db.String(100))
    link = db.Column(db.String(500))                           # TikTok / Shopee URL
    barangay = db.Column(db.String(100))
    city = db.Column(db.String(100))
    province = db.Column(db.String(100))
    address = db.Column(db.Text)                               # Complete Address
    sender_name = db.Column(db.String(200))                    # Sender Name / contact person
    contact_number = db.Column(db.String(50))
    email = db.Column(db.String(120))
    social_media_link = db.Column(db.String(500))
    # Pipeline
    status = db.Column(db.String(50), default='pool')
    # pool, assigned, attempting, negotiation, registration, live, matched, closed
    gabay_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    assigned_at = db.Column(db.DateTime)
    imported_at = db.Column(db.DateTime, default=datetime.utcnow)
    batch_ref = db.Column(db.String(100))
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaigns.id'))
    notes = db.Column(db.Text)
    # ML model output — updated by /admin/ml/train, None = use rule-based score
    ml_score = db.Column(db.Float)
    ml_trained_at = db.Column(db.DateTime)
    # Health inspection flags
    ai_readiness = db.Column(db.Text)       # JSON from Haiku inspection
    ai_inspected_at = db.Column(db.DateTime)
    is_warehouse = db.Column(db.Boolean, default=False)   # fulfillment center flag
    is_duplicate_addr = db.Column(db.Boolean, default=False)
    # AI Lead Intelligence — Phase 3: used for queue ordering
    ai_score = db.Column(db.Integer)          # 0-100 from LeadIntelligence engine

    visits = db.relationship('Visit', backref='lead', lazy='dynamic', cascade='all, delete-orphan')
    registration = db.relationship('Registration', backref='lead', uselist=False, cascade='all, delete-orphan')

    @property
    def latest_visit(self):
        return self.visits.order_by(Visit.visited_at.desc()).first()

    @property
    def status_label(self):
        labels = {
            'pool': 'Pool', 'assigned': 'Assigned', 'attempting': 'Attempting Contact',
            'negotiation': 'Negotiation', 'registration': 'Registration',
            'live': 'Live Seller', 'matched': 'Matched', 'closed': 'Closed'
        }
        return labels.get(self.status, self.status.title())

    @property
    def status_color(self):
        colors = {
            'pool': 'secondary', 'assigned': 'primary', 'attempting': 'warning',
            'negotiation': 'info', 'registration': 'purple', 'live': 'success',
            'matched': 'success', 'closed': 'danger'
        }
        return colors.get(self.status, 'secondary')

    @property
    def age_days(self):
        ref = self.assigned_at or self.imported_at or datetime.utcnow()
        return (datetime.utcnow() - ref).days

    @property
    def last_visit_days(self):
        last = self.visits.order_by(Visit.visited_at.desc()).first()
        if not last:
            return None
        return (datetime.utcnow() - last.visited_at).days

    @property
    def conversion_score(self):
        """
        Lead conversion score 0–100. Higher = more likely to register soon.
        When the ML model has been trained and scored this lead, the ML score
        is blended in (70% ML, 30% rules). Otherwise pure rule-based.

        Rule factors (max pts):
          Priority tier          : 20
          Status progression     : 20
          Visit outcome momentum : 25
          Recency of last visit  : 15
          Follow-up compliance   : 10
          Category/cluster bonus :  8
          Online presence bonus  :  5
          Contact info bonus     :  2
          Lead age penalty       : -10 max
        """
        score = 0

        # ── 1. Priority tier (20 pts) ────────────────────────────────────
        tier_pts = {'P0': 20, 'P1': 15, 'P2': 10, 'P3': 5}
        score += tier_pts.get(self.priority_tier or '', 8)

        # ── 2. Status progression (20 pts) ──────────────────────────────
        status_pts = {
            'pool': 0, 'assigned': 4, 'attempting': 8,
            'negotiation': 16, 'registration': 20,
            'live': 20, 'matched': 20, 'closed': 0,
        }
        score += status_pts.get(self.status, 0)

        # ── 3. Visit outcome momentum (25 pts) ──────────────────────────
        outcome_pts = {
            'interested':     10,
            'callback':        8,
            'follow_up':       5,
            'not_home':        2,
            'rejected':      -15,
            'not_interested': -15,
            'registered':     12,
        }
        recent_visits = self.visits.order_by(Visit.visited_at.desc()).limit(5).all()
        visit_score = 0
        for i, v in enumerate(recent_visits):
            weight = 1.0 - (i * 0.15)
            visit_score += outcome_pts.get(v.outcome or '', 0) * weight
        score += max(-20, min(25, int(visit_score)))

        # ── 4. Recency of last visit (15 pts) ───────────────────────────
        lvd = self.last_visit_days
        if lvd is None:
            recency = -5
        elif lvd <= 2:
            recency = 15
        elif lvd <= 5:
            recency = 12
        elif lvd <= 10:
            recency = 8
        elif lvd <= 21:
            recency = 4
        elif lvd <= 45:
            recency = 0
        else:
            recency = -8
        score += recency

        # ── 5. Follow-up compliance (10 pts) ────────────────────────────
        last_v = self.latest_visit
        if last_v and last_v.follow_up_date:
            days_to_fu = (last_v.follow_up_date - datetime.utcnow().date()).days
            if -3 <= days_to_fu <= 1:
                score += 10
            elif days_to_fu < -3:
                score += 5
            elif days_to_fu <= 7:
                score += 6

        # ── 6. Category / cluster affinity (8 pts) ──────────────────────
        # High-volume categories on Lazada PH that convert faster
        HIGH_CONV_CATEGORIES = {
            'beauty', 'health', 'fashion', 'clothing', 'accessories',
            'food', 'beverage', 'snacks', 'groceries', 'fmcg',
            'home', 'kitchen', 'appliances', 'electronics',
        }
        MEDIUM_CONV_CATEGORIES = {
            'sports', 'automotive', 'toys', 'baby', 'pet',
            'office', 'tools', 'garden',
        }
        cat = (self.category or '').lower()
        cluster = (self.cluster or '').lower()
        cat_text = f'{cat} {cluster}'
        if any(k in cat_text for k in HIGH_CONV_CATEGORIES):
            score += 8
        elif any(k in cat_text for k in MEDIUM_CONV_CATEGORIES):
            score += 4

        # ── 7. Online presence — existing shop = easier onboarding (5 pts)
        if self.link:
            score += 3   # TikTok / Shopee shop already exists
        if self.social_media_link:
            score += 2   # Facebook / Instagram presence

        # ── 8. Contact info available (2 pts) ───────────────────────────
        if self.contact_number:
            score += 2

        # ── 9. Lead age penalty (up to -10) ─────────────────────────────
        age = self.age_days
        if age > 60:
            score -= 10
        elif age > 30:
            score -= 5

        rule_score = max(0, min(100, score))

        # ── 10. Blend ML score if available (70% ML, 30% rules) ─────────
        if self.ml_score is not None:
            return int(round(self.ml_score * 0.7 + rule_score * 0.3))

        return rule_score

    @property
    def conversion_tier(self):
        """Returns (label, color, bg, icon) based on conversion_score."""
        s = self.conversion_score
        if s >= 70:
            return ('Hot',    '#b91c1c', '#fee2e2', '🔥')
        if s >= 50:
            return ('Warm',   '#d97706', '#fef3c7', '⚡')
        if s >= 30:
            return ('Cool',   '#2563eb', '#dbeafe', '📋')
        return     ('Cold',   '#6b7280', '#f3f4f6', '🧊')

    @property
    def priority_score(self):
        return self.conversion_score

    @property
    def priority_label(self):
        label, color, bg, icon = self.conversion_tier
        icon_map = {'Hot': 'bi-fire', 'Warm': 'bi-lightning-charge-fill',
                    'Cool': 'bi-arrow-up-circle-fill', 'Cold': 'bi-snow'}
        return (label, color, icon_map.get(label, 'bi-circle'))


class Visit(db.Model):
    __tablename__ = 'visits'
    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('leads.id'), nullable=False)
    gabay_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    visited_at = db.Column(db.DateTime, default=datetime.utcnow)
    gps_lat = db.Column(db.Float)
    gps_lng = db.Column(db.Float)
    gps_address = db.Column(db.String(300))
    outcome = db.Column(db.String(50))  # interested, not_interested, follow_up, no_contact
    notes = db.Column(db.Text)
    follow_up_date = db.Column(db.Date)
    photos = db.Column(db.Text)  # JSON list of filenames
    photo_pending = db.Column(db.Boolean, default=False)  # True = submitted without photos, upload later

    @property
    def photos_list(self):
        if not self.photos:
            return []
        try:
            return json.loads(self.photos)
        except Exception:
            return []

    @property
    def outcome_label(self):
        labels = {
            'interested': 'Interested', 'not_interested': 'Not Interested',
            'follow_up': 'Follow Up', 'no_contact': 'No Contact'
        }
        return labels.get(self.outcome, self.outcome or '—')

    @property
    def outcome_color(self):
        colors = {
            'interested': 'success', 'not_interested': 'danger',
            'follow_up': 'warning', 'no_contact': 'secondary'
        }
        return colors.get(self.outcome, 'secondary')


class Registration(db.Model):
    __tablename__ = 'registrations'
    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('leads.id'), nullable=False)
    status = db.Column(db.String(30), default='draft')  # draft, pending, approved, rejected
    # Documents
    has_dti = db.Column(db.Boolean, default=False)
    has_permit = db.Column(db.Boolean, default=False)
    has_gov_id = db.Column(db.Boolean, default=False)
    has_tin = db.Column(db.Boolean, default=False)
    has_bank = db.Column(db.Boolean, default=False)
    # Dates
    submitted_at = db.Column(db.DateTime)
    reviewed_at = db.Column(db.DateTime)
    activated_at = db.Column(db.DateTime)
    rejected_at = db.Column(db.DateTime)
    rejection_reason = db.Column(db.Text)
    # VW flags
    is_vw = db.Column(db.Boolean, default=False)
    is_vw_rrld = db.Column(db.Boolean, default=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def docs_complete(self):
        return all([self.has_dti, self.has_permit, self.has_gov_id, self.has_tin, self.has_bank])

    @property
    def docs_count(self):
        return sum([self.has_dti, self.has_permit, self.has_gov_id, self.has_tin, self.has_bank])


class Notification(db.Model):
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    type = db.Column(db.String(50))  # stalled, followup_due, new_assignment, reg_pending, live_achieved
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text)
    link = db.Column(db.String(300))
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    related_lead_id = db.Column(db.Integer, db.ForeignKey('leads.id'))

    TYPE_ICONS = {
        'stalled': ('bi-exclamation-triangle-fill', '#b91c1c'),
        'followup_due': ('bi-calendar-check-fill', '#be185d'),
        'new_assignment': ('bi-person-check-fill', '#2E75B6'),
        'reg_pending': ('bi-file-earmark-check-fill', '#7c3aed'),
        'live_achieved': ('bi-star-fill', '#15803d'),
        'competitor_visit': ('bi-flag-fill', '#d97706'),
    }

    @property
    def icon(self):
        return self.TYPE_ICONS.get(self.type, ('bi-bell-fill', '#9aabc5'))[0]

    @property
    def color(self):
        return self.TYPE_ICONS.get(self.type, ('bi-bell-fill', '#9aabc5'))[1]

    @property
    def age_label(self):
        delta = datetime.utcnow() - self.created_at
        if delta.seconds < 3600:
            return f'{delta.seconds // 60}m ago'
        if delta.days == 0:
            return f'{delta.seconds // 3600}h ago'
        return f'{delta.days}d ago'


class LeadAssignmentHistory(db.Model):
    __tablename__ = 'lead_assignment_history'
    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('leads.id'), nullable=False)
    gabay_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    assigned_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    assigned_at = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text)


class MLModelRun(db.Model):
    """Tracks each training run of the lead scoring ML model."""
    __tablename__ = 'ml_model_runs'
    id = db.Column(db.Integer, primary_key=True)
    trained_at = db.Column(db.DateTime, default=datetime.utcnow)
    trained_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    n_samples = db.Column(db.Integer)       # total leads used
    n_positive = db.Column(db.Integer)      # live leads (label=1)
    accuracy = db.Column(db.Float)          # cross-val accuracy
    roc_auc = db.Column(db.Float)           # AUC score
    top_features = db.Column(db.Text)       # JSON: [{name, weight}]
    model_path = db.Column(db.String(300))  # path to .pkl file
    status = db.Column(db.String(30), default='pending')  # pending, success, failed, insufficient_data
    notes = db.Column(db.Text)


class StrictBuilding(db.Model):
    __tablename__ = 'strict_buildings'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(300), nullable=False)       # building / barangay / village
    city = db.Column(db.String(100))
    reason = db.Column(db.Text)                            # e.g. "Strict guard, no entry without appointment"
    source = db.Column(db.String(20), default='manual')   # 'auto' or 'manual'
    times_encountered = db.Column(db.Integer, default=1)
    added_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    added_by = db.relationship('User', foreign_keys=[added_by_id])


class GabayTarget(db.Model):
    __tablename__ = 'gabay_targets'
    id = db.Column(db.Integer, primary_key=True)
    gabay_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    month = db.Column(db.String(7), nullable=False)  # 'YYYY-MM'
    target_visits = db.Column(db.Integer, default=0)
    target_live = db.Column(db.Integer, default=0)
    set_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('gabay_id', 'month', name='uq_gabay_month'),)


class LeadIntelligence(db.Model):
    """AI-enriched intel per lead — web scan + Claude Haiku analysis."""
    __tablename__ = 'lead_intelligence'
    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('leads.id'), unique=True, nullable=False)
    # Core
    ai_score = db.Column(db.Integer)          # 0-100
    ai_brief = db.Column(db.Text)             # pre-visit brief for Gabay
    score_reason = db.Column(db.Text)
    # Platform data
    platforms_json = db.Column(db.Text)       # JSON list of {name, status, detail, followers, rating, product_count, last_active}
    is_on_lazada = db.Column(db.Boolean)      # already registered on Lazada?
    top_platform = db.Column(db.String(50))   # strongest platform found
    max_followers = db.Column(db.Integer)     # highest follower count across all platforms
    last_active = db.Column(db.String(50))    # e.g. "2 days ago", "last week"
    # Product intelligence
    product_category = db.Column(db.String(200))  # e.g. "Baked goods / Food & Beverage"
    price_range = db.Column(db.String(100))        # e.g. "Budget RM10–50"
    avg_rating = db.Column(db.Float)               # best rating found across platforms
    product_count = db.Column(db.Integer)          # total products listed
    # Scan metadata
    scan_status = db.Column(db.String(20), default='pending')  # pending/running/done/failed
    scan_trigger = db.Column(db.String(30))   # auto/manual/campaign_sweep
    scanned_at = db.Column(db.DateTime)
    error_msg = db.Column(db.Text)
    lead = db.relationship('Lead', backref=db.backref('intelligence', uselist=False))

    @property
    def platforms(self):
        try:
            return json.loads(self.platforms_json or '[]')
        except Exception:
            return []

    @property
    def active_platforms(self):
        return [p for p in self.platforms if p.get('status') == 'active']
