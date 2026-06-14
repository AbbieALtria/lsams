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
from models import db, User, Lead, Visit, Registration, LeadAssignmentHistory, Notification, GabayTarget

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access LSAMS.'
login_manager.login_message_category = 'warning'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('instance', exist_ok=True)

with app.app_context():
    db.create_all()
    # Add new User columns if they don't exist (safe for existing Railway DB)
    _new_user_cols = [
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
    ]
    with db.engine.connect() as _conn:
        for _col, _type in _new_user_cols:
            try:
                _conn.execute(text(
                    f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {_col} {_type}"
                ))
                _conn.commit()
            except Exception:
                _conn.rollback()


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


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
    # KPI totals
    total_pool = Lead.query.count()
    assigned = Lead.query.filter(Lead.status != 'pool').count()
    attempting = Lead.query.filter_by(status='attempting').count()
    negotiation = Lead.query.filter_by(status='negotiation').count()
    registration = Lead.query.filter_by(status='registration').count()
    live = Lead.query.filter_by(status='live').count()
    matched = Lead.query.filter_by(status='matched').count()

    # Per-gabay summary for table
    gabay_users = User.query.filter_by(role='gabay', is_active=True).all()
    gabay_stats = []
    for g in gabay_users:
        pool = Lead.query.filter_by(gabay_id=g.id).count() + Lead.query.filter_by(status='pool').count() // max(len(gabay_users), 1)
        g_assigned = Lead.query.filter_by(gabay_id=g.id, status='assigned').count()
        g_attempting = Lead.query.filter_by(gabay_id=g.id, status='attempting').count()
        g_negotiation = Lead.query.filter_by(gabay_id=g.id, status='negotiation').count()
        g_registration = Lead.query.filter_by(gabay_id=g.id, status='registration').count()
        g_live = Lead.query.filter_by(gabay_id=g.id, status='live').count()
        g_matched = Lead.query.filter_by(gabay_id=g.id, status='matched').count()
        gabay_stats.append({
            'name': g.full_name, 'pool': pool, 'assigned': g_assigned,
            'attempting': g_attempting, 'negotiation': g_negotiation,
            'registration': g_registration, 'live': g_live, 'matched': g_matched,
        })

    # Recent activity
    recent_visits = Visit.query.order_by(Visit.visited_at.desc()).limit(10).all()

    # Aging leads — assigned/attempting with no visit in 14+ days
    from datetime import timedelta
    aging_cutoff = datetime.utcnow() - timedelta(days=14)
    aging_leads = Lead.query.filter(
        Lead.status.in_(['assigned', 'attempting']),
        ~Lead.id.in_(
            db.session.query(Visit.lead_id).filter(Visit.visited_at >= aging_cutoff)
        )
    ).order_by(Lead.assigned_at.asc()).limit(20).all()
    for al in aging_leads:
        al._gabay = User.query.get(al.gabay_id) if al.gabay_id else None

    return render_template('dashboard.html',
        total_pool=total_pool, assigned=assigned, attempting=attempting,
        negotiation=negotiation, registration=registration, live=live,
        matched=matched, gabay_stats=gabay_stats, recent_visits=recent_visits,
        aging_leads=aging_leads)


# ─── LEADS ───────────────────────────────────────────────────────────────────

@app.route('/leads')
@login_required
def leads():
    page = request.args.get('page', 1, type=int)
    status_filter = request.args.get('status', '')
    gabay_filter = request.args.get('gabay', '', type=str)
    search = request.args.get('q', '')
    per_page = 20

    query = Lead.query
    if current_user.role == 'gabay':
        query = query.filter_by(gabay_id=current_user.id)
    if status_filter:
        query = query.filter_by(status=status_filter)
    if gabay_filter:
        query = query.filter_by(gabay_id=gabay_filter)
    if search:
        query = query.filter(or_(
            Lead.seller_name.ilike(f'%{search}%'),
            Lead.business_name.ilike(f'%{search}%'),
            Lead.contact_number.ilike(f'%{search}%'),
            Lead.city.ilike(f'%{search}%')
        ))

    pagination = query.order_by(Lead.imported_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    gabay_users = User.query.filter_by(role='gabay', is_active=True).all()
    return render_template('leads/list.html', pagination=pagination,
                           status_filter=status_filter, gabay_filter=gabay_filter,
                           search=search, gabay_users=gabay_users)


@app.route('/leads/import', methods=['GET', 'POST'])
@login_required
def import_leads():
    if not current_user.is_manager:
        flash('Access denied.', 'danger')
        return redirect(url_for('leads'))

    if request.method == 'POST':
        file = request.files.get('file')
        if not file or not file.filename.endswith(('.xlsx', '.xls', '.csv')):
            flash('Please upload a valid Excel or CSV file.', 'danger')
            return redirect(request.url)

        try:
            if file.filename.endswith('.csv'):
                df = pd.read_csv(file)
            else:
                # header=1 skips the merged "PIC / Seller Details" top row
                df = pd.read_excel(file, header=1)

            # Normalize column names
            df.columns = [str(c).strip() for c in df.columns]
            added, skipped, errors = 0, 0, 0
            duplicates = []

            # Pre-load existing lazada_ids and phones for fast duplicate check
            existing_ids = {r[0] for r in db.session.query(Lead.lazada_id).filter(Lead.lazada_id.isnot(None)).all()}
            existing_phones = {r[0] for r in db.session.query(Lead.contact_number).filter(Lead.contact_number.isnot(None)).all()}

            def val(row, *keys):
                """Return first non-empty value from row for any of the given keys."""
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

                    # Duplicate checks
                    if lazada_id and lazada_id in existing_ids:
                        duplicates.append({'seller': seller, 'reason': f'Leads ID already exists'})
                        skipped += 1
                        continue
                    if phone and phone in existing_phones:
                        duplicates.append({'seller': seller, 'reason': f'Phone {phone} already exists'})
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
            dup_msg = f', {len(duplicates)} duplicate{"s" if len(duplicates)!=1 else ""} skipped' if duplicates else ''
            flash(f'Import complete: {added} added{dup_msg}, {errors} errors.', 'success')
            return redirect(url_for('leads'))
        except Exception as e:
            flash(f'Import failed: {str(e)}', 'danger')

    return render_template('leads/import.html')


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
    query = Visit.query
    if current_user.role == 'gabay':
        query = query.filter_by(gabay_id=current_user.id)
    pagination = query.order_by(Visit.visited_at.desc()).paginate(page=page, per_page=20, error_out=False)
    return render_template('visits/list.html', pagination=pagination)


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

    try:
        import openai as _openai
        client = _openai.OpenAI(api_key=openai_key)

        audio_bytes = audio_file.read()
        import io
        audio_io = io.BytesIO(audio_bytes)
        audio_io.name = 'voice.webm'

        transcript = client.audio.transcriptions.create(
            model='whisper-1',
            file=audio_io,
            language=None,
            prompt=(
                'This is a field sales agent in the Philippines reporting a seller visit outcome. '
                'They may speak in English, Tagalog, or Bisaya/Cebuano. '
                'Common words: interesado, gusto, nag-register, wala, hindi interesado, babalik, tatawag.'
            )
        )
        text = transcript.text.strip()
    except Exception as e:
        return jsonify({'error': f'Transcription failed: {str(e)}'}), 500

    outcome = _parse_outcome(text)
    return jsonify({'text': text, 'outcome': outcome})


def _parse_outcome(text):
    t = text.lower()
    registered_kw = ['register', 'nag-register', 'nakapag', 'sign up', 'signed up', 'na-onboard', 'live na']
    interested_kw = ['interested', 'interesado', 'gusto', 'willing', 'open', 'pwede', 'consider', 'gustong sumali']
    rejected_kw = ['ayaw', 'hindi interesado', 'not interested', 'rejected', 'basta ayaw', 'no thanks', 'wag na', 'hindi na', 'ayaw na']
    not_home_kw = ['wala', 'walang tao', 'not home', 'not around', 'hindi nandoon', 'closed', 'nakasirado', 'store close']
    callback_kw = ['tatawag', 'call back', 'callback', 'tawagan', 'magtatawag', 'call me', 'call later']
    follow_up_kw = ['follow up', 'babalik', 'bumalik', 'balik na lang', 'susunod na', 'next time', 'revisit', 'mag-iwan']

    for kw in registered_kw:
        if kw in t:
            return 'registered'
    for kw in rejected_kw:
        if kw in t:
            return 'rejected'
    for kw in not_home_kw:
        if kw in t:
            return 'not_home'
    for kw in callback_kw:
        if kw in t:
            return 'callback'
    for kw in interested_kw:
        if kw in t:
            return 'interested'
    for kw in follow_up_kw:
        if kw in t:
            return 'follow_up'
    return ''


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
    query = Registration.query
    if current_user.role == 'gabay':
        query = query.join(Lead).filter(Lead.gabay_id == current_user.id)
    if status_filter:
        query = query.filter_by(status=status_filter)
    pagination = query.order_by(Registration.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    return render_template('registrations/list.html', pagination=pagination, status_filter=status_filter)


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

    query = Lead.query.filter_by(status='pool')
    if search:
        query = query.filter(or_(
            Lead.seller_name.ilike(f'%{search}%'),
            Lead.business_name.ilike(f'%{search}%'),
            Lead.contact_number.ilike(f'%{search}%'),
        ))
    if city_filter:
        query = query.filter_by(city=city_filter)

    pagination = query.order_by(Lead.imported_at.asc()).paginate(page=page, per_page=25, error_out=False)
    pool_count = Lead.query.filter_by(status='pool').count()

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
        .filter(Lead.status == 'pool', Lead.city != None, Lead.city != '')\
        .group_by(Lead.city).all()
    for city, count in pool_by_city:
        gabay = city_to_gabay.get(city.lower())
        if gabay:
            orphan_cities.append((city, count, gabay.full_name, gabay.id))
    orphan_cities.sort(key=lambda x: -x[1])  # highest count first

    return render_template('assign/index.html',
        pagination=pagination, pool_leads=pagination.items,
        pool_count=pool_count, gabay_users=gabay_users,
        gabay_counts=gabay_counts, cities=cities,
        recent_assigned=recent_assigned, search=search, city_filter=city_filter,
        orphan_cities=orphan_cities)


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
    pool_leads = Lead.query.filter_by(status='pool').order_by(Lead.imported_at.asc()).all()
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

    pool_leads = Lead.query.filter_by(status='pool').all()

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


@app.route('/reports/daily-field')
@login_required
def report_daily_field():
    if not current_user.is_supervisor:
        flash('Access denied.', 'danger')
        return redirect(url_for('reports'))
    today = date.today()
    visits = Visit.query.filter(func.date(Visit.visited_at) == today)\
        .order_by(Visit.gabay_id, Visit.visited_at).all()
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
    return render_template('reports/daily_field.html',
        visits=visits, today=today, gabay_summary=gabay_summary, now=datetime.utcnow())


@app.route('/reports/gabay-performance')
@login_required
def report_gabay_performance():
    if not current_user.is_supervisor:
        flash('Access denied.', 'danger')
        return redirect(url_for('reports'))
    today = date.today()
    agents = User.query.filter_by(role='gabay', is_active=True).order_by(User.full_name).all()
    rows = []
    for a in agents:
        total = Lead.query.filter_by(gabay_id=a.id).count()
        live = Lead.query.filter_by(gabay_id=a.id, status='live').count()
        matched = Lead.query.filter_by(gabay_id=a.id, status='matched').count()
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
        rows=rows, month=today.strftime('%B %Y'), now=datetime.utcnow())


@app.route('/reports/pipeline-detail')
@login_required
def report_pipeline_detail():
    if not current_user.is_supervisor:
        flash('Access denied.', 'danger')
        return redirect(url_for('reports'))
    statuses = ['pool', 'assigned', 'attempting', 'negotiation', 'registration', 'live', 'matched', 'closed']
    totals = {s: Lead.query.filter_by(status=s).count() for s in statuses}
    city_raw = db.session.query(Lead.city, Lead.status, func.count(Lead.id))\
        .group_by(Lead.city, Lead.status).all()
    cities = {}
    for city, status, count in city_raw:
        c = city or 'Unknown'
        cities.setdefault(c, {s: 0 for s in statuses})
        if status in cities[c]:
            cities[c][status] += count
    cities = sorted(cities.items(), key=lambda x: sum(x[1].values()), reverse=True)[:20]
    return render_template('reports/pipeline_detail.html',
        totals=totals, cities=cities, statuses=statuses, now=datetime.utcnow())


@app.route('/reports/stalled')
@login_required
def report_stalled():
    if not current_user.is_supervisor:
        flash('Access denied.', 'danger')
        return redirect(url_for('reports'))
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(days=7)
    leads = Lead.query.filter(
        Lead.status.in_(['assigned', 'attempting']),
        ~Lead.id.in_(db.session.query(Visit.lead_id).filter(Visit.visited_at >= cutoff))
    ).order_by(Lead.gabay_id, Lead.assigned_at.asc()).all()
    for l in leads:
        l._gabay = User.query.get(l.gabay_id) if l.gabay_id else None
        l._last_visit = Visit.query.filter_by(lead_id=l.id).order_by(Visit.visited_at.desc()).first()
    return render_template('reports/stalled.html', leads=leads, now=datetime.utcnow())


@app.route('/reports/city-coverage')
@login_required
def report_city_coverage():
    if not current_user.is_supervisor:
        flash('Access denied.', 'danger')
        return redirect(url_for('reports'))
    visited_ids = {v.lead_id for v in Visit.query.with_entities(Visit.lead_id).all()}
    city_raw = db.session.query(Lead.city, func.count(Lead.id)).group_by(Lead.city).all()
    rows = []
    for city, total in city_raw:
        city_name = city or 'Unknown'
        leads_in = Lead.query.filter_by(city=city).with_entities(Lead.id, Lead.status).all()
        visited = sum(1 for l in leads_in if l.id in visited_ids)
        live = sum(1 for l in leads_in if l.status == 'live')
        rows.append({'city': city_name, 'total': total, 'visited': visited,
                     'unvisited': total - visited, 'live': live,
                     'coverage': round(visited / total * 100) if total else 0})
    rows.sort(key=lambda x: x['total'], reverse=True)
    return render_template('reports/city_coverage.html', cities=rows, now=datetime.utcnow())


@app.route('/reports/registrations-status')
@login_required
def report_registrations_status():
    if not current_user.is_supervisor:
        flash('Access denied.', 'danger')
        return redirect(url_for('reports'))
    regs = Registration.query.order_by(Registration.submitted_at.desc()).all()
    for r in regs:
        r._lead = Lead.query.get(r.lead_id) if r.lead_id else None
        r._gabay = User.query.get(r._lead.gabay_id) if r._lead and r._lead.gabay_id else None
    return render_template('reports/registrations_status.html',
        regs=regs, now=datetime.utcnow())


@app.route('/reports/campaign-roi')
@login_required
def report_campaign_roi():
    if not current_user.is_supervisor:
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
    if not current_user.is_supervisor:
        flash('Access denied.', 'danger')
        return redirect(url_for('reports'))

    gabay_filter = request.args.get('gabay', type=int)
    tier_filter  = request.args.get('tier', '')
    status_filter = request.args.get('status', '')

    q = Lead.query.filter(Lead.status.notin_(['pool', 'live', 'matched', 'closed']))
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

    return render_template('reports/lead_scoring.html',
        leads=scored, gabay_users=gabay_users,
        gabay_filter=gabay_filter, tier_filter=tier_filter,
        status_filter=status_filter, tier_counts=tier_counts,
        now=datetime.utcnow())


@app.route('/reports/gabay-pipeline')
@login_required
def report_gabay_pipeline():
    if not current_user.is_supervisor:
        flash('Access denied.', 'danger')
        return redirect(url_for('reports'))
    gabay_users = User.query.filter_by(role='gabay').order_by(User.full_name).all()
    report_rows = []
    for g in gabay_users:
        total   = Lead.query.filter_by(gabay_id=g.id).count()
        visits  = Visit.query.filter_by(gabay_id=g.id).count()
        by_status = {}
        for s in ('assigned','attempting','negotiation','registration','live','matched','closed'):
            by_status[s] = Lead.query.filter_by(gabay_id=g.id, status=s).count()
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
    return render_template('reports/gabay_pipeline.html',
        rows=report_rows, now=datetime.utcnow(),
        total_leads=Lead.query.count(),
        total_visits=Visit.query.count())


@app.route('/api/reports/kpi')
@login_required
def api_kpi():
    data = {
        'total_pool': Lead.query.count(),
        'assigned': Lead.query.filter(Lead.status != 'pool').count(),
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


@app.route('/reports/export/leads')
@login_required
def export_leads():
    if not current_user.is_supervisor:
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
    return render_template('admin/users.html', users=users)


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
        else:
            u.assigned_city = None
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


@app.route('/gabay/app')
@login_required
def gabay_home():
    if current_user.role not in ('gabay', 'admin', 'manager', 'supervisor'):
        return redirect(url_for('dashboard'))
    gid = current_user.id
    stats = _gabay_stats(gid)
    hour = datetime.now().hour
    greeting = 'Good morning' if hour < 12 else ('Good afternoon' if hour < 18 else 'Good evening')
    today_str = datetime.now().strftime('%A, %B %d, %Y')
    followups = Lead.query.filter(
        Lead.gabay_id == gid,
        Lead.status.in_(['assigned', 'attempting', 'negotiation'])
    ).join(Visit, Lead.id == Visit.lead_id).filter(
        func.date(Visit.follow_up_date) == date.today()
    ).limit(5).all()
    priority_leads = Lead.query.filter(
        Lead.gabay_id == gid,
        Lead.status.in_(['negotiation', 'attempting', 'assigned'])
    ).order_by(Lead.assigned_at.asc()).limit(8).all()
    stalled_cutoff = datetime.utcnow().replace(hour=0, minute=0, second=0) - \
        __import__('datetime').timedelta(days=7)
    stalled_count = Lead.query.filter(
        Lead.gabay_id == gid,
        Lead.status.in_(['assigned', 'attempting']),
        ~Lead.id.in_(
            db.session.query(Visit.lead_id).filter(Visit.visited_at >= stalled_cutoff)
        )
    ).count()

    # Smart suggestions: group active leads by city, rank by never-visited then stalled
    from collections import defaultdict
    active_leads = Lead.query.filter(
        Lead.gabay_id == gid,
        Lead.status.in_(['assigned', 'attempting', 'negotiation'])
    ).all()
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

    return render_template('gabay_app/home.html',
        stats=stats, greeting=greeting, today=today_str,
        followups=followups, priority_leads=priority_leads, stalled_count=stalled_count,
        suggested_leads=suggested_leads, traffic_msg=traffic_msg, traffic_level=traffic_level)


@app.route('/gabay/app/leads')
@login_required
def gabay_app_leads():
    gid = current_user.id
    active_status = request.args.get('status', 'all')
    q = request.args.get('q', '')
    status_tabs = [
        ('All', 'all', Lead.query.filter_by(gabay_id=gid).count()),
        ('Assigned', 'assigned', Lead.query.filter_by(gabay_id=gid, status='assigned').count()),
        ('Attempting', 'attempting', Lead.query.filter_by(gabay_id=gid, status='attempting').count()),
        ('Negotiation', 'negotiation', Lead.query.filter_by(gabay_id=gid, status='negotiation').count()),
        ('Registration', 'registration', Lead.query.filter_by(gabay_id=gid, status='registration').count()),
        ('Live', 'live', Lead.query.filter_by(gabay_id=gid, status='live').count()),
    ]
    query = Lead.query.filter_by(gabay_id=gid)
    if active_status != 'all':
        query = query.filter_by(status=active_status)
    leads = query.order_by(Lead.assigned_at.desc()).all()
    for lead in leads:
        last = Visit.query.filter_by(lead_id=lead.id).order_by(Visit.visited_at.desc()).first()
        lead.last_visit_date = last.visited_at.strftime('%b %d') if last else None
    return render_template('gabay_app/leads.html',
        leads=leads, total=Lead.query.filter_by(gabay_id=gid).count(),
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
            photos=json.dumps(photo_filenames) if photo_filenames else None
        )
        db.session.add(visit)
        if new_status:
            lead = Lead.query.get(lead_id)
            if lead:
                lead.status = new_status
        db.session.commit()
        flash('Visit logged successfully!', 'success')
        return redirect(url_for('gabay_home'))
    return render_template('gabay_app/checkin.html', my_leads=my_leads, selected_lead=selected_lead)


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


@app.route('/presentation')
@login_required
def presentation():
    return render_template('presentation.html')


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
        seed_demo_data()
    app.run(host='0.0.0.0', port=5001, debug=True)
