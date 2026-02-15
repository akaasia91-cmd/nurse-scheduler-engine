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

        # 오늘 필요한 슬롯(일반직원만 채움)
        slots = (["D"] * D_NEED) + (["E"] * E_NEED) + (["N"] * N_NEED)

        for i, sid in enumerate(req.staff_ids):
            key = (d, sid)

            # 0) 고정(locked) 우선
    # 고정처리 우선 (EDU/PL/BL만)
    if key in locked_map:
        shift = locked_map[key]

        if shift == "EDU":
            workdays_week[sid][week_idx] = workdays_week[sid].get(week_idx, 0) + 1

        assignments.append({
            "date": d,
            "staff_id": sid,
            "shift_type": shift,
            "is_locked": True,
            "generated_run_id": f"run_{req.month}"
        })
        continue

            # 1) A1 규칙(평일 A1 / 주말 OF) + D/E/N 카운트에 미포함
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

        # 2) 일반직원: OFF 최소 2회/주 강제 (주당 2일 OFF 요일 고정)
        #    (주의: 이 로직을 쓰려면 for 루프가 enumerate(req.staff_ids) 여야 i를 쓸 수 있습니다)
        off1 = (i + week_idx) % 7
        off2 = (i + week_idx + 3) % 7

    if weekday == off1 or weekday == off2:
        shift = "OF"
        assignments.append({
            "date": d,
            "staff_id": sid,
            "shift_type": shift,
            "is_locked": False,
            "generated_run_id": f"run_{req.month}"
         })
         continue

            # 3) 남은 슬롯 채우기(없으면 OF)
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
    
