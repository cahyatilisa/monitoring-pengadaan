import base64
import json
from datetime import date, datetime

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


def to_bool(x) -> bool:
    if isinstance(x, bool):
        return x
    if x is None:
        return False
    if isinstance(x, (int, float)):
        return x != 0
    if isinstance(x, str):
        return x.strip().lower() in ["true", "yes", "y", "1", "checked", "ok"]
    return False


def parse_date_value(x):
    """
    Terima: '2025-12-15T10:00:00.000Z' / '2025-12-15' / '' / 'None' / False
    Return: date atau None
    """
    if x is None:
        return None
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return None
    s = str(x).strip()
    if s == "" or s.lower() == "none":
        return None

    # kalau format ISO datetime
    if "T" in s:
        s = s.split("T")[0]

    try:
        return date.fromisoformat(s)
    except Exception:
        return None


def iso_or_empty(d: date | None) -> str:
    return d.isoformat() if d else ""


def parse_files_any(*values):
    """
    Mencoba membaca daftar file dari beberapa kemungkinan kolom:
    - list of dicts
    - string JSON list
    Return list[dict]
    """
    for v in values:
        if not v:
            continue

        # sudah list
        if isinstance(v, list):
            return v

        # string JSON
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("[") or s.startswith("{"):
                try:
                    obj = json.loads(s)
                    if isinstance(obj, list):
                        return obj
                    if isinstance(obj, dict):
                        return [obj]
                except Exception:
                    pass

    return []


def api_list_requests() -> pd.DataFrame:
    res = post_api({"action": "list_requests", "key": TEKNIK_KEY})
    if not res.get("ok"):
        raise RuntimeError(res.get("error", "API list_requests gagal"))

    rows = res.get("data") or res.get("rows") or []
    df = pd.DataFrame(rows)

    # pastikan kolom penting ada
    if "request_id" not in df.columns and "REQUEST_ID" in df.columns:
        df = df.rename(columns={"REQUEST_ID": "request_id"})

    return df


def api_update_request(request_id: str, fields: dict) -> dict:
    return post_api({
        "action": "update_request",
        "key": TEKNIK_KEY,
        "request_id": request_id,
        "fields": fields
    })


# =========================
# UI
# =========================
st.title("📦 Monitoring & Update Alur Pengadaan (Permintaan Kapal → Teknik)")

tab_kapal, tab_teknik = st.tabs(["🛳️ User Kapal (Upload)", "🛠️ User Teknik (Monitoring)"])


# =========================
# TAB: USER KAPAL
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
                st.info("Permintaan kamu sudah masuk. Tim Teknik bisa download file dan update progress.")
            else:
                st.error(f"Gagal: {res.get('error')}")
        except Exception as e:
            st.error(f"Error koneksi / API: {e}")


# =========================
# TAB: USER TEKNIK
# =========================
with tab_teknik:
    st.subheader("Monitoring & Update (User Teknik)")

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

    # =============== sudah login ===============
    try:
        df = api_list_requests()
    except Exception as e:
        st.error(f"Error ambil data: {e}")
        st.stop()

    if df.empty:
        st.info("Belum ada permintaan masuk.")
        st.stop()

    # Normalisasi kolom dasar (pakai snake_case kecil)
    # kalau ada kolom uppercase dari sheet lama, coba turunkan
    df.columns = [str(c).strip() for c in df.columns]

    # kolom wajib
    must_have = [
        "request_id", "tanggal_upload", "no_spbj_kapal", "judul_permintaan",
        "files", "files_json",
        "evaluasi_status", "evaluasi_tanggal",
        "surat_usulan_tanggal", "surat_persetujuan_tanggal",
        "sp2bj_check", "sp2bj_tanggal",
        "po_check", "po_tanggal",
        "terbayar_check", "terbayar_tanggal",
        "supply_status", "supply_tanggal",
        "last_update"
    ]
    for c in must_have:
        if c not in df.columns:
            df[c] = ""

    # =========================
    # TABEL RINGKAS (HANYA SATU)
    # =========================
    st.markdown("### Daftar
