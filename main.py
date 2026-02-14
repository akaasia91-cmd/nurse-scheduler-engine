from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Dict, Any
from datetime import datetime, timedelta

app = FastAPI(title="Nurse Scheduler Engine")

class GenerateRequest(BaseModel):
    month: str
    staff_ids: List[str]
    rules: Dict[str, Any] = {}
    requests: List[Dict[str, Any]] = []
    locked: List[Dict[str, Any]] = []

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/generate")
def generate(req: GenerateRequest):
    year, month = map(int, req.month.split("-"))
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)
    days = (end - start).days
    
    shifts = ["D", "E", "N"]   # 일반직원 근무 패턴 (OF는 규칙으로 따로 부여)
    assignments = []
    # 1. 고정처리 대상 shift
    LOCK_TYPES = {"EDU", "PL", "BL"}
    
    locked_map = {}
    for item in (req.locked or []):
    if item.get("shift_type") in LOCK_TYPES:
    key = (item["date"], item["staff_id"].strip())
    locked_map[key] = item["shift_type"]
    
    for day_idx in range(days):
    d = (start + timedelta(days=day_idx)).date().isoformat()
    weekday = (start + timedelta(days=day_idx)).weekday()
    week_idx = day_idx // 7
    
    for i, sid in enumerate(req.staff_ids):
    key = (d, sid)
    
    # 고정처리 우선
    if key in locked_map:
    shift = locked_map[key]
    assignments.append({
    "date": d,
    "staff_id": sid,
    "shift_type": shift,
    "is_locked": True,
    "generated_run_id": f"run_{req.month}"
    })
    continue
    
    # 1) 수간호사(A1): 평일 A1, 주말 OF(필수)
    if sid == "A1":
    shift = "OF" if weekday >= 5 else "A1"
    
    # 2) 일반직원: 주당 OF 2회 강제
    else:
    off1 = (i + week_idx) % 7
    off2 = (i + week_idx + 3) % 7
    
    if weekday == off1 or weekday == off2:
    shift = "OF"
    else:
    shift = shifts[(day_idx + i) % len(shifts)]
    
    assignments.append({
    "date": d,
    "staff_id": sid,
    "shift_type": shift,
    "is_locked": False,
    "generated_run_id": f"run_{req.month}"
    })
    return {
    "generated_run_id": f"run_{req.month}",
    "assignments": assignments,
    "warnings": [],
    "infeasible": False
    }
    
    @app.get("/")
    def root():
    return {"message": "Nurse Scheduler Engine is running"}
