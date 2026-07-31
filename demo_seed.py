"""
Simulate a full conference:
  - 5 committees configured in app_config
  - 1 president + 1 deputy per committee (chair role)
  - 15 delegates per committee
  - 3 resolutions per agenda item (9 per committee, 45 total)

Run: python3 demo_seed.py
All accounts use password: Demo@1234
"""
import json
import sqlite3
import sys

from lib.auth import generate_login_code, hash_password
from lib.db import DB_PATH, init_db

PASSWORD = "Demo@1234"

# ── Committee definitions (mirrors _DEF_COM_INFO in app.py) ─────────────────
COMMITTEES = [
    {
        "code": "UNIDO",
        "president":       ("unido_president", "Damla Çakır"),
        "deputy":          ("unido_deputy",    "Ada Keskin"),
        "agenda_items": [
            "Strengthening Industrial Infrastructure and Energy Resilience in Samoa",
            "Curbing the Setback of Indonesia's Manufacturing Sector",
            "Facilitating the Transition From Fossil Fuels to Diversified Industrial Development in Brunei",
        ],
        "delegates": [
            ("United States", "unido_del_usa"),
            ("China",         "unido_del_chn"),
            ("Germany",       "unido_del_deu"),
            ("Brazil",        "unido_del_bra"),
            ("India",         "unido_del_ind"),
            ("Japan",         "unido_del_jpn"),
            ("South Korea",   "unido_del_kor"),
            ("Mexico",        "unido_del_mex"),
            ("Turkey",        "unido_del_tur"),
            ("Indonesia",     "unido_del_idn"),
            ("Nigeria",       "unido_del_nga"),
            ("Australia",     "unido_del_aus"),
            ("Canada",        "unido_del_can"),
            ("France",        "unido_del_fra"),
            ("Argentina",     "unido_del_arg"),
        ],
        "resolutions": [
            # agenda_item_index, title, status, in_debate
            (0, "Renewable Energy Development in Pacific Small Island Developing States",     "pending", 1),
            (0, "Financial Mechanisms for Industrial Infrastructure Investment in Samoa",      "pending", 0),
            (0, "Technology Transfer Frameworks for Industrial Resilience in the Pacific",     "debated", 0),
            (1, "Trade Policy Reform to Support Indonesian Manufacturing Competitiveness",     "pending", 1),
            (1, "Digital Skills Training for Workers in Indonesia's Manufacturing Sector",     "pending", 0),
            (1, "SME Support Programs and Access to Capital for Indonesian Manufacturers",     "debated", 0),
            (2, "Economic Diversification Through Green Industries in Brunei Darussalam",      "pending", 1),
            (2, "International Partnerships for Clean Energy Transition in Fossil Fuel States","pending", 0),
            (2, "Retraining and Social Protection for Fossil Fuel Workers in Brunei",         "debated", 0),
        ],
    },
    {
        "code": "UNHCR",
        "president":       ("unhcr_president", "Doruk Ege Özgülşen"),
        "deputy":          ("unhcr_deputy",    "Mete Cem Utku"),
        "agenda_items": [
            "Tackling the Maltreatment of Asylum Seekers in Malaysia",
            "Addressing the Impact of the Rohingya Refugee Crisis on Bangladesh",
            "Reducing the Impact of Violence on Displaced Populations Resulting from the West Papua Conflict",
        ],
        "delegates": [
            ("United Kingdom", "unhcr_del_gbr"),
            ("Russia",         "unhcr_del_rus"),
            ("Egypt",          "unhcr_del_egy"),
            ("Ethiopia",       "unhcr_del_eth"),
            ("Pakistan",       "unhcr_del_pak"),
            ("Bangladesh",     "unhcr_del_bgd"),
            ("Iran",           "unhcr_del_irn"),
            ("Jordan",         "unhcr_del_jor"),
            ("Kenya",          "unhcr_del_ken"),
            ("Colombia",       "unhcr_del_col"),
            ("Venezuela",      "unhcr_del_ven"),
            ("Thailand",       "unhcr_del_tha"),
            ("Malaysia",       "unhcr_del_mys"),
            ("South Africa",   "unhcr_del_zaf"),
            ("Netherlands",    "unhcr_del_nld"),
        ],
        "resolutions": [
            (0, "Establishing Legal Protections for Asylum Seekers Detained in Malaysia",              "pending", 1),
            (0, "Regional Framework for Processing Asylum Claims in Southeast Asia",                   "pending", 0),
            (0, "Access to Legal Counsel and Fair Hearings for Asylum Seekers in Malaysia",            "debated", 0),
            (1, "Sustainable Funding for Rohingya Refugee Camps in Cox's Bazar",                       "pending", 1),
            (1, "Regional Burden-Sharing Mechanisms for the Rohingya Crisis",                          "pending", 0),
            (1, "Voluntary Repatriation and Safe Return Conditions for Rohingya Refugees",             "debated", 0),
            (2, "Protection of Civilians and Displaced Persons in the West Papua Conflict Zone",       "pending", 1),
            (2, "Humanitarian Corridors and Access for Aid Organizations in West Papua",               "pending", 0),
            (2, "Accountability Mechanisms for Violence Against Displaced Populations in West Papua",  "debated", 0),
        ],
    },
    {
        "code": "OHCHR",
        "president":       ("ohchr_president", "Bahri Çağrı Toygar"),
        "deputy":          ("ohchr_deputy",    "Derin Halatçı"),
        "agenda_items": [
            "Promoting Freedom of Expression in the Philippines",
            "Protecting the Rights of Displaced Domestic Workers in Post-Coup Myanmar",
            "Upholding Human Rights Principles in China's Xinjiang Region",
        ],
        "delegates": [
            ("Sweden",       "ohchr_del_swe"),
            ("Italy",        "ohchr_del_ita"),
            ("Spain",        "ohchr_del_esp"),
            ("Poland",       "ohchr_del_pol"),
            ("Philippines",  "ohchr_del_phl"),
            ("Vietnam",      "ohchr_del_vnm"),
            ("Morocco",      "ohchr_del_mar"),
            ("Tunisia",      "ohchr_del_tun"),
            ("Chile",        "ohchr_del_chl"),
            ("Peru",         "ohchr_del_per"),
            ("Ghana",        "ohchr_del_gha"),
            ("Norway",       "ohchr_del_nor"),
            ("Denmark",      "ohchr_del_dnk"),
            ("Portugal",     "ohchr_del_prt"),
            ("Greece",       "ohchr_del_grc"),
        ],
        "resolutions": [
            (0, "Decriminalizing Criticism of Government Officials and Public Figures in the Philippines", "pending", 1),
            (0, "Protection of Journalists and Online Activists Under the Philippines' Anti-Terror Law",   "pending", 0),
            (0, "Independent Monitoring Mechanisms for Press Freedom Violations in the Philippines",       "debated", 0),
            (1, "Legal Status and Labour Protections for Displaced Domestic Workers in Post-Coup Myanmar", "pending", 1),
            (1, "Bilateral Agreements for the Safe Return of Migrant Domestic Workers from Myanmar",       "pending", 0),
            (1, "International Fund for Myanmar Displaced Workers' Rehabilitation and Reintegration",      "debated", 0),
            (2, "Independent Investigation into Human Rights Conditions in China's Xinjiang Region",       "pending", 1),
            (2, "Accountability for Reported Forced Labour and Detention Practices in Xinjiang",           "pending", 0),
            (2, "Cultural and Religious Rights Protections for Uyghur and Other Minority Communities",     "debated", 0),
        ],
    },
    {
        "code": "UNDPPA",
        "president":       ("undppa_president", "Sanem Naz Kafalı"),
        "deputy":          ("undppa_deputy",    "Berke Ballıel"),
        "agenda_items": [
            "Mediating the Sovereignty Dispute in the Spratly Islands",
            "Facilitating Post-Conflict Reconciliation in the Philippines' Bangsamoro Region",
            "Assessing the Expansion of State Surveillance in Hong Kong",
        ],
        "delegates": [
            ("UAE",            "undppa_del_are"),
            ("Saudi Arabia",   "undppa_del_sau"),
            ("Qatar",          "undppa_del_qat"),
            ("Israel",         "undppa_del_isr"),
            ("Lebanon",        "undppa_del_lbn"),
            ("Iraq",           "undppa_del_irq"),
            ("Algeria",        "undppa_del_dza"),
            ("Libya",          "undppa_del_lby"),
            ("Myanmar",        "undppa_del_mmr"),
            ("Singapore",      "undppa_del_sgp"),
            ("New Zealand",    "undppa_del_nzl"),
            ("Czech Republic", "undppa_del_cze"),
            ("Romania",        "undppa_del_rou"),
            ("Hungary",        "undppa_del_hun"),
            ("Austria",        "undppa_del_aut"),
        ],
        "resolutions": [
            (0, "Multilateral Dialogue Framework for the Peaceful Resolution of Spratly Islands Claims",     "pending", 1),
            (0, "Code of Conduct for Claimant States in the South China Sea Territorial Dispute",            "pending", 0),
            (0, "Confidence-Building Measures to Reduce Military Tensions in the Spratly Islands",           "debated", 0),
            (1, "Inclusive Peace Process and Power-Sharing Mechanisms for the Bangsamoro Region",            "pending", 1),
            (1, "International Support for Economic Development and Reconciliation in Bangsamoro",           "pending", 0),
            (1, "Disarmament, Demobilization, and Reintegration Program for Former Combatants in Mindanao",  "debated", 0),
            (2, "UN Review of Legislative Changes Affecting Civil Liberties and Autonomy in Hong Kong",      "pending", 1),
            (2, "Protection of the Right to Peaceful Assembly and Free Expression in Hong Kong",             "pending", 0),
            (2, "Monitoring Mechanism for the Implementation of the Sino-British Joint Declaration",         "debated", 0),
        ],
    },
    {
        "code": "UNESCO",
        "president":       ("unesco_president", "Can Kuzey Güner"),
        "deputy":          ("unesco_deputy",    "Defne Erdoğan"),
        "agenda_items": [
            "Upholding the Cultural Heritage of Nomadic Communities in Mongolia",
            "Improving Equitable Access to Education in Pacific Island Nations",
            "Preventing the Politicization of Cultural Sites in Contested East Asian Territories",
        ],
        "delegates": [
            ("Ukraine",      "unesco_del_ukr"),
            ("Mongolia",     "unesco_del_mng"),
            ("Cambodia",     "unesco_del_khm"),
            ("Bolivia",      "unesco_del_bol"),
            ("Ecuador",      "unesco_del_ecu"),
            ("Paraguay",     "unesco_del_pry"),
            ("Uganda",       "unesco_del_uga"),
            ("Tanzania",     "unesco_del_tza"),
            ("Mozambique",   "unesco_del_moz"),
            ("Zimbabwe",     "unesco_del_zwe"),
            ("Nepal",        "unesco_del_npl"),
            ("Sri Lanka",    "unesco_del_lka"),
            ("Cuba",         "unesco_del_cub"),
            ("Panama",       "unesco_del_pan"),
            ("Costa Rica",   "unesco_del_cri"),
        ],
        "resolutions": [
            (0, "Safeguarding the Intangible Cultural Heritage of Mongolian Nomadic Communities",           "pending", 1),
            (0, "Land Rights and Cultural Preservation for Nomadic Peoples Facing Sedentarization",         "pending", 0),
            (0, "Digital Documentation and Transmission of Nomadic Cultural Practices in Mongolia",         "debated", 0),
            (1, "Distance Learning Infrastructure and Connectivity for Pacific Island Education Systems",   "pending", 1),
            (1, "Culturally Responsive Curriculum Development for Pacific Island Nations",                  "pending", 0),
            (1, "Teacher Training and Retention Programs for Remote Pacific Island Communities",            "debated", 0),
            (2, "Guidelines for the Apolitical Management of UNESCO World Heritage Sites in East Asia",     "pending", 1),
            (2, "Dispute Resolution Mechanism for Competing Cultural Claims Over Shared Heritage Sites",    "pending", 0),
            (2, "International Standards for the Preservation of Cultural Sites in Contested Territories",  "debated", 0),
        ],
    },
]


def main() -> int:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    pw = hash_password(PASSWORD)

    # ── 1. Build and store app_config committees block ───────────────────────
    row = conn.execute("SELECT data FROM app_config WHERE id = 1").fetchone()
    cfg = json.loads(row["data"]) if row else {}
    cfg.setdefault("schools", {})
    cfg.setdefault("conference", {})
    cfg.setdefault("upload_permission_minutes", 15)
    cfg.setdefault("schedule", [])
    cfg["committees"] = [
        {"code": c["code"], "agenda_items": c["agenda_items"]}
        for c in COMMITTEES
    ]
    if row:
        conn.execute(
            "UPDATE app_config SET data = ?, updated_at = datetime('now') WHERE id = 1",
            (json.dumps(cfg),),
        )
    else:
        conn.execute(
            "INSERT INTO app_config (id, data, updated_at) VALUES (1, ?, datetime('now'))",
            (json.dumps(cfg),),
        )
    print("✓ app_config updated with 5 committees")

    # ── 2. Create chairs and delegates ───────────────────────────────────────
    user_ids = {}   # username -> id
    skipped = 0

    for c in COMMITTEES:
        code = c["code"]

        # President
        uname, dname = c["president"]
        try:
            conn.execute(
                "INSERT INTO users (username, display_name, password_hash, role, committee, login_code) "
                "VALUES (?, ?, ?, 'chair', ?, ?)",
                (uname, dname, pw, code, generate_login_code()),
            )
            uid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            user_ids[uname] = uid
            print(f"  + chair  {uname} ({code} President)")
        except sqlite3.IntegrityError:
            uid = conn.execute("SELECT id FROM users WHERE username=?", (uname,)).fetchone()["id"]
            user_ids[uname] = uid
            skipped += 1

        # Deputy
        uname, dname = c["deputy"]
        try:
            conn.execute(
                "INSERT INTO users (username, display_name, password_hash, role, committee, login_code) "
                "VALUES (?, ?, ?, 'chair', ?, ?)",
                (uname, dname, pw, code, generate_login_code()),
            )
            uid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            user_ids[uname] = uid
            print(f"  + chair  {uname} ({code} Deputy)")
        except sqlite3.IntegrityError:
            uid = conn.execute("SELECT id FROM users WHERE username=?", (uname,)).fetchone()["id"]
            user_ids[uname] = uid
            skipped += 1

        # Delegates
        for delegation, uname in c["delegates"]:
            display = f"{delegation} ({code})"
            try:
                conn.execute(
                    "INSERT INTO users (username, display_name, password_hash, role, committee, delegation, login_code) "
                    "VALUES (?, ?, ?, 'delegate', ?, ?, ?)",
                    (uname, display, pw, code, delegation, generate_login_code()),
                )
                uid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                user_ids[uname] = uid
            except sqlite3.IntegrityError:
                uid = conn.execute("SELECT id FROM users WHERE username=?", (uname,)).fetchone()["id"]
                user_ids[uname] = uid
                skipped += 1

        print(f"  + 15 delegates for {code}")

    # ── 3. Create resolutions ────────────────────────────────────────────────
    doc_count = 0
    for c in COMMITTEES:
        code = c["code"]
        # Use the president as uploader for all resolutions in this committee
        uploader_uname = c["president"][0]
        uploader_id = user_ids[uploader_uname]

        for ai_idx, title, status, in_debate in c["resolutions"]:
            agenda_item = c["agenda_items"][ai_idx]
            conn.execute(
                """
                INSERT INTO documents
                    (title, committee, agenda_item, status, in_debate, approved,
                     uploader_id, size_bytes, created_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, 0, datetime('now'))
                """,
                (title, code, agenda_item, status, in_debate, uploader_id),
            )
            doc_count += 1

    print(f"✓ {doc_count} resolutions created")

    conn.commit()
    conn.close()

    print()
    print("Demo conference seeded successfully.")
    print(f"  Skipped {skipped} already-existing users.")
    print(f"  All accounts: password = {PASSWORD}")
    print()
    print("Sample logins:")
    for c in COMMITTEES:
        print(f"  {c['code']:8s}  president: {c['president'][0]:22s}  deputy: {c['deputy'][0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
