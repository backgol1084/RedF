import io
import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

import requests
import streamlit as st
from PIL import Image
from streamlit.components.v1 import html
from supabase import Client, create_client

st.set_page_config(
    page_title="RedF",
    page_icon="🏷️",
    layout="centered",
    initial_sidebar_state="collapsed",
)


# ---------------------------------------------------------------------------
# 1. 클라이언트 및 API 키 로드
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
# 2. 세션 상태 및 페이지 전환
# ---------------------------------------------------------------------------
if "page" not in st.session_state:
    st.session_state.page = "home"

if "pending_delete_id" not in st.session_state:
    st.session_state.pending_delete_id = None

if "scan_counter" not in st.session_state:
    st.session_state.scan_counter = 0

if "processed_photo_keys" not in st.session_state:
    st.session_state.processed_photo_keys = set()

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
# 3. 페이지 배경색 및 버튼 색 지정
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
                padding-top: 0.9rem;
                padding-bottom: 2.2rem;
                max-width: 680px;
            }}
            .redf-btn-inbound button {{
                background-color: #2563EB !important;
                color: #FFFFFF !important;
                border: none !important;
                font-size: 1.3rem !important;
                font-weight: 700 !important;
                height: 4.6rem !important;
                border-radius: 14px !important;
            }}
            .redf-btn-inbound button:hover {{
                background-color: #1D4ED8 !important;
            }}
            .redf-btn-return button {{
                background-color: #DC2626 !important;
                color: #FFFFFF !important;
                border: none !important;
                font-size: 1.3rem !important;
                font-weight: 700 !important;
                height: 4.6rem !important;
                border-radius: 14px !important;
            }}
            .redf-btn-return button:hover {{
                background-color: #B91C1C !important;
            }}
            .redf-btn-lookup button {{
                background-color: #FACC15 !important;
                color: #111827 !important;
                border: none !important;
                font-size: 1.3rem !important;
                font-weight: 700 !important;
                height: 4.6rem !important;
                border-radius: 14px !important;
            }}
            .redf-btn-lookup button:hover {{
                background-color: #EAB308 !important;
            }}
            .item-card {{
                background-color: rgba(255, 255, 255, 0.95);
                border: 1px solid #E5E7EB;
                border-radius: 12px;
                padding: 0.7rem 0.9rem;
                margin-bottom: 0.55rem;
            }}
        </style>
        """,
        unsafe_allow_html=True,
    )


apply_theme(st.session_state.page)


# ---------------------------------------------------------------------------
# 4. 택 이미지 분석 (품명, 품번, 색상, 치수) 및 Supabase CRUD
# ---------------------------------------------------------------------------
def _clean_val(val: Any, fallback: str) -> str:
    s = re.sub(r"\s+", " ", str(val or "")).strip(" :·.-")
    return s if s else fallback


def _prepare_jpeg_bytes(raw_bytes: bytes, max_width: int = 1280) -> bytes:
    with Image.open(io.BytesIO(raw_bytes)) as img:
        img = img.convert("RGB")
        w, h = img.size
        if w > max_width:
            new_h = max(1, int(h * (max_width / w)))
            img = img.resize((max_width, new_h), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()


def analyze_tag_with_gemini(raw_bytes: bytes, api_key: str) -> dict[str, Any]:
    jpeg_bytes = _prepare_jpeg_bytes(raw_bytes)
    import base64

    b64_data = base64.b64encode(jpeg_bytes).decode("ascii")
    del jpeg_bytes

    endpoint = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.5-flash:generateContent?key={api_key}"
    )
    prompt = (
        "이 의류 상품택 사진에서 '품명', '품번', '색상', '치수'를 정확히 읽어서 "
        "JSON 객체로만 답하세요. 설명이나 코드블록은 쓰지 마세요.\n"
        "키 이름: item_name, item_code, color, size_val\n"
        "치수에 '100 (90~110)'처럼 표기되어 있으면 대표 치수(예: '100')를 넣으세요. "
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
                            "data": b64_data,
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
    del b64_data

    resp = requests.post(endpoint, json=payload, timeout=25)
    resp.raise_for_status()
    data = resp.json()

    text_out = (
        data.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [{}])[0]
        .get("text", "")
    ).strip()
    text_out = re.sub(r"^```(?:json)?\s*|\s*```$", "", text_out, flags=re.IGNORECASE).strip()
    parsed = json.loads(text_out)

    item_name = _clean_val(parsed.get("item_name"), "")
    item_code = _clean_val(parsed.get("item_code"), "")
    color = _clean_val(parsed.get("color"), "미지정")
    size_val = _clean_val(parsed.get("size_val"), "미지정")

    if not item_name and not item_code:
        raise ValueError("택에서 품명이나 품번을 읽지 못했습니다. 택이 선명하게 보이도록 다시 찍어주세요.")

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
            new_qty = int(row.get("qty") or 0) + 1
            supabase.table("redf_transactions").update(
                {
                    "qty": new_qty,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            ).eq("id", row["id"]).execute()
            return (
                True,
                f"수량 +1 저장: {parsed['item_name']} ({parsed['item_code']} / {parsed['color']} / {parsed['size_val']}) → {new_qty}개",
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
                "qty": 1,
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
# 5. 인수 / 반품 상세 페이지 (찍자마자 인식 -> 저장 -> 임시사진 파기 -> 띵~)
# ---------------------------------------------------------------------------
def render_transaction_detail_page(tx_type: str) -> None:
    is_inbound = tx_type == "inbound"
    title_text = "인수" if is_inbound else "반품"
    title_color = "#1D4ED8" if is_inbound else "#BE123C"

    top_l, top_r = st.columns([1.4, 5])
    with top_l:
        if st.button("← 홈", key=f"back_{tx_type}"):
            go_to("home")
    with top_r:
        st.markdown(
            f"<h3 style='margin:0;color:{title_color};'>{title_text}</h3>",
            unsafe_allow_html=True,
        )

    gemini_key = get_gemini_api_key()
    if not gemini_key:
        st.error("Secrets에 `[gemini] api_key`가 없습니다. Google AI Studio API 키를 등록해 주세요.")

    cam_key = f"cam_{tx_type}_{st.session_state.scan_counter}"
    captured = st.camera_input("상품택 촬영", key=cam_key, label_visibility="collapsed")

    if captured is not None:
        photo_token = f"{cam_key}_{captured.size}"
        if photo_token not in st.session_state.processed_photo_keys:
            st.session_state.processed_photo_keys.add(photo_token)
            raw_bytes = captured.getvalue()

            if not gemini_key:
                st.error("Gemini API 키가 없어 인식할 수 없습니다.")
            else:
                with st.spinner("택 인식 및 저장 중..."):
                    try:
                        parsed = analyze_tag_with_gemini(raw_bytes, gemini_key)
                        ok, msg = save_parsed_item(tx_type, parsed)
                        if ok:
                            trigger_ding()
                            st.success(msg)
                        else:
                            st.error(msg)
                    except Exception as exc:
                        st.error(f"인식 실패: {exc}")

            # 임시 사진 데이터 즉시 파기 및 다음 촬영 준비
            del raw_bytes
            del captured
            st.session_state.scan_counter += 1
            st.rerun()

    st.divider()

    rows = fetch_records(tx_type=tx_type)
    render_ding_if_needed()

    if not rows:
        st.caption(f"등록된 {title_text} 제품이 없습니다.")
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
# 6. 모바일 첫 페이지 (인수: 파랑, 반품: 빨강, 조회: 노랑)
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
# 7. 조회 페이지
# ---------------------------------------------------------------------------
def render_lookup_page() -> None:
    header_l, header_r = st.columns([4, 1.8])
    with header_l:
        st.markdown("<h2 style='margin:0;color:#111827;'>조회</h2>", unsafe_allow_html=True)
    with header_r:
        if st.button("← 홈", key="lookup_to_home", use_container_width=True):
            go_to("home")

    st.divider()

    all_rows = fetch_records(tx_type=None)
    inbound_qty = sum(int(r.get("qty") or 0) for r in all_rows if r.get("tx_type") == "inbound")
    return_qty = sum(int(r.get("qty") or 0) for r in all_rows if r.get("tx_type") == "return")

    m1, m2, m3 = st.columns(3)
    m1.metric("건수", f"{len(all_rows)}건")
    m2.metric("인수 수량", f"{inbound_qty}개")
    m3.metric("반품 수량", f"{return_qty}개")

    type_filter = st.selectbox("구분", ["전체", "인수", "반품"], index=0)
    search_text = st.text_input("검색 (품명 / 품번 / 색상 / 치수)", placeholder="검색어 입력")

    filtered = []
    for r in all_rows:
        r_type_kr = "인수" if r.get("tx_type") == "inbound" else "반품"
        if type_filter != "전체" and r_type_kr != type_filter:
            continue
        if search_text.strip():
            q = search_text.strip().lower()
            haystack = " ".join(
                [
                    str(r.get("item_name") or ""),
                    str(r.get("item_code") or ""),
                    str(r.get("color") or ""),
                    str(r.get("size_val") or r.get("spec") or ""),
                ]
            ).lower()
            if q not in haystack:
                continue
        filtered.append(r)

    if not filtered:
        st.info("조회된 데이터가 없습니다.")
        return

    for r in filtered:
        rec_id = r["id"]
        r_type_kr = "인수" if r.get("tx_type") == "inbound" else "반품"
        item_name = r.get("item_name") or "-"
        item_code = r.get("item_code") or "-"
        color = r.get("color") or "-"
        size_val = r.get("size_val") or r.get("spec") or "-"
        qty = int(r.get("qty") or 0)

        st.markdown("<div class='item-card'>", unsafe_allow_html=True)
        c1, c2, c3, c4 = st.columns([5.2, 1, 1, 1.4])
        with c1:
            st.markdown(f"**[{r_type_kr}] {item_name}**")
            st.caption(f"품번: {item_code} · 색상: {color} · 치수: {size_val} · **수량: {qty}**")
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
            st.warning(f"**'{item_name}'** 항목을 정말 삭제하시겠습니까?")
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
        st.markdown("</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 8. 페이지 라우터
# ---------------------------------------------------------------------------
page = st.session_state.page
if page == "home":
    render_mobile_home_page()
elif page == "inbound":
    render_transaction_detail_page("inbound")
elif page == "return":
    render_transaction_detail_page("return")
else:
    render_lookup_page()
