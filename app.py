from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from psycopg import connect

app = FastAPI(title="Emotion Sensor API v2")

def get_conn():
    return connect("postgresql:///sensordb")

# ========== Модели ==========

class LogRecord(BaseModel):
    session_person_id: int
    track_id: int
    absolute_time: str
    valence: float
    arousal: float
    bbox_x1: Optional[int] = None
    bbox_y1: Optional[int] = None
    bbox_x2: Optional[int] = None
    bbox_y2: Optional[int] = None

class BulkPayload(BaseModel):
    device_id: str
    session_id: str
    records: List[LogRecord]

# ========== Эндпоинты ==========

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/v1/logs/bulk")
def ingest_bulk(payload: BulkPayload):
    if not payload.records:
        return {"ok": True, "inserted": 0}
    
    rows = []
    for r in payload.records:
        try:
            dt = datetime.fromisoformat(r.absolute_time.replace("Z", "+00:00"))
            t_ms = int(dt.timestamp() * 1000)
        except Exception:
            raise HTTPException(400, f"Bad absolute_time: {r.absolute_time}")
        
        rows.append({
            "device_id": payload.device_id,
            "session_id": payload.session_id,
            "session_person_id": r.session_person_id,
            "track_id": r.track_id,
            "t_ms": t_ms,
            "absolute_time": r.absolute_time,
            "valence": r.valence,
            "arousal": r.arousal,
            "bbox_x1": r.bbox_x1,
            "bbox_y1": r.bbox_y1,
            "bbox_x2": r.bbox_x2,
            "bbox_y2": r.bbox_y2,
        })
    
    sql = """
    INSERT INTO emotion_logs 
        (device_id, session_id, session_person_id, track_id, t_ms, absolute_time, 
         valence, arousal, bbox_x1, bbox_y1, bbox_x2, bbox_y2)
    VALUES 
        (%(device_id)s, %(session_id)s, %(session_person_id)s, %(track_id)s, %(t_ms)s, %(absolute_time)s,
         %(valence)s, %(arousal)s, %(bbox_x1)s, %(bbox_y1)s, %(bbox_x2)s, %(bbox_y2)s)
    ON CONFLICT DO NOTHING;
    """
    
    inserted = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            for row in rows:
                cur.execute(sql, row)
                inserted += cur.rowcount
        conn.commit()
    
    return {"ok": True, "inserted": inserted}

@app.get("/v1/sessions")
def list_sessions(device_id: Optional[str] = None):
    if device_id:
        sql = """
        SELECT device_id, session_id, COUNT(*) as n_points,
               COUNT(DISTINCT session_person_id) as n_persons,
               MIN(t_ms) as min_ms, MAX(t_ms) as max_ms
        FROM emotion_logs WHERE device_id = %s
        GROUP BY device_id, session_id ORDER BY max_ms DESC;
        """
        params = (device_id,)
    else:
        sql = """
        SELECT device_id, session_id, COUNT(*) as n_points,
               COUNT(DISTINCT session_person_id) as n_persons,
               MIN(t_ms) as min_ms, MAX(t_ms) as max_ms
        FROM emotion_logs
        GROUP BY device_id, session_id ORDER BY max_ms DESC;
        """
        params = ()
    
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    
    return [{"device_id": r[0], "session_id": r[1], "n_points": r[2],
             "n_persons": r[3], "min_ms": r[4], "max_ms": r[5]} for r in rows]

@app.get("/v1/persons")
def list_persons(device_id: str, session_id: str):
    sql = """
    SELECT session_person_id, COUNT(*) as n_points,
           AVG(valence) as avg_valence, AVG(arousal) as avg_arousal,
           MIN(t_ms) as min_ms, MAX(t_ms) as max_ms
    FROM emotion_logs
    WHERE device_id = %s AND session_id = %s
    GROUP BY session_person_id ORDER BY session_person_id;
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (device_id, session_id))
        rows = cur.fetchall()
    
    return [{"session_person_id": r[0], "n_points": r[1],
             "avg_valence": float(r[2]) if r[2] else 0,
             "avg_arousal": float(r[3]) if r[3] else 0,
             "min_ms": r[4], "max_ms": r[5]} for r in rows]

@app.get("/v1/logs")
def get_logs(device_id: str, session_id: str,
             session_person_id: Optional[int] = None,
             limit: int = Query(1000, ge=1, le=10000)):
    if session_person_id is not None:
        sql = """
        SELECT t_ms, valence, arousal, track_id, bbox_x1, bbox_y1, bbox_x2, bbox_y2
        FROM emotion_logs
        WHERE device_id = %s AND session_id = %s AND session_person_id = %s
        ORDER BY t_ms ASC LIMIT %s;
        """
        params = (device_id, session_id, session_person_id, limit)
    else:
        sql = """
        SELECT t_ms, valence, arousal, session_person_id, track_id
        FROM emotion_logs
        WHERE device_id = %s AND session_id = %s
        ORDER BY t_ms ASC LIMIT %s;
        """
        params = (device_id, session_id, limit)
    
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    
    if session_person_id is not None:
        records = [{"t_ms": r[0], "valence": r[1], "arousal": r[2], "track_id": r[3],
                    "bbox": [r[4], r[5], r[6], r[7]]} for r in rows]
    else:
        records = [{"t_ms": r[0], "valence": r[1], "arousal": r[2],
                    "session_person_id": r[3], "track_id": r[4]} for r in rows]
    
    return {"count": len(records), "records": records}

@app.post("/admin/truncate")
def admin_truncate():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE emotion_logs RESTART IDENTITY;")
        conn.commit()
    return {"ok": True}
