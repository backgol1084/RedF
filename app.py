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
    """저장 및 리스트 반영 직후 '띵~' 사운드를 1회 재생합니다."""
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

          // '띵~' 느낌의 맑은 벨 톤 (A5 -> D6)
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
        }} catch (e) {{
          // 오디오 재생 제한 환경 무시
        }}
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
                padding-top: 1.4rem;
                padding-bottom: 3rem;
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
                background-color: rgba(255, 255, 255, 0.92);
                border: 1px solid #E5E7EB;
                border-radius: 12px;
                padding: 0.85rem 1rem;
                margin-bottom: 0.65rem;
            }}
        </style>
        """,
        unsafe_allow_html=True,
    )


apply_theme(st.session_state.page)


# ---------------------------------------------------------------------------
# 4. 택 텍스트 파싱 (품명, 품번, 색상, 치수) 및 Supabase CRUD
# ---------------------------------------------------------------------------
def _clean_label_value(val: str) -> str:
    return re.sub(r"\s+", " ", val).strip(" :·.-")


def parse_redf_tag_text(raw_text: str) -> dict[str, Any]:
    cleaned = raw_text.strip()
    if not cleaned:
        raise ValueError("인식된 택 데이터가 비어 있습니다.")

    if cleaned.startswith("{") and cleaned.endswith("}"):
        data = json.loads(cleaned)
        return {
            "item_name": _clean_label_value(
                str(data.get("item_name") or data.get("품명") or "미확인 품명")
            ),
            "item_code": _clean_label_value(
                str(data.get("item_code") or data.get("품번") or "미확인 품번")
            ),
            "color": _clean_label_value(
                str(data.get("color") or data.get("색상") or "미지정")
            ),
            "size_val": _clean_label_value(
                str(data.get("size_val") or data.get("size") or data.get("치수") or "미지정")
            ),
            "qty": max(1, int(data.get("qty") or data.get("수량") or 1)),
            "tag_code": str(data.get("tag_code") or data.get("item_code") or cleaned[:60]),
        }

    item_name = ""
    item_code = ""
    color = ""
    size_val = ""

    name_match = re.search(r"품\s*명\s*[:：\-]?\s*([^\n]+)", cleaned)
    if name_match:
        item_name = _clean_label_value(name_match.group(1))

    code_match = re.search(r"품\s*번\s*[:：\-]?\s*([A-Za-z0-9\-_]+)", cleaned)
    if code_match:
        item_code = _clean_label_value(code_match.group(1))

    color_match = re.search(r"색\s*상\s*[:：\-]?\s*([^\n]+)", cleaned)
    if color_match:
        color = _clean_label_value(color_match.group(1))

    size_match = re.search(
        r"치\s*수\s*[:：\-]?\s*([0-9]{2,3}(?:\s*[A-Za-z가-힣]+)?)", cleaned
    )
    if size_match:
        size_val = _clean_label_value(size_match.group(1))

    if not (item_name and item_code):
        for sep in ["|", "/"]:
            if sep in cleaned:
                parts = [_clean_label_value(p) for p in cleaned.split(sep)]
                if len(parts) >= 1 and not item_name:
                    item_name = parts[0]
                if len(parts) >= 2 and not item_code:
                    item_code = parts[1]
                if len(parts) >= 3 and not color:
                    color = parts[2]
                if len(parts) >= 4 and not size_val:
                    size_val = parts[3]
                break

    if not item_name and not item_code:
        raise ValueError("택에서 '품명' 또는 '품번'을 찾지 못했습니다.")

    final_name = item_name or item_code
    final_code = item_code or "미기재"
    final_color = color or "미지정"
    final_size = size_val or "미지정"

    return {
        "item_name": final_name,
        "item_code": final_code,
        "color": final_color,
        "size_val": final_size,
        "qty": 1,
        "tag_code": final_code if final_code != "미기재" else final_name[:50],
    }


def fetch_records(tx_type: Optional[str] = None) -> list[dict[str, Any]]:
    query = supabase.table("redf_transactions").select("*")
    if tx_type:
        query = query.eq("tx_type", tx_type)
    res = query.order("id", desc=True).execute()
    return res.data or []


def save_scanned_tag(tx_type: str, raw_payload: str) -> tuple[bool, str]:
    try:
        parsed = parse_redf_tag_text(raw_payload)
    except Exception as exc:
        return False, f"택 인식 해석 실패: {exc}"

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
                f"인식·수량추가(+1): {parsed['item_name']} | {parsed['item_code']} | {parsed['color']} | {parsed['size_val']} → {new_qty}개",
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
            f"자동 저장 완료: {parsed['item_name']} | {parsed['item_code']} | {parsed['color']} | {parsed['size_val']} (1개)",
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
# 5. 상단 카메라 실시간 택 OCR 자동 인식 (셔터 없이 인식 시 자동 저장)
# ---------------------------------------------------------------------------
def render_camera_scanner(tx_type: str) -> None:
    st.markdown("#### 📷 상품택 자동 인식 카메라")
    st.caption("카메라에 택을 비추면 촬영 버튼을 누르지 않아도 품명·품번·색상·치수를 읽어 자동 저장합니다.")

    scanner_html = """
    <div style="background:#111827;color:#F9FAFB;padding:12px;border-radius:12px;">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;gap:8px;flex-wrap:wrap;">
        <span id="ocr-status" style="font-size:0.88rem;">OCR 엔진 준비 중...</span>
        <div>
          <button id="btn-ocr-start" type="button" style="padding:6px 12px;border-radius:8px;border:none;background:#2563EB;color:#fff;cursor:pointer;font-weight:600;">카메라 켜기</button>
          <button id="btn-ocr-stop" type="button" style="padding:6px 12px;border-radius:8px;border:none;background:#4B5563;color:#fff;cursor:pointer;font-weight:600;">끄기</button>
        </div>
      </div>
      <video id="ocr-video" autoplay playsinline muted style="width:100%;max-height:270px;object-fit:cover;border-radius:10px;background:#000;"></video>
      <canvas id="ocr-canvas" style="display:none;"></canvas>
      <div id="ocr-preview" style="margin-top:8px;font-size:0.78rem;color:#D1D5DB;white-space:pre-line;max-height:70px;overflow:auto;"></div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js"></script>
    <script>
      (function() {
        const video = document.getElementById("ocr-video");
        const canvas = document.getElementById("ocr-canvas");
        const statusEl = document.getElementById("ocr-status");
        const previewEl = document.getElementById("ocr-preview");
        const startBtn = document.getElementById("btn-ocr-start");
        const stopBtn = document.getElementById("btn-ocr-stop");

        let stream = null;
        let timer = null;
        let worker = null;
        let isRecognizing = false;
        let lastSignature = "";
        let lastSavedAt = 0;

        async function ensureWorker() {
          if (worker) return worker;
          statusEl.textContent = "한글/영문 택 인식 엔진 로딩 중...";
          worker = await Tesseract.createWorker("kor+eng");
          return worker;
        }

        function looksLikeValidTag(text) {
          const hasNameOrCode =
            /품\s*명/.test(text) ||
            /품\s*번/.test(text) ||
            /[A-Z]{3,}[A-Z0-9\-]{4,}/.test(text);
          const hasColorOrSize =
            /색\s*상/.test(text) || /치\s*수/.test(text);
          return hasNameOrCode && hasColorOrSize;
        }

        function submitTagText(rawText) {
          const now = Date.now();
          const compact = rawText.replace(/\\s+/g, " ").trim();
          if (!compact) return;
          if (compact === lastSignature && (now - lastSavedAt) < 2500) return;

          lastSignature = compact;
          lastSavedAt = now;
          statusEl.textContent = "택 인식 완료! 자동 저장 중...";

          const parentUrl = new URL(window.parent.location.href);
          parentUrl.searchParams.set("tag_payload", rawText.trim());
          parentUrl.searchParams.set("tag_nonce", String(now));
          window.parent.history.replaceState({}, "", parentUrl.toString());
          window.parent.location.assign(parentUrl.toString());
        }

        async function recognizeFrame() {
          if (!stream || isRecognizing || video.readyState < 2) return;
          isRecognizing = true;
          try {
            const w = await ensureWorker();
            const vw = video.videoWidth;
            const vh = video.videoHeight;
            if (!vw || !vh) return;

            const cropW = Math.floor(vw * 0.85);
            const cropH = Math.floor(vh * 0.75);
            const sx = Math.floor((vw - cropW) / 2);
            const sy = Math.floor((vh - cropH) / 2);

            canvas.width = cropW;
            canvas.height = cropH;
            const ctx = canvas.getContext("2d");
            ctx.drawImage(video, sx, sy, cropW, cropH, 0, 0, cropW, cropH);

            const ret = await w.recognize(canvas);
            const text = (ret && ret.data && ret.data.text) ? ret.data.text.trim() : "";
            if (text) {
              previewEl.textContent = text;
              if (looksLikeValidTag(text)) {
                submitTagText(text);
              }
            }
          } catch (e) {
            // 프레임 인식 중 일시 오류 무시
          } finally {
            isRecognizing = false;
          }
        }

        async function startCam() {
          try {
            if (stream) return;
            stream = await navigator.mediaDevices.getUserMedia({
              video: { facingMode: { ideal: "environment" } },
              audio: false
            });
            video.srcObject = stream;
            await ensureWorker();
            statusEl.textContent = "카메라 스캔 중 — 택을 화면 중앙에 비춰주세요.";
            if (timer) clearInterval(timer);
            timer = setInterval(recognizeFrame, 1200);
          } catch (err) {
            statusEl.textContent = "카메라 실행 실패: " + err.message;
          }
        }

        function stopCam() {
          if (timer) {
            clearInterval(timer);
            timer = null;
          }
          if (stream) {
            stream.getTracks().forEach(t => t.stop());
            stream = null;
          }
          video.srcObject = null;
          statusEl.textContent = "카메라가 꺼져 있습니다.";
        }

        startBtn.addEventListener("click", startCam);
        stopBtn.addEventListener("click", stopCam);

        startCam();
      })();
    </script>
    """
    html(scanner_html, height=390)

    # 자동 인식된 택 텍스트 처리
    tag_payload = st.query_params.get("tag_payload", "")
    tag_nonce = st.query_params.get("tag_nonce", "")
    if tag_payload and tag_nonce and tag_nonce != st.session_state.last_scan_nonce:
        st.session_state.last_scan_nonce = tag_nonce
        ok, msg = save_scanned_tag(tx_type, tag_payload)
        try:
            del st.query_params["tag_payload"]
            del st.query_params["tag_nonce"]
        except Exception:
            pass
        if ok:
            trigger_ding()
            st.success(msg)
        else:
            st.error(msg)
        st.rerun()

    # 택 텍스트 붙여넣기 / 테스트용 입력 + 소리 테스트
    with st.expander("택 텍스트 직접 붙여넣기 / 소리 테스트", expanded=False):
        if st.button("🔔 '띵~' 소리 테스트", key=f"btn_ding_test_{tx_type}"):
            trigger_ding()
            st.rerun()

        sample_txt = st.text_area(
            "택 내용 입력",
            height=110,
            key=f"manual_tag_{tx_type}",
            placeholder="품 명 : 마이크로엠보우먼짚티셔츠\n품 번 : REWFTSWBF051\n색 상 : 버건디(BG)\n치 수 : 100",
        )
        if st.button("택 내용 인식 및 저장", key=f"btn_manual_tag_{tx_type}"):
            if sample_txt.strip():
                ok, msg = save_scanned_tag(tx_type, sample_txt.strip())
                if ok:
                    trigger_ding()
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
            else:
                st.warning("택 내용을 입력해 주세요.")


# ---------------------------------------------------------------------------
# 6. 인수 / 반품 공통 상세 페이지
# ---------------------------------------------------------------------------
def render_transaction_detail_page(tx_type: str) -> None:
    is_inbound = tx_type == "inbound"
    title_text = "인수" if is_inbound else "반품"
    title_color = "#1D4ED8" if is_inbound else "#BE123C"

    top_l, top_r = st.columns([1.2, 5])
    with top_l:
        if st.button("← 뒤로가기", key=f"back_{tx_type}"):
            go_to("home" if is_mobile else "lookup")
    with top_r:
        st.markdown(
            f"<h2 style='margin:0;color:{title_color};'>🏷️ RedF — {title_text}</h2>",
            unsafe_allow_html=True,
        )

    st.divider()

    # 상단: 카메라 자동 인식
    render_camera_scanner(tx_type)

    st.divider()

    # 하단: 품명, 품번, 색상, 치수, 수량 리스트 + 업/다운/삭제
    st.markdown(f"#### 📋 {title_text} 제품 리스트")
    rows = fetch_records(tx_type=tx_type)

    # 리스트가 렌더링되는 시점에 '띵~' 알림음 재생
    render_ding_if_needed()

    if not rows:
        st.info(f"인식된 {title_text} 제품이 없습니다. 상단 카메라에 택을 비춰주세요.")
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
            st.markdown(f"**품명:** {item_name}")
            st.markdown(
                f"**품번:** `{item_code}` &nbsp;|&nbsp; "
                f"**색상:** `{color}` &nbsp;|&nbsp; "
                f"**치수:** `{size_val}` &nbsp;|&nbsp; "
                f"**수량: {qty}**"
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

        if st.session_state.pending_delete_id == rec_id:
            st.warning(
                f"**'{item_name}' (품번: {item_code} / 색상: {color} / 치수: {size_val})** 항목을 정말 삭제하시겠습니까?"
            )
            conf1, conf2, _ = st.columns([1.2, 1.2, 4])
            with conf1:
                if st.button("예, 삭제합니다", key=f"del_yes_{tx_type}_{rec_id}", type="primary"):
                    delete_record(rec_id)
                    st.session_state.pending_delete_id = None
                    st.success("삭제되었습니다.")
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
    st.markdown("<h1 style='text-align:center;margin-bottom:0.25rem;'>RedF</h1>", unsafe_allow_html=True)
    st.markdown(
        "<p style='text-align:center;color:#4B5563;margin-bottom:2rem;'>원하시는 메뉴를 선택해 주세요.</p>",
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
# 8. 조회 페이지 (PC 기본 화면)
# ---------------------------------------------------------------------------
def render_lookup_page() -> None:
    header_l, header_r = st.columns([4, 2])
    with header_l:
        st.markdown("<h2 style='margin:0;color:#111827;'>🔎 RedF 조회</h2>", unsafe_allow_html=True)
        st.caption("품명, 품번, 색상, 치수별 인수·반품 내역을 조회합니다.")
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
