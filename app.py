import base64
import json
from datetime import date

import pandas as pd
import requests
import streamlit as st


# =========================
# CONFIG
# =========================
st.set_page_config(page_title="Monitoring Pengadaan", layout="wide")

WEBAPP_URL = st.secrets.get("WEBAPP_URL", "").strip()
TEKNIK_KEY = st.secrets.get("TEKNIK_KEY", "").strip()

if not WEBAPP_URL:
    st.error("WEBAPP_URL belum diisi di Streamlit Secrets.")
    st.stop()

if not TEKNIK_KEY:
    st.warning("TEKNIK_KEY belum diisi di Streamlit Secrets. Tab teknik tidak akan bisa login.")


# =========================
# HELPERS
# =========================
def post_api(payload: dict) -> dict:
    r = requests.post(WEBAPP_URL, json=payload, timeout=60)
    r.raise_for_status()
    return r.json()


def clean_status(x) -> str:
    if x is None:
        return "None"
    s = str(x).strip()
    if s == "" or s.lower() in ["none", "null", "nan", "nat", "false"]:
        return "None"
    s_low = s.lower()
    if s_low in ["in process", "in_progress", "progress", "process", "ongoing"]:
        return "In Process"
    if s_low in ["done", "completed", "finish", "finished", "ok", "yes", "true", "1"]:
        return "Done"
    return "None"


def parse_date(x):
    """
    Terima:
    - '2025-12-15T10:00:00.000Z'
    - '2025-12-15'
    - '' / None / False
    Return: date atau None
    """
    if x is None:
        return None
    s = str(x).strip()
    if s == "" or s.lower() in ["none", "nan", "nat", "false"]:
        return None
    s = s[:10]  # ambil YYYY-MM-DD dari ISO panjang
    try:
        return date.fromisoformat(s)
    except Exception:
        return None


def fmt_ddmmyyyy(x) -> str:
    d = parse_date(x)
    return d.strftime("%d-%m-%Y") if d else ""


def status_icon(x) -> str:
    s = clean_status(x)
    if s == "Done":
        return "✅"
    if s == "In Process":
        return "⏳"
    return ""


# =========================
# UI
# =========================
st.title("📦 Monitoring & Update Alur Pengadaan (Permintaan Kapal → Teknik)")

tab_kapal, tab_teknik = st.tabs(["🛳️ User Kapal (Upload)", "🛠️ User Teknik (Monitoring)"])


# =========================
# TAB: USER KAPAL (UPLOAD)
# =========================
with tab_kapal:
    st.subheader("Upload Permintaan Pengadaan")

    with st.form("form_kapal", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            tanggal_upload = st.date_input("Tanggal Upload", value=date.today())
        with col2:
            no_spbj = st.text_input("No. SPBJ Kapal (opsional)")

        judul = st.text_input("Judul Permintaan", placeholder="Contoh: Pengadaan sparepart mesin ...")

        files = st.file_uploader(
            "Upload Dokumen (boleh lebih dari 1 file)",
            accept_multiple_files=True,
            type=None
        )

        submitted = st.form_submit_button("Submit Permintaan")

    if submitted:
        if not judul.strip():
            st.warning("Judul Permintaan wajib diisi.")
            st.stop()

        if not files:
            st.warning("Minimal upload 1 file.")
            st.stop()

        files_payload = []
        for f in files:
            content = f.read()
            files_payload.append({
                "name": f.name,
                "mime": f.type or "application/octet-stream",
                "b64": base64.b64encode(content).decode("utf-8")
            })

        try:
            res = post_api({
                "action": "submit_request",
                "tanggal_upload": tanggal_upload.isoformat(),
                "no_spbj_kapal": no_spbj.strip(),
                "judul_permintaan": judul.strip(),
                "files": files_payload
            })

            if res.get("ok"):
                st.success(f"✅ Berhasil! REQUEST_ID: {res.get('request_id')}")
                st.info("Permintaan kamu sudah masuk. Tab Teknik digunakan untuk monitoring.")
            else:
                st.error(f"Gagal: {res.get('error')}")
        except Exception as e:
            st.error(f"Error koneksi / API: {e}")


# =========================
# TAB: USER TEKNIK (MONITORING ONLY)
# =========================
with tab_teknik:
    st.subheader("Monitoring (User Teknik) — Checklist")

    if "teknik_logged" not in st.session_state:
        st.session_state.teknik_logged = False

    if not st.session_state.teknik_logged:
        pw = st.text_input("Password Teknik", type="password")
        if st.button("Login"):
            if not TEKNIK_KEY:
                st.error("TEKNIK_KEY belum diisi di Streamlit Secrets.")
            elif pw == TEKNIK_KEY:
                st.session_state.teknik_logged = True
                st.success("Login berhasil.")
                st.rerun()
            else:
                st.error("Password salah.")
        st.stop()

    # ===== Ambil data (READ ONLY) =====
    try:
        # kirim dua versi key untuk kompatibilitas backend (kalau salah satunya dibutuhkan)
        res = post_api({"action": "list_requests", "key": TEKNIK_KEY, "teknik_key": TEKNIK_KEY})
        if not res.get("ok"):
            st.error(res.get("error", "Gagal list_requests"))
            st.stop()

        rows = res.get("data") or res.get("rows") or []
        df = pd.DataFrame(rows)

    except Exception as e:
        st.error(f"Error ambil data: {e}")
        st.stop()

    if df.empty:
        st.info("Belum ada permintaan masuk.")
        st.stop()

    # ===== Normalisasi kolom ke UPPERCASE biar konsisten =====
    df.columns = [str(c).strip().upper() for c in df.columns]

    # Pastikan kolom minimal ada (kalau backend beda versi)
    must = [
        "REQUEST_ID", "TANGGAL_UPLOAD", "NO_SPBJ_KAPAL", "JUDUL_PERMINTAAN",
        "EVALUASI_STATUS", "EVALUASI_TANGGAL",
        "SURAT_USULAN_STATUS", "SURAT_USULAN_TANGGAL",
        "SURAT_PERSETUJUAN_STATUS", "SURAT_PERSETUJUAN_TANGGAL",
        "SP2BJ_STATUS", "SP2BJ_TANGGAL",
        "PO_STATUS", "PO_TANGGAL",
        "TERBAYAR_STATUS", "TERBAYAR_TANGGAL",
        "SUPPLY_STATUS", "SUPPLY_TANGGAL",
        "LAST_UPDATE",
        "FILES", "FILES_JSON",
    ]
    for c in must:
        if c not in df.columns:
            df[c] = ""

    # =========================
    # AUTO-CLEAN DATA WARISAN:
    # kalau status None tapi tanggal terisi -> kosongkan tanggal
    # =========================
    pairs = [
        ("SURAT_USULAN_STATUS", "SURAT_USULAN_TANGGAL"),
        ("SURAT_PERSETUJUAN_STATUS", "SURAT_PERSETUJUAN_TANGGAL"),
        ("SP2BJ_STATUS", "SP2BJ_TANGGAL"),
        ("PO_STATUS", "PO_TANGGAL"),
        ("TERBAYAR_STATUS", "TERBAYAR_TANGGAL"),
        ("SUPPLY_STATUS", "SUPPLY_TANGGAL"),
        ("EVALUASI_STATUS", "EVALUASI_TANGGAL"),
    ]
    for s_col, d_col in pairs:
        df[s_col] = df[s_col].apply(clean_status)
        df.loc[df[s_col] == "None", d_col] = ""

    # =========================
    # TABEL CHECKLIST ALA EXCEL
    # =========================
    view = pd.DataFrame()
    view["REQUEST_ID"] = df["REQUEST_ID"].astype(str)
    view["TGL_UPLOAD"] = df["TANGGAL_UPLOAD"].apply(fmt_ddmmyyyy)
    view["NO_SPBJ"] = df["NO_SPBJ_KAPAL"].astype(str)
    view["JUDUL"] = df["JUDUL_PERMINTAAN"].astype(str)

    view["EVAL"] = df["EVALUASI_STATUS"].apply(status_icon)
    view["EVAL_TGL"] = df["EVALUASI_TANGGAL"].apply(fmt_ddmmyyyy)

    view["USULAN"] = df["SURAT_USULAN_STATUS"].apply(status_icon)
    view["USULAN_TGL"] = df["SURAT_USULAN_TANGGAL"].apply(fmt_ddmmyyyy)

    view["SETUJU"] = df["SURAT_PERSETUJUAN_STATUS"].apply(status_icon)
    view["SETUJU_TGL"] = df["SURAT_PERSETUJUAN_TANGGAL"].apply(fmt_ddmmyyyy)

    view["SP2BJ"] = df["SP2BJ_STATUS"].apply(status_icon)
    view["SP2BJ_TGL"] = df["SP2BJ_TANGGAL"].apply(fmt_ddmmyyyy)

    view["PO"] = df["PO_STATUS"].apply(status_icon)
    view["PO_TGL"] = df["PO_TANGGAL"].apply(fmt_ddmmyyyy)

    view["TERBAYAR"] = df["TERBAYAR_STATUS"].apply(status_icon)
    view["TERBAYAR_TGL"] = df["TERBAYAR_TANGGAL"].apply(fmt_ddmmyyyy)

    view["SUPPLY"] = df["SUPPLY_STATUS"].apply(status_icon)
    view["SUPPLY_TGL"] = df["SUPPLY_TANGGAL"].apply(fmt_ddmmyyyy)

    view["LAST_UPDATE"] = df["LAST_UPDATE"].apply(fmt_ddmmyyyy)

    st.markdown("### Daftar Permintaan (Checklist Monitoring)")
    st.data_editor(
        view,
        use_container_width=True,
        hide_index=True,
        disabled=True,  # read-only
    )

    st.caption("Legenda: ✅ Done | ⏳ In Process | kosong = None")
