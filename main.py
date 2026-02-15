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

    staff = req.staff_ids[:]  # 순서 고정(결정론)
    assignments = []

    # ----------------------------
    # 0) 고정(교육/공가/경조사 등) 반영: req.locked는 전부 고정 처리
    # ----------------------------
    locked_map: Dict[tuple, str] = {}
    for item in (req.locked or []):
        try:
            key = (item["date"], item["staff_id"].strip())
            locked_map[key] = item["shift_type"]
        except Exception:
            # 잘못된 입력은 무시(MVP 안전)
            pass

    # ----------------------------
    # 1) 월 공평 카운터 (A1 제외)
    # ----------------------------
    den_count = {sid: {"D": 0, "E": 0, "N": 0} for sid in staff if sid != "A1"}

    # ----------------------------
    # 2) OFF 최소 2회/주(기본 보장)
    # ----------------------------
    # 주당 2일 고정 오프를 주는 방식(결정론)
    def is_weekly_fixed_off(sid: str, i: int, week_idx: int, weekday: int) -> bool:
        off1 = (i + week_idx) % 7
        off2 = (i + week_idx + 3) % 7
        return weekday == off1 or weekday == off2

    # ----------------------------
    # 3) N 규칙 상태
    # ----------------------------
    N_MAX_PER_MONTH = 7
    N_BLOCK_MIN = 2
    N_BLOCK_MAX = 3

    n_used = {sid: 0 for sid in staff if sid != "A1"}
    n_block_left = {sid: 0 for sid in staff if sid != "A1"}          # 남은 연속 N 수(오늘 제외)
    n_block_start = {sid: -999 for sid in staff if sid != "A1"}      # 현재 블럭 시작 day_idx
    next_n_allowed_day = {sid: 0 for sid in staff if sid != "A1"}    # 다음 블럭 시작 가능 day_idx

    # N블럭 끝난 뒤 휴식: 2 -> 오늘은 무조건 OF(첫째날), 1 -> 원칙 OF(둘째날, 부족하면 E 허용)
    post_n_rest = {sid: 0 for sid in staff if sid != "A1"}

    # ----------------------------
    # 4) (옵션) 주 5일 근무 상한: EDU 포함
    # - MVP 안전형: 가능하면 지키고, 슬롯이 남을 때는 채우는 방식
    # ----------------------------
    MAX_WORKDAYS_PER_WEEK = 5
    workdays_week = {sid: {} for sid in staff}  # sid -> {week_idx: count}

    def add_workday(sid: str, week_idx: int):
        workdays_week[sid][week_idx] = workdays_week[sid].get(week_idx, 0) + 1

    def get_workday(sid: str, week_idx: int) -> int:
        return workdays_week[sid].get(week_idx, 0)

    def is_work_shift(shift: str) -> bool:
        # OF는 근무 아님. 나머지는 근무로 카운트(EDU 포함)
        return shift != "OF"

    # ----------------------------
    # 5) 공평 배정(월 기준) - D/E 중 무엇을 줄지 선택
    # ----------------------------
    def pick_fair_DE(sid: str, slots: List[str]) -> str:
        # slots에 D/E 둘 다 있으면, 그 직원이 "더 적게 한" 쪽을 우선
        hasD = "D" in slots
        hasE = "E" in slots
        if not (hasD or hasE):
            return "OF"

        if sid == "A1":
            # A1은 여기로 오지 않음
            return "OF"

        if hasD and not hasE:
            return "D"
        if hasE and not hasD:
            return "E"

        # 둘 다 있으면 공평하게
        d_cnt = den_count[sid]["D"]
        e_cnt = den_count[sid]["E"]
        return "D" if d_cnt <= e_cnt else "E"

    # ----------------------------
    # 메인 루프 (일자)
    # ----------------------------
    for day_idx in range(days):
        d = (start + timedelta(days=day_idx)).date().isoformat()
        weekday = (start + timedelta(days=day_idx)).weekday()   # 0=월 ... 6=일
        week_idx = day_idx // 7

        # ✅ 평일/주말 필요 인원(일반직원용)
        if weekday <= 4:      # 월~금
            D_NEED, E_NEED, N_NEED = 1, 2, 2
        else:                 # 토~일
            D_NEED, E_NEED, N_NEED = 2, 2, 2

        # 오늘 필요한 슬롯(일반직원용) - 하루에 1번 생성
        slots = (["D"] * D_NEED) + (["E"] * E_NEED) + (["N"] * N_NEED)

        # 직원 루프
        for i, sid in enumerate(staff):
            key = (d, sid)

            # (1) 고정반영(교육/공가/경조사 등): 있으면 무조건 그 값
            if key in locked_map:
                shift = locked_map[key]

                assignments.append({
                    "date": d,
                    "staff_id": sid,
                    "shift_type": shift,
                    "is_locked": True,
                    "generated_run_id": f"run_{req.month}"
                })

                # 카운트 갱신
                if sid != "A1":
                    if shift in ("D", "E", "N"):
                        den_count[sid][shift] += 1
                    if shift == "N":
                        n_used[sid] += 1  # 고정 N도 월 제한에 포함
                        # 고정 N은 블럭으로 간주하지 않되, 안전하게 휴식 규칙은 적용
                        post_n_rest[sid] = 2
                        next_n_allowed_day[sid] = max(next_n_allowed_day[sid], day_idx + 7)

                if is_work_shift(shift):
                    add_workday(sid, week_idx)

                continue

            # (2) A1 규칙: 평일 A1, 주말 OF (D/E/N 카운트 제외)
            if sid == "A1":
                shift = "A1" if weekday <= 4 else "OF"
                assignments.append({
                    "date": d,
                    "staff_id": sid,
                    "shift_type": shift,
                    "is_locked": False,
                    "generated_run_id": f"run_{req.month}"
                })
                if is_work_shift(shift):
                    add_workday(sid, week_idx)
                continue

            # ----------------------------
            # (3) N블럭 후 휴식 처리 (원칙: OF-OF, 둘째날만 E 예외 허용)
            # ----------------------------
            if post_n_rest[sid] == 2:
                # 첫째날: 무조건 OF
                post_n_rest[sid] = 1
                shift = "OF"
                assignments.append({
                    "date": d,
                    "staff_id": sid,
                    "shift_type": shift,
                    "is_locked": False,
                    "generated_run_id": f"run_{req.month}"
                })
                continue

            if post_n_rest[sid] == 1:
                # 둘째날: 원칙 OF, 다만 정말로 E가 남고 다른 인력이 부족할 때만 E 허용
                # (간단 안전형) 오늘 slots에 E가 "남아있고", (D가 이미 다 찼거나) E만 남은 경우에만 E 허용
                can_use_E = ("E" in slots) and ("D" not in slots) and ("N" not in slots)
                if can_use_E:
                    shift = "E"
                    slots.remove("E")
                    den_count[sid]["E"] += 1
                    add_workday(sid, week_idx)
                else:
                    shift = "OF"
                post_n_rest[sid] = 0

                assignments.append({
                    "date": d,
                    "staff_id": sid,
                    "shift_type": shift,
                    "is_locked": False,
                    "generated_run_id": f"run_{req.month}"
                })
                continue

            # ----------------------------
            # (4) 주당 OFF 최소 2회 (기본)
            # ----------------------------
            if is_weekly_fixed_off(sid, i, week_idx, weekday):
                shift = "OF"
                assignments.append({
                    "date": d,
                    "staff_id": sid,
                    "shift_type": shift,
                    "is_locked": False,
                    "generated_run_id": f"run_{req.month}"
                })
                continue

            # ----------------------------
            # (5) N 블럭 진행 중이면 N 배정 (연속 N)
            # ----------------------------
            if n_block_left[sid] > 0 and "N" in slots and n_used[sid] < N_MAX_PER_MONTH:
                shift = "N"
                slots.remove("N")
                den_count[sid]["N"] += 1
                n_used[sid] += 1
                n_block_left[sid] -= 1
                add_workday(sid, week_idx)

                # 블럭 종료 시: 다음 2일 휴식 + 다음 N블럭은 (시작 기준) 7일 이후
                if n_block_left[sid] == 0:
                    post_n_rest[sid] = 2  # OF-OF
                    # next_n_allowed_day는 "블럭 시작 후 7일" 기준
                    next_n_allowed_day[sid] = max(next_n_allowed_day[sid], n_block_start[sid] + 7)

                assignments.append({
                    "date": d,
                    "staff_id": sid,
                    "shift_type": shift,
                    "is_locked": False,
                    "generated_run_id": f"run_{req.month}"
                })
                continue

            # ----------------------------
            # (6) 새 N 블럭 시작 (2~3 연속)
            #     - 블럭 시작 후 다음 블럭 시작은 최소 7일 이후
            # ----------------------------
            can_start_n = (
                ("N" in slots)
                and n_block_left[sid] == 0
                and n_used[sid] < N_MAX_PER_MONTH
                and day_idx >= next_n_allowed_day[sid]
            )

            if can_start_n:
                # 블럭 길이 결정(결정론): 2,3 번갈아
                desired = N_BLOCK_MIN if ((n_used[sid] + i + week_idx) % 2 == 0) else N_BLOCK_MAX
                # 월 7개 제한에 맞춰 조정
                remaining = N_MAX_PER_MONTH - n_used[sid]
                block_len = min(desired, remaining)

                # 최소 2개 블럭만 허용
                if block_len >= 2:
                    shift = "N"
                    slots.remove("N")
                    den_count[sid]["N"] += 1
                    n_used[sid] += 1
                    add_workday(sid, week_idx)

                    n_block_start[sid] = day_idx
                    n_block_left[sid] = block_len - 1  # 오늘 1개 배정했으니 남은 개수

                    # 다음 블럭 시작 가능 시점(시작 후 7일)
                    next_n_allowed_day[sid] = day_idx + 7

                    assignments.append({
                        "date": d,
                        "staff_id": sid,
                        "shift_type": shift,
                        "is_locked": False,
                        "generated_run_id": f"run_{req.month}"
                    })
                    continue
                # block_len < 2이면 N블럭 시작 안 하고 아래 D/E로 넘어감

            # ----------------------------
            # (7) D/E 공평 배정 (월 기준) + 슬롯 없으면 OF
            # ----------------------------
            if "D" in slots or "E" in slots:
                shift = pick_fair_DE(sid, slots)

                if shift in ("D", "E"):
                    slots.remove(shift)
                    den_count[sid][shift] += 1
                    add_workday(sid, week_idx)
                else:
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
    
