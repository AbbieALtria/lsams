"""
LSAMS Telegram Bot
Gabay sends: "Visited Chokorean Online — seller interested, will call next week"
Bot: parses with Claude → creates Visit record → replies with confirmation

Registration: Gabay sends /start <lsams_username> to link their account.
"""

import os
import json
import logging
import requests
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_API   = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}'


# ── Send a Telegram message ───────────────────────────────────────────────────

def send_message(chat_id, text: str):
    """Send a plain text Telegram message. Supports basic Markdown."""
    if not TELEGRAM_TOKEN:
        logger.warning('[TG] TELEGRAM_BOT_TOKEN not set')
        return None
    try:
        r = requests.post(
            f'{TELEGRAM_API}/sendMessage',
            json={'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f'[TG] send_message failed: {e}')
        return None


# ── Download & transcribe a Telegram voice message ───────────────────────────

def _transcribe_voice(file_id: str) -> str | None:
    """Download a Telegram voice note and transcribe via OpenAI Whisper."""
    openai_key = os.environ.get('OPENAI_API_KEY')
    if not openai_key:
        logger.warning('[TG] OPENAI_API_KEY not set — cannot transcribe')
        return None

    if not TELEGRAM_TOKEN:
        return None

    # Step 1: resolve file path from Telegram
    try:
        meta = requests.get(
            f'{TELEGRAM_API}/getFile',
            params={'file_id': file_id},
            timeout=10,
        )
        meta.raise_for_status()
        file_path = meta.json()['result']['file_path']
    except Exception as e:
        logger.error(f'[TG] getFile failed: {e}')
        return None

    # Step 2: download audio bytes
    try:
        audio_url = f'https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}'
        audio_resp = requests.get(audio_url, timeout=30)
        audio_resp.raise_for_status()
        audio_bytes = audio_resp.content
    except Exception as e:
        logger.error(f'[TG] Audio download failed: {e}')
        return None

    # Step 3: send to Whisper
    try:
        whisper_resp = requests.post(
            'https://api.openai.com/v1/audio/transcriptions',
            headers={'Authorization': f'Bearer {openai_key}'},
            files={'file': ('voice.ogg', audio_bytes, 'audio/ogg')},
            data={'model': 'whisper-1', 'language': 'tl'},
            timeout=30,
        )
        whisper_resp.raise_for_status()
        return whisper_resp.json().get('text', '').strip() or None
    except Exception as e:
        logger.error(f'[TG] Whisper failed: {e}')
        return None


# ── Find gabay by telegram chat_id ───────────────────────────────────────────

def find_gabay_by_telegram(chat_id) -> 'User | None':
    from models import User
    return User.query.filter_by(
        telegram_chat_id=str(chat_id), role='gabay', is_active=True
    ).first()


# ── Register command: /start <username> ──────────────────────────────────────

def _handle_start(chat_id, text: str):
    """Link a Telegram chat to an LSAMS gabay account."""
    from models import db, User

    parts = text.strip().split(None, 1)
    username = parts[1].strip() if len(parts) > 1 else None

    if not username:
        send_message(chat_id,
            "👋 Welcome to the *LSAMS Bot*!\n\n"
            "To link your account, send:\n"
            "`/start your_lsams_username`\n\n"
            "Example: `/start juan123`\n\n"
            "Ask your supervisor for your LSAMS username if you're unsure."
        )
        return

    user = User.query.filter_by(username=username, role='gabay', is_active=True).first()
    if not user:
        send_message(chat_id,
            f"❌ Username *{username}* not found or not a Gabay account.\n\n"
            "Check the spelling and try again, or ask your supervisor."
        )
        return

    # Check if already linked to another chat
    existing = User.query.filter_by(telegram_chat_id=str(chat_id)).first()
    if existing and existing.id != user.id:
        send_message(chat_id,
            "⚠️ This Telegram account is already linked to another LSAMS user. "
            "Ask your supervisor to unlink it first."
        )
        return

    user.telegram_chat_id = str(chat_id)
    db.session.commit()

    send_message(chat_id,
        f"✅ *Linked!* Welcome, {user.display_name}!\n\n"
        "You can now log visits by sending a message like:\n"
        "_\"Visited Chokorean Online — interested, will call next week\"_\n\n"
        "Or send a *voice note* — I'll transcribe it automatically! 🎙️\n\n"
        "Type *help* to see all commands."
    )


# ── Main handler ─────────────────────────────────────────────────────────────

def handle_update(data: dict):
    """Process a Telegram webhook update."""
    from models import db, Visit, Lead
    from whatsapp import parse_visit_message, find_lead  # reuse existing parsers

    try:
        message = data.get('message') or data.get('edited_message')
        if not message:
            return  # callback query or other update type — ignore

        chat_id  = message['chat']['id']
        msg_type = 'text' if 'text' in message else ('voice' if 'voice' in message else 'other')

        # ── /start registration ───────────────────────────────────────────────
        if msg_type == 'text':
            text = message['text'].strip()
            if text.lower().startswith('/start'):
                _handle_start(chat_id, text)
                return

        # ── Require linked account for everything else ────────────────────────
        gabay = find_gabay_by_telegram(chat_id)
        if not gabay:
            send_message(chat_id,
                "⚠️ Your Telegram is not linked to LSAMS yet.\n\n"
                "Send: `/start your_lsams_username` to link your account."
            )
            return

        # ── Voice note ────────────────────────────────────────────────────────
        if msg_type == 'voice':
            file_id = message['voice']['file_id']
            body = _transcribe_voice(file_id)
            if not body:
                send_message(chat_id,
                    "🎙️ Sorry, I couldn't understand that voice note. "
                    "Try again or type your visit instead."
                )
                return
            logger.info(f'[TG] Voice from {chat_id} transcribed: {body[:80]}')

        elif msg_type == 'text':
            body = message['text'].strip()
            if not body:
                return
        else:
            send_message(chat_id,
                "📸 I can only process text messages and voice notes right now."
            )
            return

        body_lower = body.lower()

        # ── Help command ──────────────────────────────────────────────────────
        if body_lower in ('help', 'tulong', '?', '/help', 'commands'):
            send_message(chat_id,
                "📋 *LSAMS Bot — Commands*\n\n"
                "🎙️ *Log a visit (text or voice note):*\n"
                "_\"Visited Chokorean Online — interested, call next week\"_\n"
                "_\"Pumunta sa Jollibee Store — ayaw niya\"_\n"
                "Voice notes work the same — just speak naturally!\n\n"
                "📊 *Quick commands:*\n"
                "• *status* — your lead summary\n"
                "• *today* — today's visits\n"
                "• *help* — this menu\n\n"
                "💡 *Tips:*\n"
                "• Works offline — send the message later when you have signal\n"
                "• Say the seller name clearly first, then the outcome\n"
                "• Outcomes: interested · not interested · not home · callback · registered"
            )
            return

        # ── Status command ────────────────────────────────────────────────────
        if body_lower in ('status', 'stats', 'summary', '/status'):
            from models import func
            from datetime import date
            today = date.today()
            total        = Lead.query.filter_by(gabay_id=gabay.id).count()
            live         = Lead.query.filter_by(gabay_id=gabay.id, status='live').count()
            visits_today = Visit.query.filter(
                Visit.gabay_id == gabay.id,
                func.date(Visit.visited_at) == today
            ).count()
            send_message(chat_id,
                f"📊 *Your LSAMS Summary*\n"
                f"👤 {gabay.display_name}\n"
                f"📋 Leads assigned: {total}\n"
                f"✅ Live sellers: {live}\n"
                f"📍 Visits today: {visits_today}"
            )
            return

        # ── Today command ─────────────────────────────────────────────────────
        if body_lower in ('today', 'visits today', 'ngayon', '/today'):
            from models import func
            from datetime import date
            today  = date.today()
            visits = Visit.query.filter(
                Visit.gabay_id == gabay.id,
                func.date(Visit.visited_at) == today
            ).all()
            if not visits:
                send_message(chat_id, "📍 No visits logged today yet.")
                return
            lines = [f"📍 *Today's Visits ({len(visits)})*"]
            for v in visits:
                lead = Lead.query.get(v.lead_id)
                name = lead.seller_name if lead else '?'
                lines.append(f"• {name} — {v.outcome or 'no outcome'}")
            send_message(chat_id, '\n'.join(lines))
            return

        # ── Visit logging ─────────────────────────────────────────────────────
        parsed         = parse_visit_message(body)
        seller_name    = parsed.get('seller_name')
        outcome        = parsed.get('outcome', 'follow_up')
        notes          = parsed.get('notes', body)
        follow_up_days = parsed.get('follow_up_days')

        lead, match_score = find_lead(seller_name, gabay.id)

        if lead is None:
            assigned = Lead.query.filter_by(gabay_id=gabay.id).limit(5).all()
            names    = '\n'.join(f"• {l.seller_name}" for l in assigned)
            shown    = f'"{seller_name}"' if seller_name else 'a seller name'
            send_message(chat_id,
                f"🔍 Couldn't find {shown} in your leads.\n\n"
                f"Your recent leads:\n{names}\n\n"
                f"Try: _\"Visited [exact seller name] — [outcome]\"_"
            )
            return

        follow_up_date = None
        if follow_up_days:
            follow_up_date = (datetime.utcnow() + timedelta(days=follow_up_days)).date()

        visit = Visit(
            lead_id=lead.id,
            gabay_id=gabay.id,
            visited_at=datetime.utcnow(),
            outcome=outcome,
            notes=f"[Telegram] {notes}",
            follow_up_date=follow_up_date,
            gps_address='Logged via Telegram',
        )
        db.session.add(visit)

        STATUS_UPGRADE = {
            'interested': 'negotiation',
            'callback':   'attempting',
            'follow_up':  'attempting',
            'registered': 'registration',
        }
        new_status = STATUS_UPGRADE.get(outcome)
        if new_status:
            status_order = ['pool', 'assigned', 'attempting', 'negotiation', 'registration', 'live']
            current_idx  = status_order.index(lead.status) if lead.status in status_order else 0
            new_idx      = status_order.index(new_status)
            if new_idx > current_idx:
                lead.status = new_status

        db.session.commit()

        # Notify managers
        try:
            from app import _notify_managers_telegram
            oc_emoji = {
                'interested': '🟢', 'not_interested': '🔴', 'callback': '🔵',
                'follow_up': '🟡', 'not_home': '⚪', 'rejected': '🔴', 'registered': '✅',
            }.get(outcome, '📋')
            status_line = f"\n📊 Lead status → *{lead.status_label}*" if new_status else ''
            _notify_managers_telegram(
                f"{oc_emoji} *Visit via Telegram*\n"
                f"👤 Agent: {gabay.full_name}\n"
                f"🏪 Seller: {lead.seller_name}\n"
                f"📋 Outcome: {outcome.replace('_', ' ').title()}"
                f"{status_line}"
            )
        except Exception as _e:
            logger.warning(f'[TG] Manager notify failed: {_e}')

        # Confirmation reply
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
            conf += f"\n_(Matched to \"{lead.seller_name}\" — {int(match_score * 100)}% confident)_"
        conf += "\n\nReply *status* to see your summary or *help* for commands."

        send_message(chat_id, conf)

    except Exception as e:
        logger.error(f'[TG] handle_update error: {e}', exc_info=True)
