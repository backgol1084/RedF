import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

import streamlit as st
from streamlit.components.v1 import html
from supabase import Client, create_client

st.set_page_config(
    page_title="RedF",
    page_icon="🏷️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# 1. Supabase 클라이언트 초기화
# ---------------------------------------------------------------------------
@st.cache_resource
def init_supabase() -> Client:
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)


supabase = init_supabase()


# ---------------------------------------------------------------------------
# 2. 모바일 / PC 판별 및 페이지 전환 상태 관리
# ---------------------------------------------------------------------------
def detect_is_mobile() -> bool:
    """쿼리 파라미터 또는 브라우저 요청 헤더(User-Agent)로 모바일 여부를 판별합니다."""
    qp_device = st.query_params.get("device", "").lower()
    if qp_device == "mobile":
        return True
    if qp_device == "desktop" or qp_device == "pc":
        return False

    ua = ""
    try:
        headers = getattr(st.context, "headers", None)
        if headers:
            ua = (headers.get("User-Agent") or "").lower()
    except Exception:
        ua = ""

    mobile_keywords = [
        "android",
        "iphone",
        "ipad",
        "ipod",
        "mobile",
        "webos",
        "blackberry",
        "windows phone",
    ]
    return any(k in ua for k in mobile_keywords)


is_mobile = detect_is_mobile()

if "page" not in st.session_state:
    # 모바일은 첫 페이지(인수/반품/조회 메뉴), PC는 바로 조회 페이지
    st.session_state.page = "home" if is_mobile else "lookup"

if "pending_delete_id" not in st.session_state:
    st.session_state.pending_delete_id = None

if "last_scanned_code" not in st.session_state:
    st.session_state.last_scanned_code = ""


def go_to(target_page: str) -> None:
    st.session_state.page = target_page
    st.session_state.pending_delete_id = None
    st.rerun()


# ---------------------------------------------------------------------------
# 3. 페이지별 배경색 및 버튼 스타일 적용
# ---------------------------------------------------------------------------
def apply_theme(page_name: str) -> None:
    bg_map = {
        "home": "#F8FAFC",
        "inbound": "#E0F2FE",   # 인수: 하늘색
        "return": "#FCE7F3",    # 반품: 연한 핑크색
        "lookup": "#FFFFFF",    # 조회: 하얀색
    }
    bg_color = bg_map.get(page_name, "#FFFFFF")

    st.markdown(
        f"""
        <style>
            .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {{
                background-color: {bg_color} !important;
            }}
            .block-container {{
                padding-top: 1.5rem;
                padding-bottom: 3rem;
            }}
            /* 홈 화면 메인 버튼 스타일 */
            .redf-btn-inbound button {{
                background-color: #2563EB !important;
                color: #FFFFFF !important;
                border: none !important;
                font-size: 1.25rem !important;
                font-weight: 700 !important;
                height: 4.5rem !important;
                border-radius: 14px !important;
            }}
            .redf-btn-inbound button:hover {{
                background-color: #1D4ED8 !important;
            }}
            .redf-btn-return button {{
                background-color: #DC2626 !important;
                color: #FFFFFF !important;
                border: none !important;
                font-size: 1.25rem !important;
                font-weight: 700 !important;
                height: 4.5rem !important;
                border-radius: 14px !important;
            }}
            .redf-btn-return button:hover {{
                background-color: #B91C1C !important;
            }}
            .redf-btn-lookup button {{
                background-color: #FACC15 !important;
                color: #111827 !important;
                border: none !important;
                font-size: 1.25rem !important;
                font-weight: 700 !important;
                height: 4.5rem !important;
                border-radius: 14px !important;
            }}
            .redf-btn-lookup button:hover {{
                background-color: #EAB308 !important;
            }}
            .item-card {{
                background-color: rgba(255, 255, 255, 0.88);
                border: 1px solid #E5E7EB;
                border-radius: 12px;
                padding: 0.9rem 1rem;
                margin-bottom: 0.65rem;
            }}
        </style>
        """,
        unsafe_allow_html=True,
    )


apply_theme(st.session_state.page)


# ---------------------------------------------------------------------------
# 4. 상품택 파싱 및 Supabase CRUD 함수
# ---------------------------------------------------------------------------
def parse_tag_payload(raw_text: str) -> dict[str, Any]:
    """
    상품택(QR/바코드/텍스트) 문자열을 품명, 규격, 색상, 수량으로 파싱합니다.
    지원 형식 예시:
      1) JSON: {"item_name":"후드집업","spec":"L","color":"블랙","qty":1}
      2) 파이프/슬래시/콤마 구분: 후드집업|L|블랙|1 또는 후드집업/L/블랙
      3) 단일 코드/텍스트: TAG-1001 -> 품명=TAG-1001, 규격=기본, 색상=미지정, 수량=1
    """
    cleaned = raw_text.strip()
    if not cleaned:
        raise ValueError("인식된 택 데이터가 비어 있습니다.")

    # 1) JSON 형식 시도
    if cleaned.startswith("{") and cleaned.endswith("}"):
        data = json.loads(cleaned)
        qty_val = int(data.get("qty") or data.get("quantity") or data.get("수량") or 1)
        return {
            "tag_code": str(data.get("tag_code") or data.get("code") or cleaned),
            "item_name": str(data.get("item_name") or data.get("name") or data.get("품명") or cleaned),
            "spec": str(data.get("spec") or data.get("size") or data.get("규격") or "기본"),
            "color": str(data.get("color") or data.get("색상") or "미지정"),
            "qty": max(1, qty_val),
        }

    # 2) 구분자(|, /, ,) 기반 파싱
    for sep in ["|", "/", ","]:
        if sep in cleaned:
            parts = [p.strip() for p in cleaned.split(sep)]
            item_name = parts[0] if len(parts) >= 1 and parts[0] else cleaned
            spec = parts[1] if len(parts) >= 2 and parts[1] else "기본"
            color = parts[2] if len(parts) >= 3 and parts[2] else "미지정"
            qty = 1
            if len(parts) >= 4 and re.fullmatch(r"\d+", parts[3]):
                qty = max(1, int(parts[3]))
            return {
                "tag_code": cleaned,
                "item_name": item_name,
                "spec": spec,
                "color": color,
                "qty": qty,
            }

    # 3) 일반 문자열/바코드
    return {
        "tag_code": cleaned,
        "item_name": cleaned,
        "spec": "기본",
        "color": "미지정",
        "qty": 1,
    }


def fetch_records(tx_type: Optional[str] = None) -> list[dict[str, Any]]:
    query = supabase.table("redf_transactions").select("*")
    if tx_type:
        query = query.eq("tx_type", tx_type)
    res = query.order("id", desc=True).execute()
    return res.data or []


def save_scanned_tag(tx_type: str, raw_payload: str) -> tuple[bool, str]:
    """
    상품택 인식 시 자동으로 DB에 저장합니다.
    동일 구분(인수/반품) 내 동일한 (품명, 규격, 색상) 항목이 있으면 수량을 +1 누적하고,
    없으면 새 행으로 저장합니다.
    """
    try:
        parsed = parse_tag_payload(raw_payload)
    except Exception as exc:
        return False, f"택 데이터 해석 오류: {exc}"

    try:
        existing = (
            supabase.table("redf_transactions")
            .select("*")
            .eq("tx_type", tx_type)
            .eq("item_name", parsed["item_name"])
            .eq("spec", parsed["spec"])
            .eq("color", parsed["color"])
            .limit(1)
            .execute()
        )

        if existing.data:
            row = existing.data[0]
            new_qty = int(row.get("qty") or 0) + int(parsed["qty"])
            supabase.table("redf_transactions").update(
                {
                    "qty": new_qty,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            ).eq("id", row["id"]).execute()
            return True, f"인식 완료(수량 +{parsed['qty']}): {parsed['item_name']} ({parsed['spec']} / {parsed['color']}) → 총 {new_qty}개"

        supabase.table("redf_transactions").insert(
            {
                "tx_type": tx_type,  # 'inbound' | 'return'
                "tag_code": parsed["tag_code"],
                "item_name": parsed["item_name"],
                "spec": parsed["spec"],
                "color": parsed["color"],
                "qty": parsed["qty"],
            }
        ).execute()
        return True, f"자동 저장 완료: {parsed['item_name']} ({parsed['spec']} / {parsed['color']}) · {parsed['qty']}개"
    except Exception as exc:
        return False, f"DB 저장 중 오류가 발생했습니다: {exc}"


def update_qty(record_id: int, delta: int) -> None:
    res = (
        supabase.table("redf_transactions")
        .select("qty")
        .eq("id", record_id)
        .single()
        .execute()
    )
    current_qty = int((res.data or {}).get("qty") or 0)
    next_qty = max(0, current_qty + delta)
    supabase.table("redf_transactions").update(
        {
            "qty": next_qty,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", record_id).execute()


def delete_record(record_id: int) -> None:
    supabase.table("redf_transactions").delete().eq("id", record_id).execute()


# ---------------------------------------------------------------------------
# 5. 카메라 상품택 자동 인식 컴포넌트 (셔터 없이 인식 시 자동 전송)
# ---------------------------------------------------------------------------
def render_camera_scanner(tx_type: str) -> None:
    """
    상단 카메라 영역:
    - BarcodeDetector(지원 브라우저) 및 비디오 프레임 스캔으로 택 인식 시
      촬영 버튼 없이 자동으로 쿼리 파라미터(`scan_payload`, `scan_nonce`)를 갱신해 DB에 저장합니다.
    - 카메라 권한 불가/미지원 환경 또는 테스트를 위한 즉시 인식 입력창도 함께 제공합니다.
    """
    st.markdown("#### 📷 상품택 자동 인식 카메라")
    st.caption("카메라에 상품택을 비추면 촬영 버튼을 누르지 않아도 자동으로 인식되어 저장됩니다.")

    scanner_html = """
    <div style="background:#111827;color:#F9FAFB;padding:12px;border-radius:12px;">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;gap:8px;flex-wrap:wrap;">
        <span id="cam-status" style="font-size:0.9rem;">카메라 시작 대기 중...</span>
        <div>
          <button id="btn-start-cam" type="button" style="padding:6px 12px;border-radius:8px;border:none;background:#2563EB;color:#fff;cursor:pointer;font-weight:600;">카메라 켜기</button>
          <button id="btn-stop-cam" type="button" style="padding:6px 12px;border-radius:8px;border:none;background:#4B5563;color:#fff;cursor:pointer;font-weight:600;">끄기</button>
        </div>
      </div>
      <video id="redf-video" autoplay playsinline muted style="width:100%;max-height:280px;object-fit:cover;border-radius:10px;background:#000;"></video>
      <canvas id="redf-canvas" style="display:none;"></canvas>
    </div>

    <script>
      (function() {
        const video = document.getElementById("redf-video");
        const canvas = document.getElementById("redf-canvas");
        const statusEl = document.getElementById("cam-status");
        const startBtn = document.getElementById("btn-start-cam");
        const stopBtn = document.getElementById("btn-stop-cam");

        let stream = null;
        let scanTimer = null;
        let lastDetected = "";
        let lastDetectedTime = 0;

        const hasBarcodeDetector = ("BarcodeDetector" in window);
        let detector = null;
        if (hasBarcodeDetector) {
          try {
            detector = new window.BarcodeDetector({
              formats: ["qr_code", "code_128", "code_39", "ean_13", "ean_8", "upc_a", "upc_e", "data_matrix"]
            });
          } catch (e) {
            detector = null;
          }
        }

        function triggerAutoSave(codeValue) {
          const trimmed = (codeValue || "").trim();
          if (!trimmed) return;
          const now = Date.now();
          // 동일 코드 중복 연속 인식 방지(1.8초 쿨다운)
          if (trimmed === lastDetected && (now - lastDetectedTime) < 1800) return;
          lastDetected = trimmed;
          lastDetectedTime = now;

          statusEl.textContent = "택 자동 인식됨: " + trimmed + " (저장 중...)";

          const parentUrl = new URL(window.parent.location.href);
          parentUrl.searchParams.set("scan_payload", trimmed);
          parentUrl.searchParams.set("scan_nonce", String(now));
          window.parent.history.replaceState({}, "", parentUrl.toString());
          window.parent.location.assign(parentUrl.toString());
        }

        async function scanLoop() {
          if (!stream || video.readyState < 2) return;
          if (detector) {
            try {
              const barcodes = await detector.detect(video);
              if (barcodes && barcodes.length > 0 && barcodes[0].rawValue) {
                triggerAutoSave(barcodes[0].rawValue);
              }
            } catch (err) {
              // 프레임 인식 실패는 무시하고 계속 스캔
            }
          }
        }

        async function startCamera() {
          try {
            if (stream) return;
            stream = await navigator.mediaDevices.getUserMedia({
              video: { facingMode: { ideal: "environment" } },
              audio: false
            });
            video.srcObject = stream;
            statusEl.textContent = detector
              ? "카메라 실행 중 — 상품택을 비추면 자동 인식됩니다."
              : "카메라 실행 중 — 아래 빠른 인식/스캐너 입력도 함께 사용할 수 있습니다.";
            if (scanTimer) clearInterval(scanTimer);
            scanTimer = setInterval(scanLoop, 450);
          } catch (err) {
            statusEl.textContent = "카메라 접근이 차단되었거나 장치를 찾을 수 없습니다: " + err.message;
          }
        }

        function stopCamera() {
          if (scanTimer) {
            clearInterval(scanTimer);
            scanTimer = null;
          }
          if (stream) {
            stream.getTracks().forEach(t => t.stop());
            stream = null;
          }
          video.srcObject = null;
          statusEl.textContent = "카메라가 꺼져 있습니다.";
        }

        startBtn.addEventListener("click", startCamera);
        stopBtn.addEventListener("click", stopCamera);

        // 페이지 진입 시 카메라 자동 시작 시도
        startCamera();
      })();
    </script>
    """
    html(scanner_html, height=365)

    # 카메라 스캐너 URL 파라미터 자동 처리
    scan_payload = st.query_params.get("scan_payload", "")
    scan_nonce = st.query_params.get("scan_nonce", "")
    if scan_payload and scan_nonce and scan_nonce != st.session_state.last_scanned_code:
        st.session_state.last_scanned_code = scan_nonce
        ok, msg = save_scanned_tag(tx_type, scan_payload)
        # 중복 트리거 방지를 위해 쿼리 파라미터 정리
        try:
            del st.query_params["scan_payload"]
            del st.query_params["scan_nonce"]
        except Exception:
            pass
        if ok:
            st.success(msg)
        else:
            st.error(msg)
        st.rerun()

    # 수동/바코드스캐너/테스트용 빠른 택 입력 (예: 품명|규격|색상|수량)
    with st.expander("택 문자열 빠른 입력 / 테스트 (카메라 대체용)", expanded=False):
        quick_val = st.text_input(
            "택 데이터 입력 (예: 베이직반팔|L|화이트|1 또는 TAG-001)",
            key=f"quick_tag_{tx_type}",
            placeholder="품명|규격|색상|수량 또는 택코드",
        )
        if st.button("이 택 값으로 즉시 인식 저장", key=f"btn_quick_{tx_type}"):
            if quick_val.strip():
                ok, msg = save_scanned_tag(tx_type, quick_val.strip())
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
            else:
                st.warning("택 데이터를 입력해 주세요.")


# ---------------------------------------------------------------------------
# 6. 인수 / 반품 공통 상세 페이지
# ---------------------------------------------------------------------------
def render_transaction_detail_page(tx_type: str) -> None:
    is_inbound = tx_type == "inbound"
    title_text = "인수 상세" if is_inbound else "반품 상세"
    badge_color = "#2563EB" if is_inbound else "#DC2626"

    top_left, top_right = st.columns([1, 5])
    with top_left:
        if st.button("← 뒤로가기", key=f"back_{tx_type}"):
            go_to("home" if is_mobile else "lookup")
    with top_right:
        st.markdown(
            f"<h2 style='margin:0;color:{badge_color};'>🏷️ RedF — {title_text}</h2>",
            unsafe_allow_html=True,
        )

    st.divider()

    # 상단: 카메라 자동 인식 영역
    render_camera_scanner(tx_type)

    st.divider()

    # 하단: 인식된 제품 리스트 (품명, 규격, 색상, 수량 + 업/다운/삭제)
    st.markdown(f"#### 📋 {title_text} 제품 리스트")
    rows = fetch_records(tx_type=tx_type)

    if not rows:
        st.info(f"아직 인식된 {title_text} 제품이 없습니다. 상단 카메라에 상품택을 비춰주세요.")
        return

    for row in rows:
        rec_id = row["id"]
        item_name = row.get("item_name", "-")
        spec = row.get("spec", "-")
        color = row.get("color", "-")
        qty = int(row.get("qty") or 0)

        st.markdown("<div class='item-card'>", unsafe_allow_html=True)
        c_info, c_up, c_down, c_del = st.columns([5, 1, 1, 1.4])

        with c_info:
            st.markdown(f"**품명:** {item_name}")
            st.markdown(
                f"규격: `{spec}` &nbsp;|&nbsp; 색상: `{color}` &nbsp;|&nbsp; **수량: {qty}**"
            )

        with c_up:
            if st.button("▲", key=f"up_{tx_type}_{rec_id}", help="수량 증가"):
                update_qty(rec_id, 1)
                st.rerun()

        with c_down:
            if st.button("▼", key=f"down_{tx_type}_{rec_id}", help="수량 감소"):
                update_qty(rec_id, -1)
                st.rerun()

        with c_del:
            if st.button("삭제", key=f"del_ask_{tx_type}_{rec_id}"):
                st.session_state.pending_delete_id = rec_id
                st.rerun()

        # 삭제 확인 팝업/프롬프트
        if st.session_state.pending_delete_id == rec_id:
            st.warning(
                f"**'{item_name}' ({spec} / {color})** 항목을 정말 삭제하시겠습니까?"
            )
            conf_col1, conf_col2, _ = st.columns([1.2, 1.2, 4])
            with conf_col1:
                if st.button("예, 삭제합니다", key=f"del_yes_{tx_type}_{rec_id}", type="primary"):
                    delete_record(rec_id)
                    st.session_state.pending_delete_id = None
                    st.success("삭제되었습니다.")
                    st.rerun()
            with conf_col2:
                if st.button("아니오", key=f"del_no_{tx_type}_{rec_id}"):
                    st.session_state.pending_delete_id = None
                    st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 7. 모바일 첫 페이지 (인수: 파랑, 반품: 빨강, 조회: 노랑)
# ---------------------------------------------------------------------------
def render_mobile_home_page() -> None:
    st.markdown("<h1 style='text-align:center;margin-bottom:0.25rem;'>RedF</h1>", unsafe_allow_html=True)
    st.markdown(
        "<p style='text-align:center;color:#4B5563;margin-bottom:2rem;'>원하시는 작업을 선택해 주세요.</p>",
        unsafe_allow_html=True,
    )

    st.markdown("<div class='redf-btn-inbound'>", unsafe_allow_html=True)
    if st.button("인수", key="home_btn_inbound", use_container_width=True):
        go_to("inbound")
    st.markdown("</div>", unsafe_allow_html=True)

    st.write("")

    st.markdown("<div class='redf-btn-return'>", unsafe_allow_html=True)
    if st.button("반품", key="home_btn_return", use_container_width=True):
        go_to("return")
    st.markdown("</div>", unsafe_allow_html=True)

    st.write("")

    st.markdown("<div class='redf-btn-lookup'>", unsafe_allow_html=True)
    if st.button("조회", key="home_btn_lookup", use_container_width=True):
        go_to("lookup")
    st.markdown("</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 8. 조회 페이지 (PC 기본 진입 화면 / 모바일에서도 선택 가능)
# ---------------------------------------------------------------------------
def render_lookup_page() -> None:
    header_l, header_r = st.columns([4, 2])
    with header_l:
        st.markdown("<h2 style='margin:0;color:#111827;'>🔎 RedF 조회</h2>", unsafe_allow_html=True)
        st.caption("인수 및 반품 내역을 조회하고 수량을 관리할 수 있습니다.")
    with header_r:
        if is_mobile:
            if st.button("처음 메뉴로", key="lookup_to_home", use_container_width=True):
                go_to("home")
        else:
            nav_c1, nav_c2 = st.columns(2)
            with nav_c1:
                if st.button("인수 이동", key="pc_to_inbound", use_container_width=True):
                    go_to("inbound")
            with nav_c2:
                if st.button("반품 이동", key="pc_to_return", use_container_width=True):
                    go_to("return")

    st.divider()

    all_rows = fetch_records(tx_type=None)

    inbound_qty = sum(
        int(r.get("qty") or 0) for r in all_rows if r.get("tx_type") == "inbound"
    )
    return_qty = sum(
        int(r.get("qty") or 0) for r in all_rows if r.get("tx_type") == "return"
    )

    m1, m2, m3 = st.columns(3)
    m1.metric("총 등록 건수", f"{len(all_rows)}건")
    m2.metric("총 인수 수량", f"{inbound_qty}개")
    m3.metric("총 반품 수량", f"{return_qty}개")

    st.write("")

    f1, f2, f3 = st.columns([2, 2, 4])
    with f1:
        type_filter = st.selectbox(
            "구분",
            options=["전체", "인수", "반품"],
            index=0,
        )
    with f2:
        color_options = ["전체"] + sorted(
            {str(r.get("color") or "미지정") for r in all_rows}
        )
        color_filter = st.selectbox("색상", options=color_options, index=0)
    with f3:
        search_text = st.text_input("검색 (품명 / 규격 / 택코드)", placeholder="검색어를 입력하세요")

    filtered = []
    for r in all_rows:
        r_type_kr = "인수" if r.get("tx_type") == "inbound" else "반품"
        if type_filter != "전체" and r_type_kr != type_filter:
            continue
        r_color = str(r.get("color") or "미지정")
        if color_filter != "전체" and r_color != color_filter:
            continue
        if search_text.strip():
            q = search_text.strip().lower()
            haystack = " ".join(
                [
                    str(r.get("item_name") or ""),
                    str(r.get("spec") or ""),
                    str(r.get("color") or ""),
                    str(r.get("tag_code") or ""),
                ]
            ).lower()
            if q not in haystack:
                continue
        filtered.append(r)

    st.markdown(f"#### 조회 결과 ({len(filtered)}건)")

    if not filtered:
        st.info("조건에 맞는 조회 데이터가 없습니다.")
        return

    display_table = [
        {
            "구분": "인수" if r.get("tx_type") == "inbound" else "반품",
            "품명": r.get("item_name", "-"),
            "규격": r.get("spec", "-"),
            "색상": r.get("color", "-"),
            "수량": int(r.get("qty") or 0),
            "택코드": r.get("tag_code", "-"),
        }
        for r in filtered
    ]
    st.dataframe(display_table, use_container_width=True, hide_index=True)

    with st.expander("항목별 수량 조절 및 삭제", expanded=False):
        for r in filtered:
            rec_id = r["id"]
            r_type_kr = "인수" if r.get("tx_type") == "inbound" else "반품"
            c1, c2, c3, c4 = st.columns([5, 1, 1, 1.4])
            with c1:
                st.write(
                    f"**[{r_type_kr}] {r.get('item_name')}** — 규격: `{r.get('spec')}` / 색상: `{r.get('color')}` / 수량: **{r.get('qty')}**"
                )
            with c2:
                if st.button("▲", key=f"lk_up_{rec_id}"):
                    update_qty(rec_id, 1)
                    st.rerun()
            with c3:
                if st.button("▼", key=f"lk_dn_{rec_id}"):
                    update_qty(rec_id, -1)
                    st.rerun()
            with c4:
                if st.button("삭제", key=f"lk_del_{rec_id}"):
                    st.session_state.pending_delete_id = rec_id
                    st.rerun()

            if st.session_state.pending_delete_id == rec_id:
                st.warning(f"'{r.get('item_name')}' 항목을 정말 삭제하시겠습니까?")
                y_col, n_col, _ = st.columns([1.2, 1.2, 4])
                with y_col:
                    if st.button("예, 삭제합니다", key=f"lk_yes_{rec_id}", type="primary"):
                        delete_record(rec_id)
                        st.session_state.pending_delete_id = None
                        st.rerun()
                with n_col:
                    if st.button("아니오", key=f"lk_no_{rec_id}"):
                        st.session_state.pending_delete_id = None
                        st.rerun()


# ---------------------------------------------------------------------------
# 9. 페이지 라우터
# ---------------------------------------------------------------------------
current_page = st.session_state.page

if current_page == "home":
    render_mobile_home_page()
elif current_page == "inbound":
    render_transaction_detail_page("inbound")
elif current_page == "return":
    render_transaction_detail_page("return")
else:
    render_lookup_page()
