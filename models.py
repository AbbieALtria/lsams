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
    # Gabay territory — city or cities this agent covers (comma-separated for multi-city)
    assigned_city = db.Column(db.String(300))

    leads_assigned = db.relationship('Lead', backref='assigned_gabay', lazy='dynamic', foreign_keys='Lead.gabay_id')
    visits = db.relationship('Visit', backref='gabay', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

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


class Lead(db.Model):
    __tablename__ = 'leads'
    id = db.Column(db.Integer, primary_key=True)
    # Seller info — matches Lazada Excel export columns
    seller_name = db.Column(db.String(200), nullable=False)   # Shop Name
    lazada_id = db.Column(db.String(100), unique=True)         # Leads ID (UUID)
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
    notes = db.Column(db.Text)

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
    def priority_score(self):
        score = 0
        # Age penalty: 1pt per day assigned, capped at 20
        score += min(self.age_days, 20)
        # High-value statuses need faster action
        if self.status == 'negotiation':
            score += 15
        elif self.status == 'registration':
            score += 12
        elif self.status == 'attempting':
            score += 5
        # Stalled penalty: no visit in 7+ days
        lvd = self.last_visit_days
        if lvd is None and self.status in ('assigned', 'attempting', 'negotiation'):
            score += 10  # never visited
        elif lvd is not None and lvd >= 7:
            score += 8   # visited but stalled
        return score

    @property
    def priority_label(self):
        s = self.priority_score
        lvd = self.last_visit_days
        no_visit = lvd is None and self.status in ('assigned', 'attempting', 'negotiation')
        stalled = (lvd is not None and lvd >= 7) or no_visit
        if stalled:
            return ('Stalled', '#b91c1c', 'bi-exclamation-triangle-fill')
        if s >= 25:
            return ('Hot', '#E07B00', 'bi-fire')
        if s >= 12:
            return ('Warm', '#2E75B6', 'bi-arrow-up-circle-fill')
        return ('Normal', '#15803d', 'bi-check-circle')


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
