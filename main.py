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

@app.post("/generate")
def generate(req: GenerateRequest):

    year, month = map(int, req.month.split("-"))
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)

    days = (end - start).days
    assignments = []

    LOCK_TYPES = {"EDU", "PL", "BL"}

    locked_map = {}
    for item in (req.locked or []):
        if item.get("shift_type") in LOCK_TYPES:
            key = (item["date"], item["staff_id"].strip())
            locked_map[key] = item["shift_type"]

    # ---- N 규칙 세팅 ----
    N_MAX_PER_MONTH = 7
    N_BLOCK_MIN = 2
    N_BLOCK_MAX = 3

    n_used = {sid: 0 for sid in req.staff_ids}
    n_block_left = {sid: 0 for sid in req.staff_ids}
    force_off_next = {sid: False for sid in req.staff_ids}
    next_n_allowed_day = {sid: 0 for sid in req.staff_ids}

    for day_idx in range(days):

        d = (start + timedelta(days=day_idx)).date().isoformat()
        weekday = (start + timedelta(days=day_idx)).weekday()
        week_idx = day_idx // 7

        # 필요 인원
        if weekday <= 4:
            D_NEED, E_NEED, N_NEED = 1, 2, 2
        else:
            D_NEED, E_NEED, N_NEED = 2, 2, 2

        slots = (["D"] * D_NEED) + (["E"] * E_NEED) + (["N"] * N_NEED)

        for i, sid in enumerate(req.staff_ids):

            key = (d, sid)

            # 1. 고정처리
            if key in locked_map:
                assignments.append({
                    "date": d,
                    "staff_id": sid,
                    "shift_type": locked_map[key],
                    "is_locked": True,
                    "generated_run_id": f"run_{req.month}"
                })
                continue

            # 2. A1 규칙
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

            # 3. N 다음날 강제 OFF
            if force_off_next[sid]:
                force_off_next[sid] = False
                assignments.append({
                    "date": d,
                    "staff_id": sid,
                    "shift_type": "OF",
                    "is_locked": False,
                    "generated_run_id": f"run_{req.month}"
                })
                continue

            # 4. OFF 주 2회 자동
            off1 = (i + week_idx) % 7
            off2 = (i + week_idx + 3) % 7
            if weekday == off1 or weekday == off2:
                assignments.append({
                    "date": d,
                    "staff_id": sid,
                    "shift_type": "OF",
                    "is_locked": False,
                    "generated_run_id": f"run_{req.month}"
                })
                continue

            # 5. N 블럭 진행 중
            if n_block_left[sid] > 0 and "N" in slots:
                slots.remove("N")
                n_used[sid] += 1
                n_block_left[sid] -= 1

                if n_block_left[sid] == 0:
                    force_off_next[sid] = True
                    next_n_allowed_day[sid] = day_idx + 7
                    after_n_of_day[sid] = day_idx + 2
                    after_n_of_day = {sid: -999 for sid in req.staff_ids}  # N 다음날(OF) 후 "그 다음날"을 표시
                assignments.append({
                    "date": d,
                    "staff_id": sid,
                    "shift_type": "N",
                    "is_locked": False,
                    "generated_run_id": f"run_{req.month}"
                })
                continue

            # 6. 새 N 블럭 시작
            can_start_n = (
                day_idx >= next_n_allowed_day[sid]
                and n_used[sid] < N_MAX_PER_MONTH
                and "N" in slots
            )

            if can_start_n:
                block_len = N_BLOCK_MIN if (n_used[sid] % 2 == 0) else N_BLOCK_MAX
                block_len = min(block_len, N_MAX_PER_MONTH - n_used[sid])

                if block_len >= 2:
                    slots.remove("N")
                    n_used[sid] += 1
                    n_block_left[sid] = block_len - 1
                    force_off_next[sid] = True
                    next_n_allowed_day[sid] = day_idx + 7
                    assignments.append({
                        "date": d,
                        "staff_id": sid,
                        "shift_type": "N",
                        "is_locked": False,
                        "generated_run_id": f"run_{req.month}"
                    })
                    continue

            # 7. D/E 배정 (N-OF 다음날 규칙 반영)
            shift = "OF"

            # N-OF 다음날이면: D 금지, (EDU는 locked에서 이미 처리됨), 가능하면 OF, 불가하면 E만 허용
            if day_idx == after_n_of_day[sid]:
                # slots에서 D는 절대 뽑지 않음
                if "E" in slots:
                    # 원칙은 OF-OF이지만, 근무가 안될 때만 E 허용
                    shift = "E"
                    slots.remove("E")
                else:
                    shift = "OF"
            else:
                # 평소처럼 D/E 채우기
                for pref in ["D", "E"]:
                    if pref in slots:
                        shift = pref
                        slots.remove(pref)
                        break

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
    
