"""
LSAMS Lead Scoring ML Engine
Logistic regression trained on actual conversion data from the DB.
Falls back gracefully when insufficient data.

Minimum to train: MIN_POSITIVE leads with status='live'.
When available, each Lead gets an ml_score (0–100) stored on the DB row.
The conversion_score property blends ML (70%) + rules (30%).
"""

import os
import json
import pickle
import logging
from datetime import datetime

MIN_POSITIVE = 20   # minimum live leads before we attempt ML training
MODEL_DIR    = os.path.join(os.path.dirname(__file__), 'ml_models')
MODEL_PATH   = os.path.join(MODEL_DIR, 'lead_score_model.pkl')

logger = logging.getLogger(__name__)


# ── Feature extraction ────────────────────────────────────────────────────────

def _outcome_score(visits):
    """Weighted visit outcome score from last 5 visits."""
    pts = {
        'interested': 10, 'callback': 8, 'follow_up': 5,
        'not_home': 2, 'rejected': -15, 'not_interested': -15, 'registered': 12,
    }
    total = 0.0
    for i, v in enumerate(visits[:5]):
        weight = 1.0 - i * 0.15
        total += pts.get(v.outcome or '', 0) * weight
    return max(-20, min(25, total))


HIGH_CONV = {
    'beauty', 'health', 'fashion', 'clothing', 'accessories',
    'food', 'beverage', 'snacks', 'groceries', 'fmcg',
    'home', 'kitchen', 'appliances', 'electronics',
}
MEDIUM_CONV = {
    'sports', 'automotive', 'toys', 'baby', 'pet',
    'office', 'tools', 'garden',
}


def extract_features(lead):
    """
    Returns a flat feature dict for one Lead object.
    All values must be numeric (int/float).
    """
    from models import Visit

    recent_visits = lead.visits.order_by(Visit.visited_at.desc()).limit(5).all()
    visit_count   = lead.visits.count()
    lvd           = lead.last_visit_days

    tier_map = {'P0': 4, 'P1': 3, 'P2': 2, 'P3': 1}
    status_map = {
        'pool': 0, 'assigned': 1, 'attempting': 2,
        'negotiation': 3, 'registration': 4, 'live': 5,
    }

    cat_text = f"{(lead.category or '').lower()} {(lead.cluster or '').lower()}"
    cat_score = 2 if any(k in cat_text for k in HIGH_CONV) else (
                1 if any(k in cat_text for k in MEDIUM_CONV) else 0)

    last_v = lead.latest_visit
    fu_urgency = 0
    if last_v and last_v.follow_up_date:
        days = (last_v.follow_up_date - datetime.utcnow().date()).days
        fu_urgency = 3 if -3 <= days <= 1 else (2 if days < -3 else (1 if days <= 7 else 0))

    return {
        'priority_tier':   tier_map.get(lead.priority_tier or '', 0),
        'status_stage':    status_map.get(lead.status, 0),
        'visit_count':     min(visit_count, 20),
        'outcome_score':   _outcome_score(recent_visits),
        'days_since_visit': min(lvd, 90) if lvd is not None else 90,
        'never_visited':   1 if lvd is None else 0,
        'followup_urgency': fu_urgency,
        'age_days':        min(lead.age_days, 120),
        'has_contact':     1 if lead.contact_number else 0,
        'has_shop_link':   1 if lead.link else 0,
        'has_social':      1 if lead.social_media_link else 0,
        'category_score':  cat_score,
        'has_address':     1 if lead.address else 0,
        'has_city':        1 if lead.city else 0,
    }


FEATURE_NAMES = [
    'priority_tier', 'status_stage', 'visit_count', 'outcome_score',
    'days_since_visit', 'never_visited', 'followup_urgency', 'age_days',
    'has_contact', 'has_shop_link', 'has_social', 'category_score',
    'has_address', 'has_city',
]


def features_to_vector(feat_dict):
    return [feat_dict[k] for k in FEATURE_NAMES]


# ── Training ──────────────────────────────────────────────────────────────────

def train(app, run_id=None):
    """
    Train logistic regression on all leads in DB.
    Label = 1 if status in ('live', 'matched'), 0 otherwise (excluding 'pool').
    Returns a result dict with status, accuracy, auc, top_features.
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline
    from sklearn.model_selection import cross_val_score
    from sklearn.metrics import roc_auc_score
    import numpy as np

    with app.app_context():
        from models import db, Lead, MLModelRun

        # Load run record if given
        run = MLModelRun.query.get(run_id) if run_id else None

        # Build dataset — exclude 'pool' (no field contact yet)
        leads = Lead.query.filter(Lead.status != 'pool').all()
        X, y = [], []
        for lead in leads:
            label = 1 if lead.status in ('live', 'matched') else 0
            X.append(features_to_vector(extract_features(lead)))
            y.append(label)

        import numpy as np
        X = np.array(X, dtype=float)
        y = np.array(y)

        n_pos = int(y.sum())
        n_total = len(y)
        logger.info(f'ML train: {n_total} samples, {n_pos} positive (live/matched)')

        if n_pos < MIN_POSITIVE:
            msg = (f'Only {n_pos} live leads — need {MIN_POSITIVE} to train. '
                   f'Using rule-based scores only.')
            logger.warning(msg)
            if run:
                run.status = 'insufficient_data'
                run.n_samples = n_total
                run.n_positive = n_pos
                run.notes = msg
                db.session.commit()
            return {'status': 'insufficient_data', 'n_positive': n_pos,
                    'needed': MIN_POSITIVE, 'message': msg}

        # Train with cross-validation
        model = Pipeline([
            ('scaler', StandardScaler()),
            ('clf', LogisticRegression(max_iter=500, class_weight='balanced', C=1.0)),
        ])

        cv_scores = cross_val_score(model, X, y, cv=min(5, n_pos), scoring='accuracy')
        accuracy  = float(cv_scores.mean())

        model.fit(X, y)
        proba = model.predict_proba(X)[:, 1]
        try:
            auc = float(roc_auc_score(y, proba))
        except Exception:
            auc = 0.0

        # Feature importance from logistic regression coefficients
        coefs = model.named_steps['clf'].coef_[0]
        top_features = sorted(
            [{'name': FEATURE_NAMES[i], 'weight': round(float(coefs[i]), 3)}
             for i in range(len(FEATURE_NAMES))],
            key=lambda x: abs(x['weight']), reverse=True
        )

        # Save model
        os.makedirs(MODEL_DIR, exist_ok=True)
        with open(MODEL_PATH, 'wb') as f:
            pickle.dump(model, f)

        # Score ALL leads and persist ml_score to DB
        all_leads = Lead.query.all()
        scored = 0
        now = datetime.utcnow()
        for lead in all_leads:
            fv = features_to_vector(extract_features(lead))
            prob = model.predict_proba([fv])[0][1]
            lead.ml_score = round(prob * 100, 1)
            lead.ml_trained_at = now
            scored += 1
        db.session.commit()

        if run:
            run.status = 'success'
            run.n_samples = n_total
            run.n_positive = n_pos
            run.accuracy = accuracy
            run.roc_auc = auc
            run.top_features = json.dumps(top_features)
            run.model_path = MODEL_PATH
            db.session.commit()

        logger.info(f'ML train complete: acc={accuracy:.2%}, auc={auc:.2f}, scored {scored} leads')

        return {
            'status': 'success',
            'n_samples': n_total,
            'n_positive': n_pos,
            'accuracy': accuracy,
            'roc_auc': auc,
            'top_features': top_features,
            'scored': scored,
        }


# ── Predict single lead (without re-training) ─────────────────────────────────

def predict_one(lead):
    """Score a single lead using the saved model. Returns 0–100 float or None."""
    if not os.path.exists(MODEL_PATH):
        return None
    try:
        with open(MODEL_PATH, 'rb') as f:
            model = pickle.load(f)
        fv = features_to_vector(extract_features(lead))
        return round(model.predict_proba([fv])[0][1] * 100, 1)
    except Exception as e:
        logger.warning(f'predict_one failed: {e}')
        return None
