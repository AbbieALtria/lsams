"""
LSAMS Pipeline Import Script
Reads pipline_lazada_gabay.xlsx and:
  1. Updates lead statuses from the 'Details' column
  2. Assigns leads to gabay agents by PIC name
  3. Creates one backfill Visit record per lead with Visit > 0

Usage:
    Set DATABASE_URL env var to your Railway PostgreSQL URL, then run:
        python import_pipeline.py

    Or pass it inline:
        DATABASE_URL="postgresql://..." python import_pipeline.py
"""

import os
import sys
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from datetime import datetime, date

XLSX = "pipline_lazada_gabay.xlsx"

# ── Status mapping Excel → DB ────────────────────────────────────────────────
STATUS_MAP = {
    "Assigned":               "assigned",
    "Attempting to Contact":  "attempting",
    "Negotiation":            "negotiation",
    "Registration":           "registration",
    "Live":                   "live",
    "Matched":                "matched",
    "Closed":                 "closed",
}

# ── Outcome for backfill visits ──────────────────────────────────────────────
def details_to_outcome(details):
    m = {
        "Negotiation":           "interested",
        "Attempting to Contact": "follow_up",
        "Registration":          "registered",
        "Live":                  "registered",
        "Matched":               "registered",
        "Assigned":              "follow_up",
        "Closed":                "not_interested",
    }
    return m.get(details, "follow_up")


def get_db_url():
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("ERROR: DATABASE_URL environment variable is not set.")
        print()
        print("How to run this script:")
        print('  Windows PowerShell:')
        print('    $env:DATABASE_URL="postgresql://user:pass@host/db"')
        print('    python import_pipeline.py')
        print()
        print("You can copy the DATABASE_URL from your Railway project:")
        print("  Railway → your project → Variables → DATABASE_URL")
        sys.exit(1)
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


def main():
    db_url = get_db_url()

    print(f"Reading {XLSX}…")
    df = pd.read_excel(XLSX, header=1)

    # Normalise column names
    df.columns = [str(c).strip().replace("\n", " ") for c in df.columns]

    # Rename the messy date column
    for col in df.columns:
        if "Last Date" in col:
            df.rename(columns={col: "last_date"}, inplace=True)
            break

    # Keep only rows with a valid Leads ID (UUID)
    df = df[df["Leads ID"].notna() & df["Leads ID"].str.len().gt(10)].copy()
    print(f"  {len(df)} leads found in Excel")

    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    cur = conn.cursor()

    # ── Load gabay user map  name.upper() → id ──────────────────────────────
    cur.execute("SELECT id, full_name FROM users WHERE role='gabay'")
    gabay_map = {row[1].upper(): row[0] for row in cur.fetchall()}
    print(f"  {len(gabay_map)} gabay agents in DB: {list(gabay_map.keys())}")

    # ── Load existing leads lazada_id → (db_id, current_status, gabay_id) ───
    cur.execute("SELECT id, lazada_id, status, gabay_id FROM leads WHERE lazada_id IS NOT NULL")
    existing = {row[1]: (row[0], row[2], row[3]) for row in cur.fetchall()}
    print(f"  {len(existing)} leads already in DB with lazada_id")

    # ── Statistics ───────────────────────────────────────────────────────────
    updated_status = 0
    assigned_gabay = 0
    new_leads = 0
    visits_created = 0
    skipped = 0

    for _, row in df.iterrows():
        lid = str(row["Leads ID"]).strip()
        pic = str(row.get("PIC", "")).strip().upper() if pd.notna(row.get("PIC")) else ""
        details = str(row.get("Details", "")).strip() if pd.notna(row.get("Details")) else ""
        db_status = STATUS_MAP.get(details)
        visit_count = row.get("Visit")
        visit_count = int(visit_count) if pd.notna(visit_count) and visit_count > 0 else 0
        remarks = str(row.get("Remarks.1", "")).strip() if pd.notna(row.get("Remarks.1")) else ""
        next_steps = str(row.get("Next Steps", "")).strip() if pd.notna(row.get("Next Steps")) else ""
        last_date = row.get("last_date")
        if pd.notna(last_date):
            if hasattr(last_date, "date"):
                last_date = last_date.date()
        else:
            last_date = date.today()

        shop_name = str(row.get("Shop Name", "")).strip() if pd.notna(row.get("Shop Name")) else ""
        gabay_id = gabay_map.get(pic)

        if lid in existing:
            db_id, cur_status, cur_gabay = existing[lid]

            # Update status if changed
            if db_status and db_status != cur_status:
                cur.execute(
                    "UPDATE leads SET status=%s WHERE id=%s",
                    (db_status, db_id)
                )
                updated_status += 1

            # Assign gabay if not yet assigned
            if gabay_id and cur_gabay is None:
                cur.execute(
                    "UPDATE leads SET gabay_id=%s, assigned_at=NOW() WHERE id=%s",
                    (gabay_id, db_id)
                )
                assigned_gabay += 1

        else:
            # Lead not in DB — insert it
            category = str(row.get("Category", "")).strip() if pd.notna(row.get("Category")) else None
            barangay = str(row.get("Barangay", "")).strip() if pd.notna(row.get("Barangay")) else None
            city = str(row.get("City", "")).strip() if pd.notna(row.get("City")) else None
            province = str(row.get("Province", "")).strip() if pd.notna(row.get("Province")) else None
            email = str(row.get("Email Address", "")).strip() if pd.notna(row.get("Email Address")) else None
            project = str(row.get("Project", "")).strip() if pd.notna(row.get("Project")) else None
            priority = str(row.get("Priority", "")).strip() if pd.notna(row.get("Priority")) else None

            cur.execute("""
                INSERT INTO leads
                  (lazada_id, seller_name, category, barangay, city, province,
                   email, batch_ref, priority_tier, status, gabay_id, assigned_at, imported_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                RETURNING id
            """, (
                lid, shop_name, category, barangay, city, province,
                email if email not in ("0", "") else None,
                project, priority,
                db_status or "assigned",
                gabay_id,
                datetime.now() if gabay_id else None,
            ))
            db_id = cur.fetchone()[0]
            existing[lid] = (db_id, db_status or "assigned", gabay_id)
            new_leads += 1

        # ── Create backfill visit ────────────────────────────────────────────
        if visit_count > 0 and gabay_id:
            # Check if there's already a backfill visit for this lead
            cur.execute(
                "SELECT COUNT(*) FROM visits WHERE lead_id=%s AND gps_address='Manual entry by supervisor'",
                (db_id,)
            )
            existing_backfill = cur.fetchone()[0]
            if existing_backfill == 0:
                outcome = details_to_outcome(details)
                notes_parts = []
                if remarks:
                    notes_parts.append(remarks)
                if next_steps:
                    notes_parts.append(f"Next steps: {next_steps}")
                notes = " | ".join(notes_parts) if notes_parts else "Imported from pipeline sheet"

                visit_dt = datetime.combine(last_date, datetime.min.time().replace(hour=9))

                cur.execute("""
                    INSERT INTO visits
                      (lead_id, gabay_id, visited_at, outcome, notes,
                       gps_lat, gps_lng, gps_address)
                    VALUES (%s,%s,%s,%s,%s,NULL,NULL,'Manual entry by supervisor')
                """, (db_id, gabay_id, visit_dt, outcome, notes))
                visits_created += 1

    conn.commit()
    cur.close()
    conn.close()

    print()
    print("=" * 50)
    print("IMPORT COMPLETE")
    print(f"  New leads inserted:     {new_leads}")
    print(f"  Lead statuses updated:  {updated_status}")
    print(f"  Gabay assignments set:  {assigned_gabay}")
    print(f"  Backfill visits created:{visits_created}")
    print("=" * 50)


if __name__ == "__main__":
    main()
