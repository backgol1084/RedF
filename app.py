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
# 4. Supabase CRUD 함수
# ---------------------------------------------------------------------------
def _clean_val(val: Any, fallback: str) -> str:
    s = re.sub(r"\s+", " ", str(val or "")).strip(" :·.-")
    return s if s else fallback


def fetch_records(tx_type: Optional[str] = None) -> list[dict[str, Any]]:
    query = supabase.table("redf_transactions").select("*")
    if tx_type:
        query = query.eq("tx_type", tx_type)
    res = query.order("id", desc=True).execute()
    return res.data or []


def save_parsed_item(tx_type: str, parsed: dict[str, Any]) -> tuple[bool, str]:
    item_name = _clean_val(parsed.get("item_name"), "")
    item_code = _clean_val(parsed.get("item_code"), "미기재")
    color = _clean_val(parsed.get("color"), "미지정")
    size_val = _clean_val(parsed.get("size_val"), "미지정")

    if not item_name and item_code == "미기재":
        return False, "유효한 품명/품번이 없습니다."

    final_name = item_name or item_code
    final_code = item_code or "미기재"
    tag_code = final_code if final_code != "미기재" else final_name[:50]

    try:
        existing = (
            supabase.table("redf_transactions")
            .select("*")
            .eq("tx_type", tx_type)
            .eq("item_name", final_name)
            .eq("item_code", final_code)
            .eq("color", color)
            .eq("size_val", size_val)
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
                f"수량 +1: {final_name} ({final_code} / {color} / {size_val}) → {new_qty}개",
            )

        supabase.table("redf_transactions").insert(
            {
                "tx_type": tx_type,
                "tag_code": tag_code,
                "item_name": final_name,
                "item_code": final_code,
                "spec": size_val,
                "size_val": size_val,
                "color": color,
                "qty": 1,
            }
        ).execute()
        return (
            True,
            f"저장 완료: {final_name} ({final_code} / {color} / {size_val})",
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
# 5. 터치 없이 자동 캡처 -> Gemini 인식 -> 임시사진 즉시 삭제 -> 자동 저장
# ---------------------------------------------------------------------------
def render_camera_scanner(tx_type: str) -> None:
    gemini_key = get_gemini_api_key()
    safe_key_json = json.dumps(gemini_key)

    scanner_html = f"""
    <div style="position:relative;width:100%;height:235px;background:#000;border-radius:12px;overflow:hidden;user-select:none;">
      <video id="cam-video" autoplay playsinline muted style="width:100%;height:100%;object-fit:cover;display:block;"></video>
      <canvas id="temp-canvas" style="display:none;"></canvas>
      <div id="cam-status" style="position:absolute;bottom:8px;left:50%;transform:translateX(-50%);background:rgba(0,0,0,0.68);color:#fff;padding:4px 12px;border-radius:999px;font-size:0.78rem;white-space:nowrap;">
        카메라 자동 인식 대기 중...
      </div>
    </div>

    <script>
      (function() {{
        const GEMINI_KEY = {safe_key_json};
        const video = document.getElementById("cam-video");
        const canvas = document.getElementById("temp-canvas");
        const statusEl = document.getElementById("cam-status");

        let stream = null;
        let autoTimer = null;
        let busy = false;
        let lastSavedKey = "";
        let lastSavedTime = 0;

        function destroyTempPhoto() {{
          try {{
            const ctx = canvas.getContext("2d");
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            canvas.width = 1;
            canvas.height = 1;
          }} catch (e) {{}}
        }}

        async function callGeminiOnFrame(b64Jpeg) {{
          const endpoint =
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=" +
            encodeURIComponent(GEMINI_KEY);

          const promptText =
            "이 의류 상품택 이미지에서 품명, 품번, 색상, 치수를 읽어서 JSON 객체로만 답하세요.\\n" +
            "키: item_name, item_code, color, size_val\\n" +
            "치수에 '100 (90~110)'처럼 표기되면 대표 치수(예: '100')를 넣으세요. " +
            "택이 보이지 않거나 읽을 수 없으면 item_name과 item_code를 빈 문자열 ''로 두세요.";

          const res = await fetch(endpoint, {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify({{
              contents: [{{
                parts: [
                  {{ text: promptText }},
                  {{ inline_data: {{ mime_type: "image/jpeg", data: b64Jpeg }} }}
                ]
              }}],
              generationConfig: {{
                temperature: 0.1,
                responseMimeType: "application/json"
              }}
            }})
          }});

          if (!res.ok) {{
            throw new Error("API 응답 오류 (" + res.status + ")");
          }}

          const json = await res.json();
          const rawText = (
            json?.candidates?.[0]?.content?.parts?.[0]?.text || "{{}}"
          ).replace(/^```(?:json)?\\s*|\\s*```$/gi, "").trim();

          return JSON.parse(rawText);
        }}

        function pushParsedToApp(parsed) {{
          const itemName = String(parsed.item_name || "").trim();
          const itemCode = String(parsed.item_code || "").trim();
          const color = String(parsed.color || "미지정").trim() || "미지정";
          const sizeVal = String(parsed.size_val || "미지정").trim() || "미지정";

          if (!itemName && !itemCode) {{
            return false;
          }}

          const sig = itemName + "|" + itemCode + "|" + color + "|" + sizeVal;
          const now = Date.now();
          if (sig === lastSavedKey && (now - lastSavedTime) < 3500) {{
            return true;
          }}
          lastSavedKey = sig;
          lastSavedTime = now;

          statusEl.textContent = "인식 완료 → 저장 중...";

          const parentUrl = new URL(window.parent.location.href);
          parentUrl.searchParams.set("p_name", itemName || itemCode);
          parentUrl.searchParams.set("p_code", itemCode || "미기재");
          parentUrl.searchParams.set("p_color", color);
          parentUrl.searchParams.set("p_size", sizeVal);
          parentUrl.searchParams.set("p_nonce", String(now));
          window.parent.history.replaceState({{}}, "", parentUrl.toString());
          window.parent.location.assign(parentUrl.toString());
          return true;
        }}

        async function autoScanStep() {{
          if (busy || !stream || video.readyState < 2) return;
          if (!GEMINI_KEY) {{
            statusEl.textContent = "Gemini API 키가 설정되지 않았습니다";
            return;
          }}

          busy = true;
          try {{
            const vw = video.videoWidth;
            const vh = video.videoHeight;
            if (!vw || !vh) {{
              busy = false;
              return;
            }}

            const maxW = 960;
            const scale = vw > maxW ? (maxW / vw) : 1;
            const tw = Math.floor(vw * scale);
            const th = Math.floor(vh * scale);

            // 임시 캡처
            canvas.width = tw;
            canvas.height = th;
            const ctx = canvas.getContext("2d");
            ctx.drawImage(video, 0, 0, tw, th);
            const dataUrl = canvas.toDataURL("image/jpeg", 0.8);
            const b64 = (dataUrl.split(",")[1] || "");

            // 임시 사진 즉시 삭제
            destroyTempPhoto();

            if (!b64) {{
              busy = false;
              return;
            }}

            statusEl.textContent = "택 자동 스캔 중...";
            const parsed = await callGeminiOnFrame(b64);
            const saved = pushParsedToApp(parsed);
            if (!saved) {{
              statusEl.textContent = "택을 카메라에 맞춰주세요 (자동 스캔 중)";
            }}
          }} catch (err) {{
            destroyTempPhoto();
            statusEl.textContent = "자동 스캔 대기 중...";
          }} finally {{
            busy = false;
          }}
        }}

        async function startCam() {{
          try {{
            if (stream) return;
            stream = await navigator.mediaDevices.getUserMedia({{
              video: {{
                facingMode: {{ ideal: "environment" }},
                width: {{ ideal: 1280 }},
                height: {{ ideal: 720 }}
              }},
              audio: false
            }});
            video.srcObject = stream;
            statusEl.textContent = "카메라 켜짐 — 택을 비추면 자동 인식됩니다";
            if (autoTimer) clearInterval(autoTimer);
            autoTimer = setInterval(autoScanStep, 2200);
          }} catch (err) {{
            statusEl.textContent = "카메라 권한을 허용해 주세요";
          }}
        }}

        startCam();
      }})();
    </script>
    """
    html(scanner_html, height=245)

    p_name = st.query_params.get("p_name", "")
    p_code = st.query_params.get("p_code", "")
    p_color = st.query_params.get("p_color", "")
    p_size = st.query_params.get("p_size", "")
    p_nonce = st.query_params.get("p_nonce", "")

    if p_nonce and p_nonce != st.session_state.last_scan_nonce and (p_name or p_code):
        st.session_state.last_scan_nonce = p_nonce
        parsed_item = {
            "item_name": p_name,
            "item_code": p_code,
            "color": p_color,
            "size_val": p_size,
        }
        try:
            for k in ["p_name", "p_code", "p_color", "p_size", "p_nonce"]:
                if k in st.query_params:
                    del st.query_params[k]
        except Exception:
            pass

        ok, msg = save_parsed_item(tx_type, parsed_item)
        if ok:
            trigger_ding()
            st.success(msg)
        else:
            st.error(msg)
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
