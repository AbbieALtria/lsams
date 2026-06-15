"""
LSAMS WhatsApp Bot
Gabay sends: "Visited Chokorean Online — seller interested, will call next week"
Bot: parses with Claude → creates Visit record → replies with confirmation
"""

import os
import json
import logging
import requests
from datetime import datetime, timedelta
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

WHATSAPP_TOKEN    = os.environ.get('WHATSAPP_TOKEN', '')
WHATSAPP_PHONE_ID = os.environ.get('WHATSAPP_PHONE_ID', '1125313127339997')
GRAPH_URL         = f'https://graph.facebook.com/v25.0/{WHATSAPP_PHONE_ID}/messages'


# ── Send a WhatsApp text message ──────────────────────────────────────────────

def send_message(to: str, text: str):
    """Send a plain text WhatsApp message to `to` (E.164 format, e.g. +639XXXXXXXXX)."""
    payload = {
        'messaging_product': 'whatsapp',
        'to': to,
        'type': 'text',
        'text': {'body': text},
    }
    headers = {
        'Authorization': f'Bearer {WHATSAPP_TOKEN}',
        'Content-Type': 'application/json',
    }
    try:
        r = requests.post(GRAPH_URL, json=payload, headers=headers, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f'WhatsApp send failed: {e}')
        return None


# ── Parse visit message with Claude ──────────────────────────────────────────

def parse_visit_message(text: str) -> dict:
    """
    Use Claude to extract structured visit data from a free-text gabay message.
    Returns dict with keys: seller_name, outcome, notes, follow_up_days
    Falls back to a simple keyword parser if ANTHROPIC_API_KEY is not set.
    """
    import anthropic as _anthropic

    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        return _keyword_parse(text)

    client = _anthropic.Anthropic(api_key=api_key)
    prompt = f"""Extract visit information from this field agent message and return JSON only.

Message: "{text}"

Return a JSON object with exactly these keys:
- seller_name: string (the business/seller name mentioned, or null)
- outcome: one of: interested, not_interested, callback, follow_up, not_home, rejected, registered (pick the closest match based on tone)
- notes: string (any additional context, cleaned up)
- follow_up_days: integer (days until follow-up if mentioned, e.g. "next week" = 7, "tomorrow" = 1, "3 days" = 3, null if not mentioned)

Reply with only the JSON object, no explanation."""

    try:
        msg = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=300,
            messages=[{'role': 'user', 'content': prompt}],
        )
        raw = msg.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith('```'):
            raw = raw.split('```')[1]
            if raw.startswith('json'):
                raw = raw[4:]
        return json.loads(raw.strip())
    except Exception as e:
        logger.warning(f'Claude parse failed: {e}, falling back to keyword parse')
        return _keyword_parse(text)


def _keyword_parse(text: str) -> dict:
    """Fallback: simple keyword-based parser when Claude is unavailable."""
    t = text.lower()
    outcome = 'follow_up'
    if any(w in t for w in ['interested', 'gusto', 'willing', 'open']):
        outcome = 'interested'
    elif any(w in t for w in ['not interested', 'ayaw', 'decline', 'refused']):
        outcome = 'not_interested'
    elif any(w in t for w in ['not home', 'wala', 'closed', 'absent']):
        outcome = 'not_home'
    elif any(w in t for w in ['reject', 'tanggihan']):
        outcome = 'rejected'
    elif any(w in t for w in ['registered', 'live', 'done', 'activated']):
        outcome = 'registered'
    elif any(w in t for w in ['call back', 'callback', 'tawag ulit']):
        outcome = 'callback'

    follow_up_days = None
    if 'tomorrow' in t or 'bukas' in t:
        follow_up_days = 1
    elif 'next week' in t or 'susunod na linggo' in t:
        follow_up_days = 7
    elif '3 days' in t or 'tatlong araw' in t:
        follow_up_days = 3
    elif '2 days' in t:
        follow_up_days = 2

    return {
        'seller_name': None,
        'outcome': outcome,
        'notes': text,
        'follow_up_days': follow_up_days,
    }


# ── Fuzzy lead matching ───────────────────────────────────────────────────────

def find_lead(seller_name: str, gabay_id: int):
    """
    Find the best matching lead for this gabay by seller name.
    Returns (Lead, score) or (None, 0).
    """
    from models import Lead

    if not seller_name:
        return None, 0

    leads = Lead.query.filter_by(gabay_id=gabay_id).all()
    if not leads:
        return None, 0

    best, best_score = None, 0.0
    needle = seller_name.lower().strip()
    for lead in leads:
        hay = (lead.seller_name or '').lower().strip()
        score = SequenceMatcher(None, needle, hay).ratio()
        # Bonus for substring match
        if needle in hay or hay in needle:
            score = max(score, 0.85)
        if score > best_score:
            best_score = score
            best = lead

    return (best, best_score) if best_score >= 0.55 else (None, 0)


# ── Find gabay user by phone number ──────────────────────────────────────────

def find_gabay_by_phone(phone: str):
    """
    Match an incoming WhatsApp phone number to a gabay User.
    Phone comes in as '639XXXXXXXXX' (no +), normalize before comparing.
    """
    from models import User

    # Normalize: strip leading + or country code variations
    phone = phone.lstrip('+')
    if phone.startswith('0'):
        phone = '63' + phone[1:]  # PH local → international

    gabays = User.query.filter_by(role='gabay', is_active=True).all()
    for g in gabays:
        for field in [g.mobile, g.mobile2, g.viber]:
            if not field:
                continue
            normalized = field.lstrip('+').replace('-', '').replace(' ', '')
            if normalized.startswith('0'):
                normalized = '63' + normalized[1:]
            if normalized == phone:
                return g
    return None


# ── Main handler called by the Flask webhook route ───────────────────────────

def handle_incoming(data: dict):
    """
    Process a WhatsApp webhook payload.
    Creates a Visit record and replies with confirmation.
    """
    from models import db, Visit, Lead

    try:
        entry   = data['entry'][0]
        changes = entry['changes'][0]['value']
        messages = changes.get('messages')
        if not messages:
            return  # status update, not a message

        msg     = messages[0]
        from_   = msg['from']           # sender phone e.g. '639171234567'
        msg_id  = msg['id']
        body    = msg.get('text', {}).get('body', '').strip()

        if not body:
            return  # ignore non-text messages for now

        logger.info(f'[WA] Message from {from_}: {body[:80]}')

        # 1. Find which gabay sent this
        gabay = find_gabay_by_phone(from_)
        logger.info(f'[WA] Gabay lookup for {from_}: {gabay}')
        if not gabay:
            logger.warning(f'[WA] No gabay found for number {from_} — sending unregistered reply')
            send_message(from_,
                "⚠️ Your number is not registered in LSAMS. "
                "Ask your supervisor to add your mobile number to your profile.")
            return

        body_lower = body.lower()

        # 2. Help command
        if body_lower in ('help', 'tulong', '?', 'commands'):
            send_message(from_, (
                "📋 *LSAMS Bot Commands*\n\n"
                "Just send a plain message describing your visit:\n"
                "_\"Visited Chokorean Online — seller interested, call next week\"_\n\n"
                "Or use shorthand:\n"
                "• *status* — see your lead summary\n"
                "• *today* — today's visit count\n"
                "• *help* — show this menu"
            ))
            return

        # 3. Status command
        if body_lower in ('status', 'stats', 'summary'):
            from models import func
            from datetime import date
            today = date.today()
            total = Lead.query.filter_by(gabay_id=gabay.id).count()
            live  = Lead.query.filter_by(gabay_id=gabay.id, status='live').count()
            visits_today = Visit.query.filter(
                Visit.gabay_id == gabay.id,
                func.date(Visit.visited_at) == today
            ).count()
            send_message(from_,
                f"📊 *Your LSAMS Summary*\n"
                f"👤 {gabay.display_name}\n"
                f"📋 Leads assigned: {total}\n"
                f"✅ Live sellers: {live}\n"
                f"📍 Visits today: {visits_today}"
            )
            return

        # 4. Today command
        if body_lower in ('today', 'visits today', 'ngayon'):
            from datetime import date
            from models import func
            today = date.today()
            visits = Visit.query.filter(
                Visit.gabay_id == gabay.id,
                func.date(Visit.visited_at) == today
            ).all()
            if not visits:
                send_message(from_, "📍 No visits logged today yet.")
                return
            lines = [f"📍 *Today's Visits ({len(visits)})*"]
            for v in visits:
                lead = Lead.query.get(v.lead_id)
                name = lead.seller_name if lead else '?'
                lines.append(f"• {name} — {v.outcome or 'no outcome'}")
            send_message(from_, '\n'.join(lines))
            return

        # 5. Visit logging — parse the free-text message
        parsed = parse_visit_message(body)
        seller_name   = parsed.get('seller_name')
        outcome       = parsed.get('outcome', 'follow_up')
        notes         = parsed.get('notes', body)
        follow_up_days = parsed.get('follow_up_days')

        lead, match_score = find_lead(seller_name, gabay.id)

        if lead is None:
            # Can't match — ask for clarification
            assigned = Lead.query.filter_by(gabay_id=gabay.id).limit(5).all()
            names = '\n'.join(f"• {l.seller_name}" for l in assigned)
            send_message(from_,
                f"🔍 Couldn't find *\"{seller_name}\"* in your leads.\n\n"
                f"Your recent leads:\n{names}\n\n"
                f"Try: _\"Visited [exact seller name] — [outcome]\"_"
            )
            return

        # 6. Create visit record
        follow_up_date = None
        if follow_up_days:
            follow_up_date = (datetime.utcnow() + timedelta(days=follow_up_days)).date()

        visit = Visit(
            lead_id=lead.id,
            gabay_id=gabay.id,
            visited_at=datetime.utcnow(),
            outcome=outcome,
            notes=f"[WhatsApp] {notes}",
            follow_up_date=follow_up_date,
            gps_address='Logged via WhatsApp',
        )
        db.session.add(visit)

        # Update lead status based on outcome
        STATUS_UPGRADE = {
            'interested':  'negotiation',
            'callback':    'attempting',
            'follow_up':   'attempting',
            'registered':  'registration',
        }
        new_status = STATUS_UPGRADE.get(outcome)
        if new_status:
            status_order = ['pool','assigned','attempting','negotiation','registration','live']
            current_idx  = status_order.index(lead.status) if lead.status in status_order else 0
            new_idx      = status_order.index(new_status)
            if new_idx > current_idx:
                lead.status = new_status

        db.session.commit()

        # 7. Build confirmation reply
        outcome_emoji = {
            'interested': '🟢', 'not_interested': '🔴', 'callback': '🔵',
            'follow_up': '🟡', 'not_home': '⚪', 'rejected': '🔴', 'registered': '✅',
        }.get(outcome, '📋')

        conf = (
            f"✅ *Visit Logged!*\n"
            f"📍 {lead.seller_name}\n"
            f"{outcome_emoji} Outcome: {outcome.replace('_', ' ').title()}\n"
        )
        if follow_up_date:
            conf += f"📅 Follow-up: {follow_up_date.strftime('%b %d, %Y')}\n"
        if match_score < 0.85:
            conf += f"\n_(Matched to \"{lead.seller_name}\" — {int(match_score*100)}% confident)_"
        conf += f"\n\nReply *status* to see your summary or *help* for commands."

        send_message(from_, conf)

    except Exception as e:
        logger.error(f'WhatsApp handle_incoming error: {e}', exc_info=True)
