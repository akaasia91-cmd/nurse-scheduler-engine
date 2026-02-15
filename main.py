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
            key = (item["date"], item["staff_id"].strip())
            locked_map[key] = item["shift_type"]

    for day_idx in range(days):
        d = (start + timedelta(days=day_idx)).date().isoformat()
        weekday = (start + timedelta(days=day_idx)).weekday()  # 0=월 ... 6=일
        week_idx = day_idx // 7

        # 평일(월~금): A1이 근무하면 D1,E2,N2
        # 주말(토~일): D2,E2,N2
        if weekday <= 4:
            D_NEED = 1
            E_NEED = 2
            N_NEED = 2
        else:
            D_NEED = 2
            E_NEED = 2
            N_NEED = 2

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
    
    # A1은 평일 고정근무, 주말 OFF (A1은 D/E/N 카운트에 포함하지 않음)
    if sid == "A1": 
        shift = "A1" if weekday <= 4 else "OF" 
        assignments.append({
            "date": d,
            "staff_id": sid,
            "shift_type": shift,
            "is_locked": False,
            "generated_run_id": f"run_{req.month}"
        })
        continue

        # 오늘 필요한 D/E/N 슬롯을 하루에 한 번만 만들기 위해:
        # day_idx 루프 안에서 처음 직원 들어올 때만 slots를 만들도록 캐시
        if i == 0:
            slots = (["D"] * D_NEED) + (["E"] * E_NEED) + (["N"] * N_NEED)

        # 일반 직원 배정: 슬롯이 남아있으면 채우고, 없으면 OF
        if slots:
            shift = slots.pop(0)
        else:
            shift = "OF"

        assignments.append({
            "date": d,
            "staff_id": sid,
            "shift_type": shift,
            "is_locked": False,
            "generated_run_id": f"run_{req.month}"
        })
        continue
    return {
    "generated_run_id": f"run_{req.month}",
    "assignments": assignments,
    "warnings": [],
    "infeasible": False
    }
    
@app.get("/")
def root():
    return {"message": "Nurse Scheduler Engine is running"}
    
