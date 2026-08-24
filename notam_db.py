import os
import sqlite3
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple, Optional, Dict
from notam_logging import logger

DB_FILENAME = os.getenv("NOTAM_DB_PATH", "notams.db")

def _get_conn(db_path: Optional[str] = None):
    path = db_path or DB_FILENAME
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(db_path: Optional[str] = None) -> None:
    """Create the database and `notams` table if it doesn't exist."""
    conn = _get_conn(db_path)
    try:
        cur = conn.cursor()
        # Desired final schema: no parsed_json column; structured fields are separate
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS notams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                A TEXT, B TEXT, C TEXT, D TEXT, E TEXT, F TEXT, G TEXT,
                Q_location TEXT, Q_q_code TEXT, Q_traffic TEXT, Q_traffic_rule TEXT,
                Q_lower TEXT, Q_upper TEXT, Q_coordinates TEXT, Q_radius_nm TEXT,
                parsed_hash TEXT,
                image_generated INTEGER DEFAULT 0,
                image_generated_at TEXT
            )
            '''
        )
        conn.commit()
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS faa_activities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                mission TEXT NOT NULL,
                primary_window TEXT,
                backup_window TEXT,

                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,

                payload_hash TEXT,

                telegram_posted INTEGER DEFAULT 0,
                telegram_posted_at TEXT,
                telegram_message_id TEXT,

                UNIQUE(mission, primary_window)
            )
        """)
        conn.commit()
        
        cur.execute("""
        CREATE TABLE IF NOT EXISTS starbase_beach (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            alert_key TEXT UNIQUE NOT NULL,

            description TEXT,

            is_closed INTEGER DEFAULT 0,

            start_utc TEXT,
            end_utc TEXT,

            raw_date TEXT,
            periods_json TEXT,

            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,

            payload_hash TEXT,

            processed INTEGER DEFAULT 0,
            processed_at TEXT
        )
        """)
        conn.commit()

        cur.execute("PRAGMA table_info(starbase_beach)")
        beach_cols = [r['name'] for r in cur.fetchall()]
        if 'periods_json' not in beach_cols:
            cur.execute("ALTER TABLE starbase_beach ADD COLUMN periods_json TEXT")
            conn.commit()
        
        cur.execute("""
        CREATE TABLE IF NOT EXISTS starbase_road (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            alert_key TEXT UNIQUE NOT NULL,

            origin TEXT,
            destination TEXT,

            description TEXT,

            start_utc TEXT,
            end_utc TEXT,

            raw_date TEXT,

            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,

            payload_hash TEXT,

            processed INTEGER DEFAULT 0,
            processed_at TEXT
        )
        """)
        conn.commit()

        # If legacy parsed_json exists (older DB), migrate it into structured columns
        cur.execute("PRAGMA table_info(notams)")
        cols = [r['name'] for r in cur.fetchall()]
        if 'parsed_json' in cols:
            logger.info('Detected legacy parsed_json column; migrating data into structured columns')
            # For rows with parsed_json populate structured columns
            cur.execute("SELECT id, parsed_json FROM notams WHERE parsed_json IS NOT NULL")
            rows = cur.fetchall()
            for r in rows:
                try:
                  payload = json.loads(r['parsed_json'])
                except Exception:
                    payload = {}
                q = payload.get('Q') if isinstance(payload, dict) else None
                updates = {
                    'A': payload.get('A'), 'B': payload.get('B'), 'C': payload.get('C'),
                    'D': payload.get('D'), 'E': payload.get('E'), 'F': payload.get('F'), 'G': payload.get('G'),
                    'Q_location': q.get('location') if isinstance(q, dict) else None,
                    'Q_q_code': q.get('q_code') if isinstance(q, dict) else None,
                    'Q_traffic': q.get('traffic') if isinstance(q, dict) else None,
                    'Q_traffic_rule': q.get('traffic_rule') if isinstance(q, dict) else None,
                    'Q_lower': q.get('lower') if isinstance(q, dict) else None,
                    'Q_upper': q.get('upper') if isinstance(q, dict) else None,
                    'Q_coordinates': q.get('coordinates') if isinstance(q, dict) else None,
                    'Q_radius_nm': q.get('radius_nm') if isinstance(q, dict) else None,
                }
                set_clause = ', '.join(f"{k} = ?" for k in updates.keys())
                params = list(updates.values()) + [r['id']]
                cur.execute(f"UPDATE notams SET {set_clause} WHERE id = ?", params)

            conn.commit()

            # Recreate table to drop parsed_json column (ensure final schema)
            logger.info('Recreating notams table to drop parsed_json column')
            final_cols = [
                'id', 'name', 'created_at', 'updated_at',
                'A', 'B', 'C', 'D', 'E', 'F', 'G',
                'Q_location', 'Q_q_code', 'Q_traffic', 'Q_traffic_rule',
                'Q_lower', 'Q_upper', 'Q_coordinates', 'Q_radius_nm',
                'parsed_hash', 'image_generated', 'image_generated_at'
            ]

            cur.execute('BEGIN')
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS notams_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    A TEXT, B TEXT, C TEXT, D TEXT, E TEXT, F TEXT, G TEXT,
                    Q_location TEXT, Q_q_code TEXT, Q_traffic TEXT, Q_traffic_rule TEXT,
                    Q_lower TEXT, Q_upper TEXT, Q_coordinates TEXT, Q_radius_nm TEXT,
                    parsed_hash TEXT,
                    image_generated INTEGER DEFAULT 0,
                    image_generated_at TEXT
                )
                '''
            )
            # copy any overlapping columns
            existing_cols = cols
            cols_to_copy = [c for c in final_cols if c in existing_cols]
            cols_csv = ','.join(cols_to_copy)
            cur.execute(f"INSERT OR REPLACE INTO notams_new ({cols_csv}) SELECT {cols_csv} FROM notams")
            cur.execute('DROP TABLE notams')
            cur.execute('ALTER TABLE notams_new RENAME TO notams')
            cur.execute('COMMIT')

        # Ensure newer optional columns exist (add if missing)
        cur.execute("PRAGMA table_info(notams)")
        cols = [r['name'] for r in cur.fetchall()]
        if 'parsed_hash' not in cols:
            logger.info('Adding parsed_hash column to notams table')
            cur.execute("ALTER TABLE notams ADD COLUMN parsed_hash TEXT")
        if 'image_generated' not in cols:
            logger.info('Adding image_generated column to notams table')
            cur.execute("ALTER TABLE notams ADD COLUMN image_generated INTEGER DEFAULT 0")
        if 'image_generated_at' not in cols:
            logger.info('Adding image_generated_at column to notams table')
            cur.execute("ALTER TABLE notams ADD COLUMN image_generated_at TEXT")
        conn.commit()
    finally:
        conn.close()

def save_notam(name: str, parsed: Dict, db_path: Optional[str] = None) -> None:
    """Insert or update a NOTAM by `name`.

    Stores the full parsed dictionary as JSON and maintains `created_at` and `updated_at`.
    """
    init_db(db_path)
    now = datetime.utcnow().isoformat() + 'Z'
    # extract structured fields for columns
    def _safe_get(k):
        return parsed.get(k) if isinstance(parsed, dict) else None

    col_values = {
        'A': _safe_get('A'),
        'B': _safe_get('B'),
        'C': _safe_get('C'),
        'D': _safe_get('D'),
        'E': _safe_get('E'),
        'F': _safe_get('F'),
        'G': _safe_get('G'),
    }
    # Q subfields
    q = parsed.get('Q') if isinstance(parsed, dict) else None
    if isinstance(q, dict):
        col_values.update({
            'Q_location': q.get('location'),
            'Q_q_code': q.get('q_code'),
            'Q_traffic': q.get('traffic'),
            'Q_traffic_rule': q.get('traffic_rule'),
            'Q_lower': q.get('lower'),
            'Q_upper': q.get('upper'),
            'Q_coordinates': q.get('coordinates'),
            'Q_radius_nm': q.get('radius_nm'),
        })
    else:
        col_values.update({
            'Q_location': None, 'Q_q_code': None, 'Q_traffic': None, 'Q_traffic_rule': None,
            'Q_lower': None, 'Q_upper': None, 'Q_coordinates': None, 'Q_radius_nm': None,
        })
    # compute a stable hash of the parsed payload to detect changes
    try:
        parsed_json = json.dumps(parsed, sort_keys=True, ensure_ascii=False)
        parsed_hash = hashlib.sha256(parsed_json.encode('utf-8')).hexdigest()
    except Exception:
        parsed_hash = None

    conn = _get_conn(db_path)
    try:
        cur = conn.cursor()

        # check for existing row and its parsed_hash and structured columns
        cur.execute(
            "SELECT parsed_hash, A, B, C, D, E, F, G, Q_location, Q_q_code, Q_traffic, Q_traffic_rule, Q_lower, Q_upper, Q_coordinates, Q_radius_nm FROM notams WHERE name = ?",
            (name,)
        )
        existing = cur.fetchone()

        if existing:
            logger.info(f"Existing NOTAM found for {name}, checking for changes")
            existing_hash = existing['parsed_hash']

            # If both hashes exist and match, treat as no payload change
            if existing_hash is not None and parsed_hash is not None and existing_hash == parsed_hash:
                logger.info(f"No changes detected for {name} based on parsed_hash; skipping DB update")
            else:
                # Hash differs or one is missing: fall back to field-by-field comparison
                logger.info(f"Changes detected for {name}; updating all fields")
                changed = False
                for k in list(col_values.keys()):
                    try:
                        existing_val = existing[k]
                    except Exception:
                        existing_val = None
                    new_val = col_values.get(k)
                    if (existing_val or '').strip() != (new_val or '').strip():
                        changed = True
                        break

                if changed or existing_hash != parsed_hash:
                    # data changed: update structured columns, reset image_generated
                    logger.info(f"Effective changes detected for {name}; updating structured fields and resetting image_generated")
                    update_cols = ['updated_at'] + list(col_values.keys()) + ['parsed_hash', 'image_generated', 'image_generated_at']
                    update_set = ', '.join(f"{c} = ?" for c in update_cols)
                    update_params = [now] + [col_values[k] for k in col_values.keys()] + [parsed_hash, 0, None, name]
                    # Note: last param is name for WHERE
                    cur.execute(f"UPDATE notams SET {update_set} WHERE name = ?", update_params)
                else:
                    # No effective change, still refresh updated_at and structured fields
                    logger.info(f"No effective changes detected for {name}; refreshing updated_at and structured fields")
                    update_cols = ['updated_at'] + list(col_values.keys())
                    update_set = ', '.join(f"{c} = ?" for c in update_cols)
                    update_params = [now] + [col_values[k] for k in col_values.keys()] + [name]
                    cur.execute(f"UPDATE notams SET {update_set} WHERE name = ?", update_params)
        else:
            logger.info(f"No existing NOTAM found for {name}; inserting new record")
            # insert new with structured columns and parsed_hash; image_generated starts at 0
            insert_cols = ['name', 'created_at', 'updated_at'] + list(col_values.keys()) + ['parsed_hash', 'image_generated']
            placeholders = ','.join('?' for _ in insert_cols)
            insert_params = [name, now, now] + [col_values[k] for k in col_values.keys()] + [parsed_hash, 0]
            cur.execute(f"INSERT INTO notams ({','.join(insert_cols)}) VALUES ({placeholders})", insert_params)

        conn.commit()
    except Exception as e:
        logger.exception(f"Failed to save NOTAM to DB: {e}")
        raise
    finally:
        conn.close()

def get_notams_needing_images(db_path: Optional[str] = None) -> List[Tuple[str, Dict]]:
    """Return list of (name, parsed_dict) where image_generated == 0."""
    init_db(db_path)
    if not Path(db_path or DB_FILENAME).exists():
        return []
    conn = _get_conn(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT name, A, B, C, D, E, F, G, Q_location, Q_q_code, Q_traffic, Q_traffic_rule, Q_lower, Q_upper, Q_coordinates, Q_radius_nm FROM notams WHERE image_generated = 0 ORDER BY name"
        )
        rows = cur.fetchall()
        out = []
        for r in rows:
            parsed = {}
            for k in ('A', 'B', 'C', 'D', 'E', 'F', 'G'):
                v = r[k]
                if v is not None:
                    parsed[k] = v
            q = {}
            q_map = {
                'location': r['Q_location'], 'q_code': r['Q_q_code'], 'traffic': r['Q_traffic'],
                'traffic_rule': r['Q_traffic_rule'], 'lower': r['Q_lower'], 'upper': r['Q_upper'],
                'coordinates': r['Q_coordinates'], 'radius_nm': r['Q_radius_nm'],
            }
            for kk, vv in q_map.items():
                if vv is not None:
                    q[kk] = vv
            if q:
                parsed['Q'] = q

            out.append((r['name'], parsed))
        return out
    finally:
        conn.close()

def mark_image_generated(name: str, db_path: Optional[str] = None) -> None:
    """Mark a NOTAM as having had its image generated and recorded."""
    init_db(db_path)
    now = datetime.utcnow().isoformat() + 'Z'
    conn = _get_conn(db_path)
    try:
        cur = conn.cursor()
        cur.execute("UPDATE notams SET image_generated = 1, image_generated_at = ? WHERE name = ?", (now, name))
        conn.commit()
    finally:
        conn.close()

def load_all_notams(db_path: Optional[str] = None) -> List[Tuple[str, Dict]]:
    """Return list of (name, parsed_dict) for all NOTAMs ordered by name."""
    if not Path(db_path or DB_FILENAME).exists():
        return []
    conn = _get_conn(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT name, A, B, C, D, E, F, G, Q_location, Q_q_code, Q_traffic, Q_traffic_rule, Q_lower, Q_upper, Q_coordinates, Q_radius_nm FROM notams ORDER BY name"
        )
        rows = cur.fetchall()
        out = []
        for r in rows:
            parsed = {}
            for k in ('A', 'B', 'C', 'D', 'E', 'F', 'G'):
                v = r[k]
                if v is not None:
                    parsed[k] = v
            # Q subfields
            q = {}
            q_map = {
                'location': r['Q_location'], 'q_code': r['Q_q_code'], 'traffic': r['Q_traffic'],
                'traffic_rule': r['Q_traffic_rule'], 'lower': r['Q_lower'], 'upper': r['Q_upper'],
                'coordinates': r['Q_coordinates'], 'radius_nm': r['Q_radius_nm'],
            }
            for kk, vv in q_map.items():
                if vv is not None:
                    q[kk] = vv
            if q:
                parsed['Q'] = q

            out.append((r['name'], parsed))
        return out
    finally:
        conn.close()

def save_faa_activity(activity: Dict, db_path=None):
    init_db(db_path)
    payload_hash = hashlib.sha256(
        json.dumps(activity, sort_keys=True).encode("utf-8")
    ).hexdigest()
    
    conn = _get_conn(db_path)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT payload_hash
            FROM faa_activities
            WHERE mission = ?
            """, (activity["mission"],))
        activity_existing = cur.fetchone()
    except Exception as e:
        logger.exception(f"Error checking existing FAA activity: {e}")
        activity_existing = None

    try:
        if activity_existing:
            logger.info(f"FAA activity for mission '{activity['mission']}' already exists; checking for updates")
            
            existing_hash = activity_existing['payload_hash']
            
            if existing_hash is not None and payload_hash is not None and existing_hash == payload_hash:
                logger.info(f"No changes detected for FAA activity '{activity['mission']}'; skipping DB update")
                return
            else:
                if existing_hash == payload_hash:
                    logger.info(f"No effective changes detected for FAA activity '{activity['mission']}'; refreshing updated_at")
                    update_cols = ['updated_at']
                    update_set = ', '.join(f"{c} = ?" for c in update_cols)
                    update_params = [datetime.utcnow().isoformat() + 'Z', activity['mission']]
                    cur.execute(f"UPDATE faa_activities SET {update_set} WHERE mission = ?", update_params)
                else:
                    logger.info(f"Changes detected for FAA activity '{activity['mission']}'; updating all fields")
                    update_cols = ['primary_window', 'backup_window', 'updated_at', 'payload_hash']
                    update_set = ', '.join(f"{c} = ?" for c in update_cols)
                    update_params = [
                        activity['primary_window'], 
                        activity['backup_window'], 
                        datetime.utcnow().isoformat() + 'Z', 
                        payload_hash, 
                        activity['mission']
                    ]
                    cur.execute(f"UPDATE faa_activities SET {update_set} WHERE mission = ?", update_params)
        else:
            logger.info(f"Inserting new FAA activity for mission '{activity['mission']}'")
            cur.execute("""
                INSERT INTO faa_activities (mission, primary_window, backup_window, created_at, updated_at, payload_hash)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                activity["mission"],
                activity["primary_window"],
                activity["backup_window"],
                datetime.utcnow().isoformat() + 'Z',
                datetime.utcnow().isoformat() + 'Z',
                payload_hash
            ))
    finally:        
        conn.commit()
        conn.close()

def get_faa_activities_needing_post(db_path=None):
    logger.info("Fetching FAA activities needing Telegram posting")
    conn = _get_conn(db_path)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT mission, primary_window, backup_window
            FROM faa_activities
            WHERE telegram_posted = 0
            ORDER BY created_at
        """)
        rows = cur.fetchall()

        logger.debug("Found %d FAA activities needing Telegram posting", len(rows))
        return [
            {
                "mission": r["mission"],
                "primary_window": r["primary_window"],
                "backup_window": r["backup_window"]
            }
            for r in rows
        ]
    finally:
        conn.close()   

def mark_faa_activity_posted(mission, telegram_message_id, db_path=None):
    logger.info("Marking FAA activity '%s' as posted to Telegram with message ID %s", mission, telegram_message_id)
    now = datetime.utcnow().isoformat() + "Z"

    conn = _get_conn(db_path)
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE faa_activities
            SET telegram_posted = 1,
                telegram_posted_at = ?,
                telegram_message_id = ?
            WHERE mission = ?
        """, (now, telegram_message_id, mission))
        conn.commit()
    finally:
        conn.close()
        
def make_beach_key(start_utc, end_utc):
    base = f"beach|{start_utc}|{end_utc}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()

def make_road_key(origin, destination, start_utc, end_utc):
    base = f"road|{origin}|{destination}|{start_utc}|{end_utc}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()

def save_beach_alert(alert: Dict, db_path=None):
    init_db(db_path)

    now = datetime.utcnow().isoformat() + "Z"

    payload_hash = hashlib.sha256(
        json.dumps(alert, sort_keys=True).encode("utf-8")
    ).hexdigest()

    periods_json = json.dumps(alert.get("periods") or [], ensure_ascii=False)

    alert_key = make_beach_key(
        alert.get("start_utc"),
        alert.get("end_utc")
    )

    conn = _get_conn(db_path)
    try:
        cur = conn.cursor()

        cur.execute("SELECT payload_hash FROM starbase_beach WHERE alert_key = ?", (alert_key,))
        existing = cur.fetchone()

        if existing and existing["payload_hash"] == payload_hash:
            return

        if existing:
            cur.execute("""
                UPDATE starbase_beach
                SET description = ?,
                    is_closed = ?,
                    start_utc = ?,
                    end_utc = ?,
                    raw_date = ?,
                    periods_json = ?,
                    updated_at = ?,
                    payload_hash = ?
                WHERE alert_key = ?
            """, (
                alert.get("description"),
                1,
                alert.get("start_utc"),
                alert.get("end_utc"),
                alert.get("raw_date"),
                periods_json,
                now,
                payload_hash,
                alert_key
            ))
        else:
            cur.execute("""
                INSERT INTO starbase_beach (
                    alert_key,
                    description,
                    is_closed,
                    start_utc,
                    end_utc,
                    raw_date,
                    periods_json,
                    created_at,
                    updated_at,
                    payload_hash
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                alert_key,
                alert.get("description"),
                1,
                alert.get("start_utc"),
                alert.get("end_utc"),
                alert.get("raw_date"),
                periods_json,
                now,
                now,
                payload_hash
            ))

        conn.commit()

    finally:
        conn.close()
        
def save_road_alert(alert: Dict, db_path=None):
    init_db(db_path)

    now = datetime.utcnow().isoformat() + "Z"

    payload_hash = hashlib.sha256(
        json.dumps(alert, sort_keys=True).encode("utf-8")
    ).hexdigest()

    alert_key = make_road_key(
        alert.get("origin"),
        alert.get("destination"),
        alert.get("start_utc"),
        alert.get("end_utc")
    )

    conn = _get_conn(db_path)
    try:
        cur = conn.cursor()

        cur.execute("SELECT payload_hash FROM starbase_road WHERE alert_key = ?", (alert_key,))
        existing = cur.fetchone()

        if existing and existing["payload_hash"] == payload_hash:
            return

        if existing:
            cur.execute("""
                UPDATE starbase_road
                SET origin = ?,
                    destination = ?,
                    description = ?,
                    start_utc = ?,
                    end_utc = ?,
                    raw_date = ?,
                    updated_at = ?,
                    payload_hash = ?
                WHERE alert_key = ?
            """, (
                alert.get("origin"),
                alert.get("destination"),
                alert.get("description"),
                alert.get("start_utc"),
                alert.get("end_utc"),
                alert.get("raw_date"),
                now,
                payload_hash,
                alert_key
            ))
        else:
            cur.execute("""
                INSERT INTO starbase_road (
                    alert_key,
                    origin,
                    destination,
                    description,
                    start_utc,
                    end_utc,
                    raw_date,
                    created_at,
                    updated_at,
                    payload_hash
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                alert_key,
                alert.get("origin"),
                alert.get("destination"),
                alert.get("description"),
                alert.get("start_utc"),
                alert.get("end_utc"),
                alert.get("raw_date"),
                now,
                now,
                payload_hash
            ))

        conn.commit()

    finally:
        conn.close()

def get_beach_alerts_needing_post(db_path=None):
    conn = _get_conn(db_path)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT alert_key, description, start_utc, end_utc, raw_date, periods_json
            FROM starbase_beach
            WHERE processed = 0
            ORDER BY created_at
        """)
        rows = cur.fetchall()

        return [dict(r) for r in rows]
    finally:
        conn.close()
        
def get_road_alerts_needing_post(db_path=None):
    conn = _get_conn(db_path)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT alert_key, origin, destination, description, start_utc, end_utc
            FROM starbase_road
            WHERE processed = 0
            ORDER BY created_at
        """)
        rows = cur.fetchall()

        return [dict(r) for r in rows]
    finally:
        conn.close()
        
def mark_beach_posted(alert_key, db_path=None):
    conn = _get_conn(db_path)
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE starbase_beach
            SET processed = 1,
                processed_at = ?
            WHERE alert_key = ?
        """, (datetime.utcnow().isoformat() + "Z", alert_key))
        conn.commit()
    finally:
        conn.close()
        
def mark_road_posted(alert_key, db_path=None):
    conn = _get_conn(db_path)
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE starbase_road
            SET processed = 1,
                processed_at = ?
            WHERE alert_key = ?
        """, (datetime.utcnow().isoformat() + "Z", alert_key))
        conn.commit()
    finally:
        conn.close()
        
