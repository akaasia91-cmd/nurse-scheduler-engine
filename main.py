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
def validate_assignments(
    month: str,
    staff_ids: List[str],
    assignments: List[Dict[str, Any]],
    n_max_per_month: int = 7,
    n_block_min: int = 2,
    n_block_max: int = 3,
    n_block_gap_min_days: int = 7,
    max_workdays_per_week: int = 5,
    fairness_tol_D: int = 1,
    fairness_tol_E: int = 1,
    fairness_tol_N: int = 1,
) -> List[str]:
    """
    assignments: [{"date":"YYYY-MM-DD","staff_id":"B1","shift_type":"D|E|N|OF|A1|EDU|PL|BL", ...}, ...]
    return: warnings (list of strings)
    """
    warnings: List[str] = []

    # month 범위 계산
    y, m = map(int, month.split("-"))
    start = datetime(y, m, 1)
    end = datetime(y + 1, 1, 1) if m == 12 else datetime(y, m + 1, 1)
    days = (end - start).days

    # 날짜 리스트
    date_list = [(start + timedelta(days=i)).date().isoformat() for i in range(days)]

    # month weekend_days(토/일 개수) 1회 계산
    weekend_days = 0
    for i in range(days):
        wd = (start + timedelta(days=i)).weekday()  # 0=월..6=일
        if wd >= 5:
            weekend_days += 1

    # 주 블럭 수(월 시작일부터 7일 단위)
    total_weeks = (days + 6) // 7

    # (date, staff_id) -> shift
    grid: Dict[tuple, str] = {}
    for a in assignments:
        d = a.get("date")
        sid = a.get("staff_id")
        st = a.get("shift_type")
        if not d or not sid or not st:
            continue
        grid[(d, sid)] = st

    # 공평성 체크용 월 누적(전체 직원 비교용) - A1 제외
    den_month_count: Dict[str, Dict[str, int]] = {}
    for sid in staff_ids:
        if sid == "A1":
            continue
        den_month_count[sid] = {"D": 0, "E": 0, "N": 0}

    # staff별로 시퀀스 구성/검증
    for sid in staff_ids:
        seq = [grid.get((d, sid), None) for d in date_list]

        # 월 D/E/N 카운트 누적(공평성용)
        if sid != "A1":
            den_month_count[sid]["D"] = sum(1 for x in seq if x == "D")
            den_month_count[sid]["E"] = sum(1 for x in seq if x == "E")
            den_month_count[sid]["N"] = sum(1 for x in seq if x == "N")

        # -------------------------
        # 1) 월 OF 총합 = weekend_days (A1 제외)
        # -------------------------
        off_cnt_month = sum(1 for x in seq if x == "OF")
        if sid != "A1" and off_cnt_month != weekend_days:
            warnings.append(f"[{sid}] Monthly OF must equal weekend_days({weekend_days}), got {off_cnt_month}")

        # -------------------------
        # 2) 주당 OF 규칙:
        #    - 완전한 주(7일) = OF 정확히 2개
        #    - 마지막 부분 주(1~6일) = 0~2개 허용 (월 목표는 위에서 검증)
        # -------------------------
        for w in range(total_weeks):
            seg = seq[w * 7 : min((w + 1) * 7, days)]
            off_cnt = sum(1 for x in seg if x == "OF")

            if len(seg) == 7:
                if sid != "A1" and off_cnt != 2:
                    warnings.append(f"[{sid}] Week {w} OF must be exactly 2 (full week), got {off_cnt}")
            else:
                if off_cnt > 2:
                    warnings.append(f"[{sid}] Week {w} OF too high (partial week), got {off_cnt}")

        # -------------------------
        # 3) 주당 최대 근무일 5일 (EDU 포함 / OF 제외)
        # -------------------------
        work_like = {"D", "E", "N", "EDU", "PL", "BL"}  # OF 제외, A1 제외(정책 시 변경 가능)
        for w in range(total_weeks):
            seg = seq[w * 7 : min((w + 1) * 7, days)]
            work_cnt = sum(1 for x in seg if x in work_like)
            if work_cnt > max_workdays_per_week:
                warnings.append(f"[{sid}] Week {w} workdays too high: {work_cnt} > {max_workdays_per_week}")

        # -------------------------
        # 4) 월 N 개수 제한
        # -------------------------
        n_count = sum(1 for x in seq if x == "N")
        if n_count > n_max_per_month:
            warnings.append(f"[{sid}] N count over monthly max: {n_count} > {n_max_per_month}")

        # -------------------------
        # 5) N 블럭(연속 N) 길이 2~3 검사 + 블럭 시작 간격(최소 7일) 검사
        # -------------------------
        n_blocks = []
        i = 0
        while i < len(seq):
            if seq[i] == "N":
                j = i
                while j < len(seq) and seq[j] == "N":
                    j += 1
                n_blocks.append((i, j - 1))  # inclusive
                i = j
            else:
                i += 1

        for (s, e) in n_blocks:
            blen = e - s + 1
            if blen < n_block_min or blen > n_block_max:
                warnings.append(f"[{sid}] N block length invalid: {blen} (idx {s}-{e})")

        for k in range(1, len(n_blocks)):
            prev_start = n_blocks[k - 1][0]
            cur_start = n_blocks[k][0]
            gap = cur_start - prev_start
            if gap < n_block_gap_min_days:
                warnings.append(f"[{sid}] N block start gap too short: {gap} days (<{n_block_gap_min_days})")
    
    # -------------------------
    # 6) N 다음날 규칙 검사
    # -------------------------
    for sid in req.staff_ids:
        if sid == "A1":
            continue

        seq = [a["shift_type"] for a in assignments if a["staff_id"] == sid]

        for idx in range(len(seq) - 1):
            if seq[idx] == "N":

                # 1️⃣ 다음날은 반드시 OF
                if seq[idx + 1] != "OF":
                    warnings.append(
                        f"[{sid}] After N must be OF (found {seq[idx + 1]}) at day {idx}"
                    )

                # 2️⃣ N-OF-둘째날 규칙
                if idx + 2 < len(seq):
                    third = seq[idx + 2]

                    if third in {"D", "EDU"}:
                        warnings.append(
                            f"[{sid}] Pattern N-OF-{third} forbidden at day {idx}"
                        )
            # 허용: N-OF-OF (원칙), N-OF-E (예외 허용)

    # -------------------------
    # 7) 월 D/E/N 공평성(전체 직원 비교) - A1 제외
    # -------------------------
    if den_month_count:
        for sh, tol in [("D", fairness_tol_D), ("E", fairness_tol_E), ("N", fairness_tol_N)]:
            vals = [den_month_count[sid][sh] for sid in den_month_count.keys()]
            mn = min(vals)
            mx = max(vals)
            if mx - mn > tol:
                # 어느 직원이 많은지/적은지까지 같이 표시
                max_sids = [sid for sid in den_month_count.keys() if den_month_count[sid][sh] == mx]
                min_sids = [sid for sid in den_month_count.keys() if den_month_count[sid][sh] == mn]
                warnings.append(
                    f"[FAIRNESS] Monthly {sh} imbalance: max({mx})={max_sids}, min({mn})={min_sids}, gap={mx-mn} > tol({tol})"
                )

    return warnings

                # 다음날이 OF일 때, 그 다음날 검사(있을 때만)
                if idx + 2 < len(seq):
                    next2 = seq[idx + 2]
                    # 금지: N-OF-D, N-OF-EDU
                    if next2 in {"D", "EDU"}:
                        warnings.append(f"[{sid}] Pattern N-OF-{next2} forbidden at day_idx={idx}")
                    # 허용: N-OF-OF (원칙), N-OF-E (대안)
                    # PL/BL은 정책에 따라 달라질 수 있어 경고로만
                    if next2 in {"PL", "BL"}:
                        warnings.append(f"[{sid}] Pattern N-OF-{next2} check policy (allowed?) at day_idx={idx}")

    return warnings
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
            # (고정 OF) - 월 목표(weekend_days)와 주 2회 고정 패턴을 동시에 만족시키기 위한 계획표
            if sid in fixed_off_dayidx and day_idx in fixed_off_dayidx[sid]:
                shift = "OF"
                off_used[sid] += 1
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
    warnings = validate_assignments(req.month, req.staff_ids, assignments)
    infeasible = len(warnings) > 0
    return {
        "generated_run_id": f"run_{req.month}",
        "assignments": assignments,
        "warnings": warnings,
        "infeasible": infeasible
    }

@app.get("/")
def root():
    return {"message": "Nurse Scheduler Engine is running"}
    
