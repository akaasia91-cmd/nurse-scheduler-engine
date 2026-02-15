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

        # ✅ 오늘 필요한 슬롯(일반직원용) - 하루에 1번 생성
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

            # 2) A1 규칙: 평일 A1, 주말 OF (D/E/N 카운트에 포함하지 않음)
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

            # =========================
            # 3) 일반직원 규칙들
            # =========================

            # (a) N 블럭 종료 다음날 강제 OF
            if force_off_next[sid]:
                force_off_next[sid] = False
                shift = "OF"
                assignments.append({
                    "date": d,
                    "staff_id": sid,
                    "shift_type": shift,
                    "is_locked": False,
                    "generated_run_id": f"run_{req.month}"
                })
                continue

            # (b) OFF 최소 2회/주 자동 부여 (주당 2일 고정 오프)
            #     (A1 제외, 일반직원만 적용)
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

            # (c) N 블럭 진행 중이면 N 배정 (오늘 N 슬롯이 남아있을 때만)
            if n_block_left[sid] > 0 and "N" in slots:
                shift = "N"
                slots.remove("N")
                n_used[sid] += 1
                n_block_left[sid] -= 1

                # 블럭이 오늘로 끝났으면, 내일 강제 OF
                if n_block_left[sid] == 0:
                    force_off_next[sid] = True

                assignments.append({
                    "date": d,
                    "staff_id": sid,
                    "shift_type": shift,
                    "is_locked": False,
                    "generated_run_id": f"run_{req.month}"
                })
                continue

            # (d) N 슬롯이 남아있으면, 새 N 블럭 시작(가능할 때)
            if "N" in slots and n_block_left[sid] == 0 and n_used[sid] < N_MAX_PER_MONTH:
                # 블럭 길이 2~3을 "결정적으로" 선택(랜덤 X)
                desired_len = N_BLOCK_MIN if ((i + week_idx) % 2 == 0) else N_BLOCK_MAX

                # 월 7개 제한에 맞춰 블럭 길이 조정
                possible_len = min(desired_len, N_MAX_PER_MONTH - n_used[sid])
                if possible_len >= 2:
                    shift = "N"
                    slots.remove("N")
                    n_used[sid] += 1

                    # 오늘 1개는 이미 배정했으니 남은 개수 저장
                    n_block_left[sid] = possible_len - 1

                    # 만약 블럭 길이가 1이 되면(여기선 거의 없음) 다음날 OF
                    if n_block_left[sid] == 0:
                        force_off_next[sid] = True

                    assignments.append({
                        "date": d,
                        "staff_id": sid,
                        "shift_type": shift,
                        "is_locked": False,
                        "generated_run_id": f"run_{req.month}"
                    })
                    continue
                # possible_len < 2 이면 새 블럭 시작 불가 -> 아래 D/E/OF로 진행

            # (e) 남은 슬롯 D/E 채우기, 없으면 OF
            if slots:
                # N는 위에서 이미 처리했으므로 여기서는 D/E가 먼저 나오게끔
                # (혹시 남아 있으면 그냥 배정)
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
    
