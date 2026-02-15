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

    N_MAX_PER_MONTH = 7
    N_BLOCK_MIN = 2
    N_BLOCK_MAX = 3
    n_used = {sid: 0 for sid in req.staff_ids}
    n_block_left = {sid: 0 for sid in req.staff_ids}
    force_off_next = {sid: False for sid in req.staff_ids}
    MAX_WORKDAYS_PER_WEEK = 5
    workdays_week = {sid: {} for sid in req.staff_ids}  # sid -> {week_idx: count}
    for day_idx in range(days):
        d = (start + timedelta(days=day_idx)).date().isoformat()
        weekday = (start + timedelta(days=day_idx)).weekday()  # 0=월 ... 6=일
        week_idx = day_idx // 7

        # ✅ 평일/주말 필요 인원
        if weekday <= 4:      # 월~금
            D_NEED, E_NEED, N_NEED = 1, 2, 2
        else:                 # 토~일
            D_NEED, E_NEED, N_NEED = 2, 2, 2

        # ✅ 오늘 슬롯(일반직원용) 생성: 하루에 딱 1번
        slots = (["D"] * D_NEED) + (["E"] * E_NEED) + (["N"] * N_NEED)

        for i, sid in enumerate(req.staff_ids):
            key = (d, sid)

            # 1) 고정(EDU/PL/BL) 우선 반영
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

            # 2) A1 규칙: 평일 A1, 주말 OF (D/E/N 슬롯 카운트에 포함하지 않음)
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

            # 3) 일반직원 배정: 슬롯이 남아있으면 배정, 없으면 OF
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

    return {
        "generated_run_id": f"run_{req.month}",
        "assignments": assignments,
        "warnings": [],
        "infeasible": False
    }
    
@app.get("/")
def root():
    return {"message": "Nurse Scheduler Engine is running"}
    
