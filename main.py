from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Dict, Any, Tuple
from datetime import datetime, timedelta, date

app = FastAPI(title="Nurse Scheduler Engine")


class GenerateRequest(BaseModel):
    month: str                # "YYYY-MM"
    staff_ids: List[str]      # ["A1","B1",...]
    rules: Dict[str, Any] = {}
    requests: List[Dict[str, Any]] = []
    locked: List[Dict[str, Any]] = []   # [{"date":"YYYY-MM-DD","staff_id":"B1","shift_type":"EDU"}, ...]


def _month_range(month: str) -> Tuple[datetime, datetime, int, List[str]]:
    y, m = map(int, month.split("-"))
    start = datetime(y, m, 1)
    end = datetime(y + 1, 1, 1) if m == 12 else datetime(y, m + 1, 1)
    days = (end - start).days
    date_list = [(start + timedelta(days=i)).date().isoformat() for i in range(days)]
    return start, end, days, date_list


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
    warnings: List[str] = []

    start, _, days, date_list = _month_range(month)

    # weekend_days(토/일 개수)
    weekend_days = 0
    for i in range(days):
        wd = (start + timedelta(days=i)).weekday()
        if wd >= 5:
            weekend_days += 1

    # (date, staff_id) -> shift
    grid: Dict[Tuple[str, str], str] = {}
    for a in assignments:
        d = a.get("date")
        sid = a.get("staff_id")
        st = a.get("shift_type")
        if d and sid and st:
            grid[(d, sid)] = st

    # 공평성용 월 누적(A1 제외)
    den_month_count: Dict[str, Dict[str, int]] = {}
    for sid in staff_ids:
        if sid != "A1":
            den_month_count[sid] = {"D": 0, "E": 0, "N": 0}

    # 주차(캘린더 week)별 분할을 위해: date -> (iso_year, iso_week)
    week_keys: List[Tuple[int, int]] = []
    for i in range(days):
        dd = (start + timedelta(days=i)).date()
        iso = dd.isocalendar()
        wk = (iso.year, iso.week)
        if not week_keys or week_keys[-1] != wk:
            week_keys.append(wk)

    # staff별 시퀀스
    for sid in staff_ids:
        seq = [grid.get((d, sid), None) for d in date_list]

        if sid != "A1":
            den_month_count[sid]["D"] = sum(1 for x in seq if x == "D")
            den_month_count[sid]["E"] = sum(1 for x in seq if x == "E")
            den_month_count[sid]["N"] = sum(1 for x in seq if x == "N")

        # 1) 월 OF 총합 = weekend_days (A1 제외)
        off_cnt_month = sum(1 for x in seq if x == "OF")
        if sid != "A1" and off_cnt_month != weekend_days:
            warnings.append(f"[{sid}] Monthly OF must equal weekend_days({weekend_days}), got {off_cnt_month}")

        # 2) 주당 OF 규칙(캘린더 주 기준):
        #    - 완전한 주(월~일 7일 모두 포함된 주) = OF 2개 권장(검증)
        #    - 마지막 부분 주(월 말 잘린 주)는 0~2 허용
        #    ※ 엄격 강제는 생성 로직에서 “계획”으로 하고, 여기서는 검증/경고로 처리
        #       (병원 인력 요구가 더 우선인 날이 있을 수 있어요)
        # 주별 index 모으기
        week_to_idx: Dict[Tuple[int, int], List[int]] = {}
        for i in range(days):
            dd = (start + timedelta(days=i)).date()
            wk = (dd.isocalendar().year, dd.isocalendar().week)
            week_to_idx.setdefault(wk, []).append(i)

        ordered_weeks = list(week_to_idx.keys())
        ordered_weeks.sort()

        for wi, wk in enumerate(ordered_weeks):
            idxs = week_to_idx[wk]
            seg = [seq[j] for j in idxs]
            off_cnt = sum(1 for x in seg if x == "OF")

            is_last = (wi == len(ordered_weeks) - 1)
            # 마지막 주는 0~2 허용
            if not is_last and sid != "A1":
                if off_cnt != 2:
                    warnings.append(f"[{sid}] Week {wk} OF should be 2 (full week), got {off_cnt}")
            else:
                if off_cnt > 2:
                    warnings.append(f"[{sid}] Week {wk} OF too high (last/partial week), got {off_cnt}")

        # 3) 주당 최대 근무일 5일 (EDU 포함 / OF 제외)
        work_like = {"D", "E", "N", "EDU", "PL", "BL"}  # OF 제외
        for wk in ordered_weeks:
            idxs = week_to_idx[wk]
            seg = [seq[j] for j in idxs]
            work_cnt = sum(1 for x in seg if x in work_like)
            if sid != "A1" and work_cnt > max_workdays_per_week:
                warnings.append(f"[{sid}] Week {wk} workdays too high: {work_cnt} > {max_workdays_per_week}")

        # 4) 월 N 개수 제한
        n_count = sum(1 for x in seq if x == "N")
        if sid != "A1" and n_count > n_max_per_month:
            warnings.append(f"[{sid}] N count over monthly max: {n_count} > {n_max_per_month}")

        # 5) N 블럭(연속 N) 길이 2~3 + 블럭 시작 간격 >= 7일
        if sid != "A1":
            n_blocks: List[Tuple[int, int]] = []
            i = 0
            while i < len(seq):
                if seq[i] == "N":
                    j = i
                    while j < len(seq) and seq[j] == "N":
                        j += 1
                    n_blocks.append((i, j - 1))
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

        # 6) N 다음날 규칙 + N-OF-OF 원칙(둘째날 E만 예외)
        if sid != "A1":
            for idx in range(len(seq) - 1):
                if seq[idx] == "N":
                    # 다음날은 반드시 OF
                    if seq[idx + 1] != "OF":
                        warnings.append(f"[{sid}] After N must be OF (found {seq[idx + 1]}) at day_idx={idx}")

                    # 둘째날 규칙: 원칙 OF, 예외 E만 허용 (D/EDU 금지)
                    if idx + 2 < len(seq):
                        third = seq[idx + 2]
                        if third in {"D", "EDU"}:
                            warnings.append(f"[{sid}] Pattern N-OF-{third} forbidden at day_idx={idx}")

    # 7) 월 D/E/N 공평성(A1 제외)
    if den_month_count:
        for sh, tol in [("D", fairness_tol_D), ("E", fairness_tol_E), ("N", fairness_tol_N)]:
            vals = [den_month_count[sid][sh] for sid in den_month_count.keys()]
            mn = min(vals)
            mx = max(vals)
            if mx - mn > tol:
                max_sids = [sid for sid in den_month_count.keys() if den_month_count[sid][sh] == mx]
                min_sids = [sid for sid in den_month_count.keys() if den_month_count[sid][sh] == mn]
                warnings.append(
                    f"[FAIRNESS] Monthly {sh} imbalance: max({mx})={max_sids}, min({mn})={min_sids}, gap={mx-mn} > tol({tol})"
                )

    return warnings


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/generate")
def generate(req: GenerateRequest):
    start, _, days, date_list = _month_range(req.month)
    staff = req.staff_ids[:]  # 결정론(입력 순서 고정)

    # weekend_days(토/일 개수) 계산
    weekend_days = 0
    for i in range(days):
        wd = (start + timedelta(days=i)).weekday()
        if wd >= 5:
            weekend_days += 1

    # 고정(교육/공가/경조사 등) 반영: EDU/PL/BL 등은 고정 처리
    LOCK_TYPES = {"EDU", "PL", "BL"}
    locked_map: Dict[Tuple[str, str], str] = {}
    for item in (req.locked or []):
        try:
            key = (item["date"], item["staff_id"].strip())
            st = item["shift_type"]
            if st in LOCK_TYPES:
                locked_map[key] = st
        except Exception:
            pass

    # 주당 근무일 카운트(EDU 포함)
    workdays_week: Dict[str, Dict[Tuple[int, int], int]] = {sid: {} for sid in staff}
    def add_workday(sid: str, wk: Tuple[int, int]) -> None:
        workdays_week[sid][wk] = workdays_week[sid].get(wk, 0) + 1
    def get_workday(sid: str, wk: Tuple[int, int]) -> int:
        return workdays_week[sid].get(wk, 0)

    # 월 공평 카운터(A1 제외)
    den_count = {sid: {"D": 0, "E": 0, "N": 0} for sid in staff if sid != "A1"}

    # N 규칙 상태
    N_MAX_PER_MONTH = 7
    N_BLOCK_MIN = 2
    N_BLOCK_MAX = 3
    n_used = {sid: 0 for sid in staff if sid != "A1"}
    n_block_left = {sid: 0 for sid in staff if sid != "A1"}
    next_n_allowed_day = {sid: 0 for sid in staff if sid != "A1"}  # 블럭 시작 간격(시작 기준 7일)
    post_n_rest = {sid: 0 for sid in staff if sid != "A1"}          # 2 -> OF(첫째날), 1 -> OF(둘째날 원칙, 부족시 E)

    # “주당 OF 2개(마지막 주 0~2 허용)”을 위한 OFF 계획(생성 우선순위는 낮게 둠)
    # - 실제 배치는 인력(D/E/N 슬롯)이 우선
    # - 그래도 가능한 범위에서 OF를 먼저 주기 위한 “목표”로 사용
    #   (검증은 validate에서 경고로 확인)
    # 캘린더 주(월~일)로 날짜 인덱스 묶기
    week_to_indices: Dict[Tuple[int, int], List[int]] = {}
    for i in range(days):
        dd = (start + timedelta(days=i)).date()
        wk = (dd.isocalendar().year, dd.isocalendar().week)
        week_to_indices.setdefault(wk, []).append(i)
    ordered_weeks = list(week_to_indices.keys())
    ordered_weeks.sort()

    # staff별 off_target_idx: 주마다 2개(마지막 주는 0~2), 총합이 weekend_days가 되도록 “목표” 구성
    off_target_idx: Dict[str, set] = {sid: set() for sid in staff if sid != "A1"}
    for sid in list(off_target_idx.keys()):
        remaining = weekend_days
        for wi, wk in enumerate(ordered_weeks):
            idxs = week_to_indices[wk]
            is_last = (wi == len(ordered_weeks) - 1)

            if is_last:
                need = min(2, remaining)  # 마지막 주 0~2
            else:
                need = 2 if remaining >= 2 else 0

            if need <= 0:
                continue

            # 결정론: sid와 wk 기반으로 idxs에서 분산 선택
            # (가능하면 서로 다른 요일로)
            pick_positions = []
            base = (sum(ord(c) for c in sid) + wk[0] + wk[1]) % max(1, len(idxs))
            for k in range(len(idxs)):
                pos = (base + k) % len(idxs)
                if pos not in pick_positions:
                    pick_positions.append(pos)
                if len(pick_positions) >= need:
                    break

            for pos in pick_positions:
                off_target_idx[sid].add(idxs[pos])

            remaining -= need
            if remaining <= 0:
                break

    assignments: List[Dict[str, Any]] = []

    # 메인 루프
    for day_idx in range(days):
        d = date_list[day_idx]
        dd = (start + timedelta(days=day_idx)).date()
        weekday = dd.weekday()  # 0=월..6=일
        wk = (dd.isocalendar().year, dd.isocalendar().week)

        # 필요 인원(일반직원용)
        if weekday <= 4:
            D_NEED, E_NEED, N_NEED = 1, 2, 2
        else:
            D_NEED, E_NEED, N_NEED = 2, 2, 2

        # 오늘 슬롯(일반직원용)
        slots = (["D"] * D_NEED) + (["E"] * E_NEED) + (["N"] * N_NEED)

        for sid in staff:
            key = (d, sid)

            # 1) 고정 우선(EDU/PL/BL)
            if key in locked_map:
                st = locked_map[key]
                assignments.append({
                    "date": d,
                    "staff_id": sid,
                    "shift_type": st,
                    "is_locked": True,
                    "generated_run_id": f"run_{req.month}"
                })
                # 근무일 카운트(EDU 포함)
                add_workday(sid, wk)
                # D/E/N 공평 카운트 및 N 카운트(고정 N은 여기서 안 씀)
                if sid != "A1" and st in ("D", "E", "N"):
                    den_count[sid][st] += 1
                    if st == "N":
                        n_used[sid] += 1
                        post_n_rest[sid] = 2
                        next_n_allowed_day[sid] = max(next_n_allowed_day[sid], day_idx + 7)
                continue

            # 2) A1: 평일 A1 / 주말 OF
            if sid == "A1":
                st = "A1" if weekday <= 4 else "OF"
                assignments.append({
                    "date": d,
                    "staff_id": sid,
                    "shift_type": st,
                    "is_locked": False,
                    "generated_run_id": f"run_{req.month}"
                })
                add_workday(sid, wk) if st != "OF" else None
                continue

            # 3) N블럭 후 휴식(원칙 OF-OF, 둘째날만 E 예외)
            if post_n_rest[sid] == 2:
                post_n_rest[sid] = 1
                st = "OF"
                assignments.append({
                    "date": d,
                    "staff_id": sid,
                    "shift_type": st,
                    "is_locked": False,
                    "generated_run_id": f"run_{req.month}"
                })
                continue

            if post_n_rest[sid] == 1:
                # 둘째날: 원칙 OF. 정말로 슬롯이 부족할 때만 E 허용
                # (간단 안전형) E가 남아있고, D/N이 없을 때만 E로 대체
                if ("E" in slots) and ("D" not in slots) and ("N" not in slots):
                    st = "E"
                    slots.remove("E")
                    den_count[sid]["E"] += 1
                    add_workday(sid, wk)
                else:
                    st = "OF"
                post_n_rest[sid] = 0
                assignments.append({
                    "date": d,
                    "staff_id": sid,
                    "shift_type": st,
                    "is_locked": False,
                    "generated_run_id": f"run_{req.month}"
                })
                continue

            # 4) (목표) 주당 OF 2개를 먼저 주기
            #    단, 슬롯이 너무 부족하면 인력 배치가 우선이므로 아래에서 D/E/N로 배치될 수 있음
            if sid in off_target_idx and day_idx in off_target_idx[sid]:
                # OF 주고 넘어감(다만, N 슬롯이 정말 부족하면 아래 로직에서 채워야 하는데
                # MVP에서는 "OF 우선"으로 단순 처리)
                st = "OF"
                assignments.append({
                    "date": d,
                    "staff_id": sid,
                    "shift_type": st,
                    "is_locked": False,
                    "generated_run_id": f"run_{req.month}"
                })
                continue

            # 5) N 블럭 진행 중
            if n_block_left[sid] > 0 and ("N" in slots) and (n_used[sid] < N_MAX_PER_MONTH):
                st = "N"
                slots.remove("N")
                den_count[sid]["N"] += 1
                n_used[sid] += 1
                n_block_left[sid] -= 1
                add_workday(sid, wk)

                if n_block_left[sid] == 0:
                    post_n_rest[sid] = 2  # OF-OF
                assignments.append({
                    "date": d,
                    "staff_id": sid,
                    "shift_type": st,
                    "is_locked": False,
                    "generated_run_id": f"run_{req.month}"
                })
                continue

            # 6) 새 N 블럭 시작 (2~3), 블럭 시작 간격 7일
            can_start_n = (
                ("N" in slots)
                and n_block_left[sid] == 0
                and (n_used[sid] < N_MAX_PER_MONTH)
                and (day_idx >= next_n_allowed_day[sid])
            )
            if can_start_n:
                desired = N_BLOCK_MIN if ((n_used[sid] + day_idx) % 2 == 0) else N_BLOCK_MAX
                remaining = N_MAX_PER_MONTH - n_used[sid]
                block_len = min(desired, remaining)

                if block_len >= 2:
                    st = "N"
                    slots.remove("N")
                    den_count[sid]["N"] += 1
                    n_used[sid] += 1
                    n_block_left[sid] = block_len - 1
                    next_n_allowed_day[sid] = day_idx + 7
                    add_workday(sid, wk)

                    assignments.append({
                        "date": d,
                        "staff_id": sid,
                        "shift_type": st,
                        "is_locked": False,
                        "generated_run_id": f"run_{req.month}"
                    })
                    continue

            # 7) D/E 공평하게 채우기 (월 기준), 없으면 OF
            st = "OF"
            if sid != "A1":
                # 주 5일 상한(가능하면 지키기)
                if get_workday(sid, wk) >= 5:
                    st = "OF"
                else:
                    if ("D" in slots) and ("E" in slots):
                        st = "D" if den_count[sid]["D"] <= den_count[sid]["E"] else "E"
                    elif "D" in slots:
                        st = "D"
                    elif "E" in slots:
                        st = "E"
                    elif "N" in slots:
                        # N은 위에서 처리됐지만, 혹시 남았으면 마지막 수단으로
                        st = "N"

                    if st in slots:
                        slots.remove(st)

                    if st in ("D", "E", "N"):
                        den_count[sid][st] += 1
                        add_workday(sid, wk)

            assignments.append({
                "date": d,
                "staff_id": sid,
                "shift_type": st,
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
    
