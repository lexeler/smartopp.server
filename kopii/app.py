from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from psycopg import connect

app = FastAPI(title="Emotion Sensor API v3")

def get_conn():
    return connect("postgresql:///sensordb")

# ========== Модели ==========

class LogRecord(BaseModel):
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
        return {"ok": True, "inserted": 0, "person_id": None}
    
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COALESCE(MAX(person_id), 0) + 1 FROM emotion_logs;")
            next_person_id = cur.fetchone()[0]
    
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
            "person_id": next_person_id,
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
        (device_id, session_id, person_id, track_id, t_ms, absolute_time, 
         valence, arousal, bbox_x1, bbox_y1, bbox_x2, bbox_y2)
    VALUES 
        (%(device_id)s, %(session_id)s, %(person_id)s, %(track_id)s, %(t_ms)s, %(absolute_time)s,
         %(valence)s, %(arousal)s, %(bbox_x1)s, %(bbox_y1)s, %(bbox_x2)s, %(bbox_y2)s)
    ON CONFLICT (device_id, session_id, person_id, track_id, t_ms) DO NOTHING;
    """
    
    inserted = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            for row in rows:
                cur.execute(sql, row)
                inserted += cur.rowcount
        conn.commit()
    
    return {"ok": True, "inserted": inserted, "person_id": next_person_id}

@app.get("/v1/persons")
def list_persons():
    """Список всех людей"""
    sql = """
    SELECT person_id, device_id, session_id, COUNT(*) as n_points,
           AVG(valence) as avg_valence, AVG(arousal) as avg_arousal,
           MIN(t_ms) as min_ms, MAX(t_ms) as max_ms
    FROM emotion_logs
    GROUP BY person_id, device_id, session_id
    ORDER BY person_id DESC;
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    
    return [{"person_id": r[0], "device_id": r[1], "session_id": r[2], 
             "n_points": r[3],
             "avg_valence": round(float(r[4]), 3) if r[4] else 0,
             "avg_arousal": round(float(r[5]), 3) if r[5] else 0,
             "min_ms": r[6], "max_ms": r[7]} for r in rows]

@app.get("/v1/logs")
def get_logs(person_id: int, limit: int = Query(1000, ge=1, le=10000)):
    """Получить записи одного человека"""
    sql = """
    SELECT t_ms, valence, arousal, track_id, bbox_x1, bbox_y1, bbox_x2, bbox_y2
    FROM emotion_logs
    WHERE person_id = %s
    ORDER BY t_ms ASC LIMIT %s;
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (person_id, limit))
        rows = cur.fetchall()
    
    records = [{"t_ms": r[0], "valence": r[1], "arousal": r[2], "track_id": r[3],
                "bbox": [r[4], r[5], r[6], r[7]]} for r in rows]
    
    return {"person_id": person_id, "count": len(records), "records": records}

@app.post("/admin/truncate")
def admin_truncate():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE emotion_logs RESTART IDENTITY;")
        conn.commit()
    return {"ok": True}
