import base64
import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

import requests
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


def get_gemini_api_key() -> str:
    try:
        return str(st.secrets["gemini"]["api_key"] or "").strip()
    except Exception:
        return ""


supabase = init_supabase()


# ---------------------------------------------------------------------------
# 2. 모바일 / PC 판별 및 페이지 전환 상태 관리
# ---------------------------------------------------------------------------
def detect_is_mobile() -> bool:
    qp_device = st.query_params.get("device", "").lower()
    if qp_device == "mobile":
        return True
    if qp_device in ("desktop", "pc"):
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
    st.session_state.page = "home" if is_mobile else "lookup"

if "pending_delete_id" not in st.session_state:
    st.session_state.pending_delete_id = None

if "last_scan_nonce" not in st.session_state:
    st.session_state.last_scan_nonce = ""

if "play_ding" not in st.session_state:
    st.session_state.play_ding = False

if "ding_nonce" not in st.session_state:
    st.session_state.ding_nonce = 0


def trigger_ding() -> None:
    st.session_state.play_ding = True
    st.session_state.ding_nonce += 1


def render_ding_if_needed() -> None:
    if not st.session_state.get("play_ding"):
        return

    nonce = st.session_state.get("ding_nonce", 0)
    st.session_state.play_ding = False

    ding_html = f"""
    <div id="ding-marker-{nonce}" style="display:none;"></div>
    <script>
      (function() {{
        try {{
          const AudioCtx = window.AudioContext || window.webkitAudioContext;
          if (!AudioCtx) return;
          const ctx = new AudioCtx();
          const now = ctx.currentTime;

          const osc1 = ctx.createOscillator();
          const osc2 = ctx.createOscillator();
          const gain = ctx.createGain();

          osc1.type = "sine";
          osc2.type = "triangle";

          osc1.frequency.setValueAtTime(880, now);
          osc1.frequency.exponentialRampToValueAtTime(1174.66, now + 0.08);

          osc2.frequency.setValueAtTime(1760, now);
          osc2.frequency.exponentialRampToValueAtTime(2349.32, now + 0.08);

          gain.gain.setValueAtTime(0.001, now);
          gain.gain.linearRampToValueAtTime(0.28, now + 0.015);
          gain.gain.exponentialRampToValueAtTime(0.0008, now + 0.55);

          osc1.connect(gain);
          osc2.connect(gain);
          gain.connect(ctx.destination);

          osc1.start(now);
          osc2.start(now);
          osc1.stop(now + 0.58);
          osc2.stop(now + 0.58);

          osc1.onended = () => {{
            ctx.close().catch(() => {{}});
          }};
        }} catch (e) {{}}
      }})();
    </script>
    """
    html(ding_html, height=0)


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
                padding-top: 0.85rem;
                padding-bottom: 2rem;
            }}
            hr {{
                margin-top: 0.55rem !important;
                margin-bottom: 0.55rem !important;
            }}
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
                background-color: rgba(255, 255, 255, 0.94);
                border: 1px solid #E5E7EB;
                border-radius: 10px;
                padding: 0.65rem 0.85rem;
                margin-bottom: 0.5rem;
            }}
        </style>
        """,
        unsafe_allow_html=True,
    )


apply_theme(st.session_state.page)


# ---------------------------------------------------------------------------
# 4. 택 이미지 / 텍스트 분석 (품명, 품번, 색상, 치수) 및 Supabase CRUD
# ---------------------------------------------------------------------------
def _clean_val(val: Any, fallback: str) -> str:
    s = re.sub(r"\s+", " ", str(val or "")).strip(" :·.-")
    return s if s else fallback


def analyze_tag_image_with_gemini(jpeg_b64: str, api_key: str) -> dict[str, Any]:
    """임시 캡처 이미지(base64 JPEG)를 Gemini로 분석해 품명, 품번, 색상, 치수를 추출합니다."""
    endpoint = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.5-flash:generateContent?key={api_key}"
    )
    prompt = (
        "이 의류 상품택 이미지에서 '품명', '품번', '색상', '치수'를 정확히 읽어서 "
        "JSON 객체로만 답하세요. 다른 설명이나 마크다운 코드블록은 쓰지 마세요.\n"
        "키 이름: item_name, item_code, color, size_val\n"
        "치수에 '100 (90~110)'처럼 표기된 경우 대표 치수(예: '100')를 넣으세요. "
        "읽을 수 없는 항목은 빈 문자열 ''로 두세요."
    )
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": jpeg_b64,
                        }
                    },
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }

    resp = requests.post(endpoint, json=payload, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    text_out = (
        data.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [{}])[0]
        .get("text", "")
    ).strip()

    # 혹시 감싸진 코드블록 제거
    text_out = re.sub(r"^```(?:json)?\s*|\s*```$", "", text_out, flags=re.IGNORECASE).strip()
    parsed = json.loads(text_out)

    item_name = _clean_val(parsed.get("item_name"), "")
    item_code = _clean_val(parsed.get("item_code"), "")
    color = _clean_val(parsed.get("color"), "미지정")
    size_val = _clean_val(parsed.get("size_val"), "미지정")

    if not item_name and not item_code:
        raise ValueError("택에서 품명이나 품번을 읽지 못했습니다.")

    final_name = item_name or item_code
    final_code = item_code or "미기재"

    return {
        "item_name": final_name,
        "item_code": final_code,
        "color": color,
        "size_val": size_val,
        "qty": 1,
        "tag_code": final_code if final_code != "미기재" else final_name[:50],
    }


def parse_redf_tag_text(raw_text: str) -> dict[str, Any]:
    cleaned = raw_text.strip()
    if not cleaned:
        raise ValueError("인식된 택 데이터가 비어 있습니다.")

    item_name = ""
    item_code = ""
    color = ""
    size_val = ""

    name_match = re.search(r"품\s*명\s*[:：\-]?\s*([^\n]+)", cleaned)
    if name_match:
        item_name = _clean_val(name_match.group(1), "")

    code_match = re.search(r"품\s*번\s*[:：\-]?\s*([A-Za-z0-9\-_]+)", cleaned)
    if code_match:
        item_code = _clean_val(code_match.group(1), "")

    color_match = re.search(r"색\s*상\s*[:：\-]?\s*([^\n]+)", cleaned)
    if color_match:
        color = _clean_val(color_match.group(1), "")

    size_match = re.search(
        r"치\s*수\s*[:：\-]?\s*([0-9]{2,3}(?:\s*[A-Za-z가-힣]+)?)", cleaned
    )
    if size_match:
        size_val = _clean_val(size_match.group(1), "")

    if not item_name and not item_code:
        raise ValueError("택에서 '품명' 또는 '품번'을 찾지 못했습니다.")

    final_name = item_name or item_code
    final_code = item_code or "미기재"

    return {
        "item_name": final_name,
        "item_code": final_code,
        "color": color or "미지정",
        "size_val": size_val or "미지정",
        "qty": 1,
        "tag_code": final_code if final_code != "미기재" else final_name[:50],
    }


def fetch_records(tx_type: Optional[str] = None) -> list[dict[str, Any]]:
    query = supabase.table("redf_transactions").select("*")
    if tx_type:
        query = query.eq("tx_type", tx_type)
    res = query.order("id", desc=True).execute()
    return res.data or []


def save_parsed_item(tx_type: str, parsed: dict[str, Any]) -> tuple[bool, str]:
    try:
        existing = (
            supabase.table("redf_transactions")
            .select("*")
            .eq("tx_type", tx_type)
            .eq("item_name", parsed["item_name"])
            .eq("item_code", parsed["item_code"])
            .eq("color", parsed["color"])
            .eq("size_val", parsed["size_val"])
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
            return (
                True,
                f"수량 +1: {parsed['item_name']} ({parsed['item_code']} / {parsed['color']} / {parsed['size_val']}) → {new_qty}개",
            )

        supabase.table("redf_transactions").insert(
            {
                "tx_type": tx_type,
                "tag_code": parsed["tag_code"],
                "item_name": parsed["item_name"],
                "item_code": parsed["item_code"],
                "spec": parsed["size_val"],
                "size_val": parsed["size_val"],
                "color": parsed["color"],
                "qty": parsed["qty"],
            }
        ).execute()
        return (
            True,
            f"저장 완료: {parsed['item_name']} ({parsed['item_code']} / {parsed['color']} / {parsed['size_val']})",
        )
    except Exception as exc:
        return False, f"DB 저장 오류: {exc}"


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
# 5. 적정 크기 카메라 (터치 시 임시 촬영 -> 분석 -> 저장 -> 임시사진 즉시 파기)
# ---------------------------------------------------------------------------
def render_camera_scanner(tx_type: str) -> None:
    gemini_key = get_gemini_api_key()

    scanner_html = """
    <div style="position:relative;width:100%;height:235px;background:#000;border-radius:12px;overflow:hidden;cursor:pointer;user-select:none;-webkit-tap-highlight-color:transparent;" id="tap-zone">
      <video id="cam-video" autoplay playsinline muted style="width:100%;height:100%;object-fit:cover;display:block;"></video>
      <canvas id="temp-canvas" style="display:none;"></canvas>
      <div id="cam-hint" style="position:absolute;bottom:8px;left:50%;transform:translateX(-50%);background:rgba(0,0,0,0.65);color:#fff;padding:4px 12px;border-radius:999px;font-size:0.78rem;white-space:nowrap;">
        택을 맞추고 화면을 터치하세요
      </div>
    </div>

    <script>
      (function() {
        const tapZone = document.getElementById("tap-zone");
        const video = document.getElementById("cam-video");
        const canvas = document.getElementById("temp-canvas");
        const hint = document.getElementById("cam-hint");

        let stream = null;
        let busy = false;

        async function startCam() {
          try {
            if (stream) return;
            stream = await navigator.mediaDevices.getUserMedia({
              video: {
                facingMode: { ideal: "environment" },
                width: { ideal: 1280 },
                height: { ideal: 720 }
              },
              audio: false
            });
            video.srcObject = stream;
          } catch (err) {
            hint.textContent = "카메라 권한을 허용해 주세요";
          }
        }

        function destroyTempPhoto() {
          try {
            const ctx = canvas.getContext("2d");
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            canvas.width = 1;
            canvas.height = 1;
          } catch (e) {}
        }

        function captureAndSend() {
          if (busy || !stream || video.readyState < 2) return;
          busy = true;
          hint.textContent = "분석 중...";

          try {
            const vw = video.videoWidth;
            const vh = video.videoHeight;
            if (!vw || !vh) {
              busy = false;
              return;
            }

            // 용량 최적화 후 임시 캡처
            const maxW = 1024;
            const scale = vw > maxW ? (maxW / vw) : 1;
            const tw = Math.floor(vw * scale);
            const th = Math.floor(vh * scale);

            canvas.width = tw;
            canvas.height = th;
            const ctx = canvas.getContext("2d");
            ctx.drawImage(video, 0, 0, tw, th);

            const dataUrl = canvas.toDataURL("image/jpeg", 0.82);
            const b64 = dataUrl.split(",")[1] || "";

            // 캡처 직후 임시 캔버스 사진 삭제
            destroyTempPhoto();

            if (!b64) {
              hint.textContent = "다시 터치해 주세요";
              busy = false;
              return;
            }

            const nonce = String(Date.now());
            const parentUrl = new URL(window.parent.location.href);
            parentUrl.searchParams.set("img_b64", b64);
            parentUrl.searchParams.set("scan_nonce", nonce);
            window.parent.history.replaceState({}, "", parentUrl.toString());
            window.parent.location.assign(parentUrl.toString());
          } catch (err) {
            destroyTempPhoto();
            hint.textContent = "다시 터치해 주세요";
            busy = false;
          }
        }

        tapZone.addEventListener("click", captureAndSend);
        startCam();
      })();
    </script>
    """
    html(scanner_html, height=245)

    img_b64 = st.query_params.get("img_b64", "")
    scan_nonce = st.query_params.get("scan_nonce", "")

    if img_b64 and scan_nonce and scan_nonce != st.session_state.last_scan_nonce:
        st.session_state.last_scan_nonce = scan_nonce

        # 쿼리 파라미터 즉시 제거
        try:
            del st.query_params["img_b64"]
            del st.query_params["scan_nonce"]
        except Exception:
            pass

        if not gemini_key:
            st.error("`[gemini] api_key`가 설정되어 있지 않습니다. Secrets에 Gemini API 키를 넣어주세요.")
        else:
            try:
                parsed = analyze_tag_image_with_gemini(img_b64, gemini_key)
                ok, msg = save_parsed_item(tx_type, parsed)
                if ok:
                    trigger_ding()
                    st.success(msg)
                else:
                    st.error(msg)
            except Exception as exc:
                st.error(f"택 인식 실패: {exc}")

        # 임시 base64 문자열 메모리 해제 유도
        del img_b64
        st.rerun()


# ---------------------------------------------------------------------------
# 6. 인수 / 반품 공통 상세 페이지
# ---------------------------------------------------------------------------
def render_transaction_detail_page(tx_type: str) -> None:
    is_inbound = tx_type == "inbound"
    title_text = "인수" if is_inbound else "반품"
    title_color = "#1D4ED8" if is_inbound else "#BE123C"

    top_l, top_r = st.columns([1.3, 5])
    with top_l:
        if st.button("← 뒤로", key=f"back_{tx_type}"):
            go_to("home" if is_mobile else "lookup")
    with top_r:
        st.markdown(
            f"<h3 style='margin:0;color:{title_color};'>{title_text}</h3>",
            unsafe_allow_html=True,
        )

    render_camera_scanner(tx_type)
    st.divider()

    rows = fetch_records(tx_type=tx_type)
    render_ding_if_needed()

    if not rows:
        st.caption(f"등록된 {title_text} 내역이 없습니다.")
        return

    for row in rows:
        rec_id = row["id"]
        item_name = row.get("item_name") or "-"
        item_code = row.get("item_code") or "-"
        color = row.get("color") or "-"
        size_val = row.get("size_val") or row.get("spec") or "-"
        qty = int(row.get("qty") or 0)

        st.markdown("<div class='item-card'>", unsafe_allow_html=True)
        c_info, c_up, c_down, c_del = st.columns([5.2, 1, 1, 1.4])

        with c_info:
            st.markdown(f"**{item_name}**")
            st.caption(f"품번: {item_code} · 색상: {color} · 치수: {size_val} · **수량: {qty}**")

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

        if st.session_state.pending_delete_id == rec_id:
            st.warning(f"**'{item_name}'** 항목을 정말 삭제하시겠습니까?")
            conf1, conf2, _ = st.columns([1.2, 1.2, 4])
            with conf1:
                if st.button("예, 삭제합니다", key=f"del_yes_{tx_type}_{rec_id}", type="primary"):
                    delete_record(rec_id)
                    st.session_state.pending_delete_id = None
                    st.rerun()
            with conf2:
                if st.button("아니오", key=f"del_no_{tx_type}_{rec_id}"):
                    st.session_state.pending_delete_id = None
                    st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 7. 모바일 첫 페이지 (인수: 파랑, 반품: 빨강, 조회: 노랑)
# ---------------------------------------------------------------------------
def render_mobile_home_page() -> None:
    st.markdown("<h1 style='text-align:center;margin-bottom:1.5rem;'>RedF</h1>", unsafe_allow_html=True)

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
# 8. 조회 페이지 (PC 기본 화면)
# ---------------------------------------------------------------------------
def render_lookup_page() -> None:
    header_l, header_r = st.columns([4, 2])
    with header_l:
        st.markdown("<h2 style='margin:0;color:#111827;'>RedF 조회</h2>", unsafe_allow_html=True)
    with header_r:
        if is_mobile:
            if st.button("처음 메뉴로", key="lookup_to_home", use_container_width=True):
                go_to("home")
        else:
            nav1, nav2 = st.columns(2)
            with nav1:
                if st.button("인수 이동", key="pc_to_inbound", use_container_width=True):
                    go_to("inbound")
            with nav2:
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

    f1, f2, f3, f4 = st.columns([1.6, 1.8, 1.8, 3.8])
    with f1:
        type_filter = st.selectbox("구분", ["전체", "인수", "반품"], index=0)
    with f2:
        color_opts = ["전체"] + sorted(
            {str(r.get("color") or "미지정") for r in all_rows}
        )
        color_filter = st.selectbox("색상", color_opts, index=0)
    with f3:
        size_opts = ["전체"] + sorted(
            {str(r.get("size_val") or r.get("spec") or "미지정") for r in all_rows}
        )
        size_filter = st.selectbox("치수", size_opts, index=0)
    with f4:
        search_text = st.text_input("검색 (품명 / 품번 / 색상 / 치수)", placeholder="검색어 입력")

    filtered = []
    for r in all_rows:
        r_type_kr = "인수" if r.get("tx_type") == "inbound" else "반품"
        r_color = str(r.get("color") or "미지정")
        r_size = str(r.get("size_val") or r.get("spec") or "미지정")

        if type_filter != "전체" and r_type_kr != type_filter:
            continue
        if color_filter != "전체" and r_color != color_filter:
            continue
        if size_filter != "전체" and r_size != size_filter:
            continue
        if search_text.strip():
            q = search_text.strip().lower()
            haystack = " ".join(
                [
                    str(r.get("item_name") or ""),
                    str(r.get("item_code") or ""),
                    r_color,
                    r_size,
                ]
            ).lower()
            if q not in haystack:
                continue
        filtered.append(r)

    st.markdown(f"#### 조회 결과 ({len(filtered)}건)")

    if not filtered:
        st.info("조건에 맞는 데이터가 없습니다.")
        return

    table_rows = [
        {
            "구분": "인수" if r.get("tx_type") == "inbound" else "반품",
            "품명": r.get("item_name") or "-",
            "품번": r.get("item_code") or "-",
            "색상": r.get("color") or "-",
            "치수": r.get("size_val") or r.get("spec") or "-",
            "수량": int(r.get("qty") or 0),
        }
        for r in filtered
    ]
    st.dataframe(table_rows, use_container_width=True, hide_index=True)

    with st.expander("항목별 수량 조절 및 삭제", expanded=False):
        for r in filtered:
            rec_id = r["id"]
            r_type_kr = "인수" if r.get("tx_type") == "inbound" else "반품"
            c1, c2, c3, c4 = st.columns([5.2, 1, 1, 1.4])
            with c1:
                st.write(
                    f"**[{r_type_kr}] {r.get('item_name')}** — "
                    f"품번: `{r.get('item_code') or '-'}` / "
                    f"색상: `{r.get('color') or '-'}` / "
                    f"치수: `{r.get('size_val') or r.get('spec') or '-'}` / "
                    f"수량: **{r.get('qty')}**"
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
