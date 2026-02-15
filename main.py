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
    next_n_allowed_day = {sid: 0 for sid in req.staff_ids}  # 다음 N 시작 가능한 day_idx
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
            # 일반 직원 배정: 슬롯이 남아있으면 채우고, 없으면 OF
shift = "OF"

# 1) 강제 OF (N 다음날)
if force_off_next[sid]:
    force_off_next[sid] = False
    shift = "OF"

else:
    # 2) N 블록 진행 중이면 N 우선 (단, 월 7회 제한도 같이 체크)
    if n_block_left[sid] > 0 and n_used[sid] < N_MAX_PER_MONTH:
        shift = "N"
        n_used[sid] += 1
        n_block_left[sid] -= 1
        force_off_next[sid] = True

        # 블록이 끝났으면: 다음 N 블록 시작은 최소 7일 후
        if n_block_left[sid] == 0:
            next_n_allowed_day[sid] = day_idx + 7

    else:
        # 3) 오늘 N을 새로 시작할 수 있는지 체크
        can_start_new_n = (day_idx >= next_n_allowed_day[sid]) and (n_used[sid] < N_MAX_PER_MONTH)

        if slots:
            if "N" in slots and can_start_new_n:
                # N 새 블록 시작(2~3개)
                shift = "N"
                slots.remove("N")
                n_used[sid] += 1
                force_off_next[sid] = True

                # 이번 블록 길이(2~3) 설정: 오늘 1개 했으니 남은 개수는 (block_len - 1)
                block_len = N_BLOCK_MIN if (n_used[sid] % 2 == 0) else N_BLOCK_MAX  # 간단한 토글 방식
                n_block_left[sid] = max(0, block_len - 1)

                # (주의) 블록이 1로 끝나는 경우는 없도록 최소 2로 잡았기 때문에 OK

            else:
                # N이 있더라도 시작 불가면 N 제외하고 D/E 먼저 채우기
                for pref in ["D", "E"]:
                    if pref in slots:
                        shift = pref
                        slots.remove(pref)
                        break
                else:
                    # D/E가 없으면 OF
                    shift = "OF"
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
    
@app.get("/")
def root():
    return {"message": "Nurse Scheduler Engine is running"}
    
