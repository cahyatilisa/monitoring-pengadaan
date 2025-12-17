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

# =========================
# API HELPERS
# =========================
def post_api(payload: dict) -> dict:
    r = requests.post(WEBAPP_URL, json=payload, timeout=60)
    r.raise_for_status()
    return r.json()


# =========================
# DATA HELPERS
# =========================
STATUS_OPTIONS = ["None", "In Process", "Done"]

def clean_status(x) -> str:
    """Normalisasi status agar selalu: None / In Process / Done"""
    if x is None:
        return "None"
    s = str(x).strip()
    if not s:
        return "None"
    low = s.lower()
    if low in ["none", "null", "nan"]:
        return "None"
    if low in ["in process", "in_progress", "progress", "processing", "ongoing", "on progress", "onprogress"]:
        return "In Process"
    if low in ["done", "selesai", "finish", "finished", "completed", "ok", "yes", "true", "1"]:
        return "Done"
    return "None"


def norm_date_str(x) -> str:
    """
    Ambil tanggal sebagai string 'YYYY-MM-DD' dari:
    - 'YYYY-MM-DD'
    - 'YYYY-MM-DDTHH:MM:SS...'
    - Date object (jarang, tapi aman)
    """
    if x is None:
        return ""
    if isinstance(x, bool):
        return ""
    if isinstance(x, (int, float)):
        return ""
    if isinstance(x, date):
        return x.isoformat()

    s = str(x).strip()
    if not s or s.lower() == "none":
        return ""
    # ISO panjang -> ambil 10 char pertama
    s10 = s[:10]
    try:
        datetime.strptime(s10, "%Y-%m-%d")
        return s10
    except Exception:
        return ""


def to_display_ddmmyyyy(iso_yyyy_mm_dd: str) -> str:
    """Konversi 'YYYY-MM-DD' -> 'dd-mm-yyyy' untuk tampilan tabel."""
    s = norm_date_str(iso_yyyy_mm_dd)
    if not s:
        return ""
    try:
        d = datetime.strptime(s, "%Y-%m-%d").date()
        return d.strftime("%d-%m-%Y")
    except Exception:
        return ""


def parse_files_json(value) -> list:
    """
    FILES_JSON disimpan sebagai JSON string list.
    Return list of dict: [{name, fileId, viewUrl, downloadUrl}, ...]
    """
    if not value:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return []
        try:
            obj = json.loads(s)
            if isinstance(obj, list):
                return obj
            if isinstance(obj, dict):
                return [obj]
        except Exception:
            return []
    return []


def api_list_requests() -> pd.DataFrame:
    res = post_api({"action": "list_requests", "key": TEKNIK_KEY})
    if not res.get("ok"):
        raise RuntimeError(res.get("error", "API list_requests gagal"))
    rows = res.get("data") or []
    df = pd.DataFrame(rows)
    return df


def api_update_request(request_id: str, fields: dict) -> dict:
    # fields: dict berisi kolom UPPERCASE sesuai spreadsheet (mis. EVALUASI_STATUS)
    res = post_api({
        "action": "update_request",
        "key": TEKNIK_KEY,
        "request_id": request_id,
        "fields": fields
    })
    return res


# =========================
# UI HELPERS (FORM STAGE)
# =========================
def stage_input(stage_code: str, label: str, row: dict, req_id: str):
    """
    stage_code: mis. "EVALUASI" / "SURAT_USULAN" / dst
    Kolom yang dipakai: f"{stage_code}_STATUS" dan f"{stage_code}_TANGGAL"
    Rules:
    - None / In Process -> tanggal kosong, tidak tampil date_input
    - Done -> tampil date_input, default pakai tanggal lama jika ada, else hari ini
    """
    status_col = f"{stage_code}_STATUS"
    date_col = f"{stage_code}_TANGGAL"

    cur_status = clean_status(row.get(status_col, "None"))
    cur_date_iso = norm_date_str(row.get(date_col, ""))

    st.markdown(f"### {label}")
    status_key = f"{req_id}_{stage_code}_status"
    date_key = f"{req_id}_{stage_code}_date"

    status = st.selectbox(
        f"Status {label}",
        STATUS_OPTIONS,
        index=STATUS_OPTIONS.index(cur_status) if cur_status in STATUS_OPTIONS else 0,
        key=status_key
    )

    chosen_date = None
    if status == "Done":
        # default date: tanggal lama kalau ada, else today
        if cur_date_iso:
            try:
                default_date = datetime.strptime(cur_date_iso, "%Y-%m-%d").date()
            except Exception:
                default_date = date.today()
        else:
            default_date = date.today()

        chosen_date = st.date_input(
            f"Tanggal {label} (muncul hanya jika Done)",
            value=default_date,
            key=date_key
        )
    else:
        st.caption("Tanggal: (kosong)")

    # Return patch fields (UPPERCASE kolom spreadsheet)
    patch = {
        status_col: status,
        date_col: chosen_date.isoformat() if (status == "Done" and chosen_date) else ""
    }
    return patch


# =========================
# APP TITLE
# =========================
st.title("📦 Monitoring & Update Alur Pengadaan (Permintaan Kapal → Teknik)")

tab_kapal, tab_teknik = st.tabs(["🛳️ User Kapal (Upload)", "🛠️ User Teknik (Monitoring & Update)"])

# =========================
# TAB: USER KAPAL (UPLOAD)
# =========================
with tab_kapal:
    st.subheader("Upload Permintaan Pengadaan (User Kapal)")

    with st.form("form_kapal", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            tgl_upload = st.date_input("Tanggal Upload", value=date.today())
        with c2:
            no_spbj = st.text_input("No. SPBJ Kapal (opsional)")

        judul = st.text_input("Judul Permintaan", placeholder="Contoh: Pengadaan sparepart mesin ...")

        files = st.file_uploader(
            "Upload Dokumen (boleh lebih dari 1 file)",
            accept_multiple_files=True
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
                "tanggal_upload": tgl_upload.isoformat(),
                "no_spbj_kapal": no_spbj.strip(),
                "judul_permintaan": judul.strip(),
                "files": files_payload
            })
            if res.get("ok"):
                st.success(f"✅ Berhasil! REQUEST_ID: {res.get('request_id')}")
                st.info("Permintaan sudah masuk. Tim Teknik bisa download file dan update progress.")
            else:
                st.error(f"Gagal: {res.get('error')}")
        except Exception as e:
            st.error(f"Error koneksi / API: {e}")


# =========================
# TAB: USER TEKNIK
# =========================
with tab_teknik:
    st.subheader("Monitoring & Update (User Teknik)")

    # -------- Login gate --------
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

    if st.button("Logout"):
        st.session_state.teknik_logged = False
        st.rerun()

    # -------- Load data --------
    try:
        df = api_list_requests()
    except Exception as e:
        st.error(f"Error ambil data: {e}")
        st.stop()

    if df.empty:
        st.info("Belum ada permintaan masuk.")
        st.stop()

    # -------- Normalize columns to UPPERCASE (match spreadsheet headers) --------
    df.columns = [str(c).strip().upper() for c in df.columns]

    # kolom wajib
    must_have = [
        "REQUEST_ID", "TANGGAL_UPLOAD", "NO_SPBJ_KAPAL", "JUDUL_PERMINTAAN", "FILES_JSON",
        "EVALUASI_STATUS", "EVALUASI_TANGGAL",
        "SURAT_USULAN_STATUS", "SURAT_USULAN_TANGGAL",
        "SURAT_PERSETUJUAN_STATUS", "SURAT_PERSETUJUAN_TANGGAL",
        "SP2BJ_STATUS", "SP2BJ_TANGGAL",
        "PO_STATUS", "PO_TANGGAL",
        "TERBAYAR_STATUS", "TERBAYAR_TANGGAL",
        "SUPPLY_STATUS", "SUPPLY_TANGGAL",
        "LAST_UPDATE"
    ]
    for c in must_have:
        if c not in df.columns:
            df[c] = ""

    # =========================
    # AUTO-CLEAN DATA WARISAN:
    # kalau status None/In Process tapi tanggal terisi -> kosongkan tanggal (untuk tampilan)
    # =========================
    pairs = [
        ("EVALUASI_STATUS", "EVALUASI_TANGGAL"),
        ("SURAT_USULAN_STATUS", "SURAT_USULAN_TANGGAL"),
        ("SURAT_PERSETUJUAN_STATUS", "SURAT_PERSETUJUAN_TANGGAL"),
        ("SP2BJ_STATUS", "SP2BJ_TANGGAL"),
        ("PO_STATUS", "PO_TANGGAL"),
        ("TERBAYAR_STATUS", "TERBAYAR_TANGGAL"),
        ("SUPPLY_STATUS", "SUPPLY_TANGGAL"),
    ]
    for s_col, d_col in pairs:
        df[s_col] = df[s_col].apply(clean_status)
        # tampilkan tanggal hanya kalau Done
        df.loc[df[s_col] != "Done", d_col] = ""

    # =========================
    # FORMAT DATE COLUMNS FOR TABLE DISPLAY (dd-mm-yyyy)
    # =========================
    date_cols = [
        "TANGGAL_UPLOAD",
        "EVALUASI_TANGGAL",
        "SURAT_USULAN_TANGGAL",
        "SURAT_PERSETUJUAN_TANGGAL",
        "SP2BJ_TANGGAL",
        "PO_TANGGAL",
        "TERBAYAR_TANGGAL",
        "SUPPLY_TANGGAL",
        "LAST_UPDATE",
    ]
    df_display = df.copy()
    for c in date_cols:
        df_display[c] = df_display[c].apply(to_display_ddmmyyyy)

    # =========================
    # TABLE (ONE TABLE ONLY)
    # =========================
    st.markdown("## Daftar Permintaan")

    show_cols = [
        "REQUEST_ID", "TANGGAL_UPLOAD", "NO_SPBJ_KAPAL", "JUDUL_PERMINTAAN",
        "EVALUASI_STATUS", "EVALUASI_TANGGAL",
        "SURAT_USULAN_STATUS", "SURAT_USULAN_TANGGAL",
        "SURAT_PERSETUJUAN_STATUS", "SURAT_PERSETUJUAN_TANGGAL",
        "SP2BJ_STATUS", "SP2BJ_TANGGAL",
        "PO_STATUS", "PO_TANGGAL",
        "TERBAYAR_STATUS", "TERBAYAR_TANGGAL",
        "SUPPLY_STATUS", "SUPPLY_TANGGAL",
        "LAST_UPDATE"
    ]

    st.dataframe(df_display[show_cols], use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("## Update Progress (pilih 1 REQUEST_ID)")

    rid_list = df["REQUEST_ID"].astype(str).tolist()
    selected_rid = st.selectbox("REQUEST_ID", rid_list)

    row = df[df["REQUEST_ID"].astype(str) == str(selected_rid)].iloc[0].to_dict()

    # -------- Detail kiri + lampiran --------
    colA, colB = st.columns([1.2, 1])

    with colA:
        st.write("**Tanggal Upload:**", to_display_ddmmyyyy(row.get("TANGGAL_UPLOAD")))
        st.write("**No SPBJ Kapal:**", row.get("NO_SPBJ_KAPAL", ""))
        st.write("**Judul:**", row.get("JUDUL_PERMINTAAN", ""))

        files_list = parse_files_json(row.get("FILES_JSON", ""))
        st.markdown("**File Lampiran (Download):**")
        if not files_list:
            st.caption("(Tidak ada file / belum terbaca)")
        else:
            for f in files_list:
                name = f.get("name", "file")
                url = f.get("downloadUrl") or f.get("viewUrl")
                if url:
                    st.markdown(f"- [{name}]({url})")
                else:
                    fid = f.get("fileId") or f.get("id")
                    if fid:
                        st.markdown(f"- [{name}](https://drive.google.com/uc?export=download&id={fid})")
                    else:
                        st.markdown(f"- {name}")

    # -------- Form kanan (7 tahap) --------
    with colB:
        patch_all = {}

        patch_all.update(stage_input("EVALUASI", "1) Evaluasi Cabang", row, str(selected_rid)))
        patch_all.update(stage_input("SURAT_USULAN", "2) Surat Usulan ke Pusat", row, str(selected_rid)))
        patch_all.update(stage_input("SURAT_PERSETUJUAN", "3) Surat Persetujuan Pusat", row, str(selected_rid)))
        patch_all.update(stage_input("SP2BJ", "4) SP2BJ", row, str(selected_rid)))
        patch_all.update(stage_input("PO", "5) PO", row, str(selected_rid)))
        patch_all.update(stage_input("TERBAYAR", "6) Terbayar", row, str(selected_rid)))
        patch_all.update(stage_input("SUPPLY", "7) Supply Barang", row, str(selected_rid)))

        st.markdown("---")
        if st.button("💾 Simpan Update"):
            try:
                # kirim patch ke backend (kolom uppercase)
                res2 = api_update_request(str(selected_rid), patch_all)
                if res2.get("ok"):
                    st.success("✅ Update tersimpan dan tabel akan refresh.")
                    st.rerun()
                else:
                    st.error(f"Gagal: {res2.get('error')}")
            except Exception as e:
                st.error(f"Error simpan: {e}")
