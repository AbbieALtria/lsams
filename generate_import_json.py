"""
Generate data_export.json from pipline_lazada_gabay.xlsx
for upload at /admin/import-data on Railway.

Usage:
    python generate_import_json.py

Outputs: data_export.json (upload this file at /admin/import-data)
"""

import json
import pandas as pd
from datetime import datetime, date

XLSX = "pipline_lazada_gabay.xlsx"

STATUS_MAP = {
    "Assigned":               "assigned",
    "Attempting to Contact":  "attempting",
    "Negotiation":            "negotiation",
    "Registration":           "registration",
    "Live":                   "live",
    "Matched":                "matched",
    "Closed":                 "closed",
}

# PIC name → gabay username (must match what's already in Railway DB)
# These will be matched by username when imported
PIC_TO_USERNAME = {
    "ARVIE":     "arvie",
    "ELLEN":     "ellen",
    "JENEROUS":  "jenerous",
    "KAREN":     "karen",
    "JENICA":    "jenica",
    "MARIECRIS": "mariecris",
    "ABI":       "abi",
    "KARL":      "karl",
    "KAYCEE":    "kaycee",
}

def outcome_from_status(details):
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


def main():
    print(f"Reading {XLSX}…")
    df = pd.read_excel(XLSX, header=1)
    df.columns = [str(c).strip().replace("\n", " ") for c in df.columns]

    for col in df.columns:
        if "Last Date" in col:
            df.rename(columns={col: "last_date"}, inplace=True)
            break

    df = df[df["Leads ID"].notna() & df["Leads ID"].str.len().gt(10)].copy()
    print(f"  {len(df)} leads in Excel")

    leads_out = []
    visits_out = []

    # Fake user IDs — the import route maps by username, so we use placeholder IDs
    # that map to the usernames above. The actual DB IDs will be resolved server-side.
    pic_fake_id = {pic: idx + 100 for idx, pic in enumerate(PIC_TO_USERNAME)}

    # Build fake user list so the importer's user_map works
    users_out = []
    for pic, username in PIC_TO_USERNAME.items():
        users_out.append({
            "id": pic_fake_id[pic],
            "username": username,
            "full_name": pic.title(),
            "email": f"{username}@lsams.local",
            "role": "gabay",
            "password_hash": "",        # won't overwrite existing — importer skips existing usernames
            "assigned_city": None,
            "is_active": True,
        })

    lead_id_counter = 10000

    for _, row in df.iterrows():
        lid_excel = str(row["Leads ID"]).strip()
        pic = str(row.get("PIC", "")).strip().upper() if pd.notna(row.get("PIC")) else ""
        details = str(row.get("Details", "")).strip() if pd.notna(row.get("Details")) else ""
        db_status = STATUS_MAP.get(details, "assigned")

        shop_name   = str(row.get("Shop Name", "")).strip() if pd.notna(row.get("Shop Name")) else "Unknown"
        category    = str(row.get("Category", "")).strip() if pd.notna(row.get("Category")) else None
        barangay    = str(row.get("Barangay", "")).strip() if pd.notna(row.get("Barangay")) else None
        city        = str(row.get("City", "")).strip() if pd.notna(row.get("City")) else None
        province    = str(row.get("Province", "")).strip() if pd.notna(row.get("Province")) else None
        email       = str(row.get("Email Address", "")).strip() if pd.notna(row.get("Email Address")) else None
        contact     = str(row.get("Contact Number", "")).strip() if pd.notna(row.get("Contact Number")) else None
        project     = str(row.get("Project", "")).strip() if pd.notna(row.get("Project")) else None
        cluster     = str(row.get("Cluster", "")).strip() if pd.notna(row.get("Cluster")) else None
        priority    = str(row.get("Priority", "")).strip() if pd.notna(row.get("Priority")) else None
        link        = str(row.get("Link", "")).strip() if pd.notna(row.get("Link")) else None
        remarks     = str(row.get("Remarks.1", "")).strip() if pd.notna(row.get("Remarks.1")) else None
        next_steps  = str(row.get("Next Steps", "")).strip() if pd.notna(row.get("Next Steps")) else None

        address_parts = [p for p in [barangay, city, province] if p]
        address = ", ".join(address_parts) if address_parts else None

        gabay_fake_id = pic_fake_id.get(pic)
        last_date = row.get("last_date")
        assigned_at = None
        if pd.notna(last_date) and gabay_fake_id:
            assigned_at = pd.Timestamp(last_date).isoformat()

        lead_id = lead_id_counter
        lead_id_counter += 1

        notes_parts = []
        if remarks:
            notes_parts.append(remarks)
        if next_steps:
            notes_parts.append(f"Next steps: {next_steps}")

        leads_out.append({
            "id": lead_id,
            "seller_name": shop_name,
            "contact_number": contact if contact not in ("0", "None", "") else None,
            "city": city,
            "category": category,
            "status": db_status,
            "gabay_id": gabay_fake_id,
            "address": address,
            "link": link,
            "notes": " | ".join(notes_parts) if notes_parts else None,
            "project": project,
            "cluster": cluster,
            "priority_tier": priority,
            "lazada_id": lid_excel,
            "assigned_at": assigned_at,
            "imported_at": datetime.utcnow().isoformat(),
        })

        # Create visit if Visit > 0
        visit_count = row.get("Visit")
        if pd.notna(visit_count) and float(visit_count) > 0 and gabay_fake_id:
            visit_dt = pd.Timestamp(last_date).isoformat() if pd.notna(last_date) else datetime.utcnow().isoformat()
            visits_out.append({
                "lead_id": lead_id,
                "gabay_id": gabay_fake_id,
                "visited_at": visit_dt,
                "outcome": outcome_from_status(details),
                "notes": " | ".join(notes_parts) if notes_parts else "Imported from pipeline sheet",
                "gps_lat": None,
                "gps_lng": None,
                "gps_address": "Manual entry by supervisor",
                "follow_up_date": None,
                "photos": None,
            })

    output = {
        "users": users_out,
        "leads": leads_out,
        "visits": visits_out,
    }

    with open("data_export.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)

    print(f"\ndata_export.json created:")
    print(f"  Users (gabay agents): {len(users_out)}")
    print(f"  Leads:                {len(leads_out)}")
    print(f"  Visits:               {len(visits_out)}")
    print()
    print("Next step:")
    print("  1. Go to https://web-production-c9ec2.up.railway.app/admin/import-data")
    print("  2. Log in as superadmin")
    print("  3. Upload data_export.json")
    print("  4. Click 'Import All Data'")


if __name__ == "__main__":
    main()
