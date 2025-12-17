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

STAGES = [
    ("EVALUASI", "Evaluasi Cabang"),
    ("SURAT_USULAN", "Surat Usulan ke Pusat"),
    ("SURAT_PERSETUJUAN", "Surat Persetujuan Pusat"),
    ("SP2BJ", "SP2BJ"),
    ("PO", "PO"),
    ("TERBAYAR", "Terbayar"),
    ("SUPPLY", "Supply Barang"),
]
STATUS_OPTIONS = ["None", "In Process", "Done"]

# =========================
# API HELPERS
# =========================
def post_api(payload: dict) -> dict:
    r = requests.post(WEBAPP_URL, json=payload, timeout=60)
    r.raise_for_status()
    return r.json()

def api_submit_request(tanggal_upload: date, no_spbj: str, judul: str, files_payload: list[dict]) -> dict:
    return post_api({
        "action": "submit_request",
        "tanggal_upload": tanggal_upload.strftime("%Y-%m-%d"),
        "no_spbj_kapal": (no_spbj or "").strip(),
        "judul_permintaan": judul.strip(),
        "files": files_payload,
    })

def api_list_requests() -> pd.DataFrame:
    res = post_api({"action": "list_requests", "key": TEKNIK_KEY})
    if not res.get("ok"):
        raise RuntimeError(res.get("error", "API list_requests gagal"))
    rows = res.get("data") or res.get("rows") or []
    return pd.DataFrame(rows)

def api_update_request(request_id: str, fields: dict) -> dict:
    return post_api({
        "action": "update_request",
        "key": TEKNIK_KEY,
        "request_id": request_id,
        "fields": fields,
    })

# =========================
# DATA HELPERS
# =========================
def clean_status(x) -> str:
    s = str(x or "").strip()
    if not s or s.lower() == "none":
        return "None"
    s_low = s.lower()
    if s_low in ["in process", "in_progress", "progress", "ongoing", "process"]:
        return "In Process"
    if s_low in ["done", "selesai", "completed", "finish", "finished", "ok", "yes", "true", "1"]:
        return "Done"
    return "None"

def parse_date_any(x):
    """
    Terima: 'YYYY-MM-DD', 'YYYY-MM-DDTHH:MM:SSZ', '', None
    Return: date atau None
    """
    if x is None:
        return None
    s = str(x).strip()
    if s == "" or s.lower() == "none":
        return None
    if "T" in s:
        s = s.split("T")[0]
    try:
        return date.fromisoformat(s[:10])
    except Exception:
        return None

def ddmmyyyy_or_empty(d: date | None) -> str:
    return d.strftime("%d-%m-%Y") if d else ""

def iso_or_empty(d: date | None) -> str:
    return d.strftime("%Y-%m-%d") if d else ""

def parse_files_json(x):
    if not x:
        return []
    if isinstance(x, list):
        return x
    if isinstance(x, str):
        s = x.strip()
        if s.startswith("[") or s.startswith("{"):
            try:
                obj = json.loads(s)
                if isinstance(obj, list):
                    return obj
                if isinstance(obj, dict):
                    return [obj]
            except Exception:
                return []
    return []

def first_file_download_link(files_json):
    files = parse_files_json(files_json)
    if not files:
        return ""
    f0 = files[0] or {}
    url = f0.get("downloadUrl") or f0.get("viewUrl")
    if url:
        return url
    fid = f0.get("fileId") or f0.get("id")
    if fid:
        return f"https://drive.google.com/uc?export=download&id={fid}"
    return ""

# =========================
# UI
# =========================
st.title("📦 Monitoring & Update Alur Pengadaan (Permintaan Kapal → Teknik)")

tab_kapal, tab_teknik = st.tabs(["🛳️ User Kapal (Upload)", "🛠️ User Teknik (Monitoring & Update)"])

# =========================
# TAB: USER KAPAL
# =========================
with tab_kapal:
    st.subheader("Upload Permintaan Pengadaan")

    with st.form("form_kapal", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            tanggal_upload = st.date_input("Tanggal Upload", value=date.today(), format="DD/MM/YYYY")
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
            res = api_submit_request(tanggal_upload, no_spbj, judul, files_payload)
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

    # tombol logout
    if st.button("Logout"):
        st.session_state.teknik_logged = False
        st.rerun()

    # ambil data
    try:
        df = api_list_requests()
    except Exception as e:
        st.error(f"Error ambil data: {e}")
        st.stop()

    if df.empty:
        st.info("Belum ada permintaan masuk.")
        st.stop()

    # Normalize kolom ke UPPER agar match header spreadsheet
    df.columns = [str(c).strip().upper() for c in df.columns]

    # kolom wajib minimal
    base_cols = ["REQUEST_ID", "TANGGAL_UPLOAD", "NO_SPBJ_KAPAL", "JUDUL_PERMINTAAN", "FILES_JSON", "LAST_UPDATE"]
    for c in base_cols:
        if c not in df.columns:
            df[c] = ""

    # pastikan stage status/tanggal ada
    for code, _label in STAGES:
        s_col = f"{code}_STATUS"
        d_col = f"{code}_TANGGAL"
        if s_col not in df.columns:
            df[s_col] = "None"
        if d_col not in df.columns:
            df[d_col] = ""

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
        df.loc[df[s_col] != "Done", d_col] = ""

    # kolom link file pertama
    df["FILE_1"] = df["FILES_JSON"].apply(first_file_download_link)

    # =========================
    # Buat tabel display + editable (Excel-like)
    # =========================
    show_cols = [
        "REQUEST_ID", "TANGGAL_UPLOAD", "NO_SPBJ_KAPAL", "JUDUL_PERMINTAAN", "FILE_1",
        "EVALUASI_STATUS", "EVALUASI_TANGGAL",
        "SURAT_USULAN_STATUS", "SURAT_USULAN_TANGGAL",
        "SURAT_PERSETUJUAN_STATUS", "SURAT_PERSETUJUAN_TANGGAL",
        "SP2BJ_STATUS", "SP2BJ_TANGGAL",
        "PO_STATUS", "PO_TANGGAL",
        "TERBAYAR_STATUS", "TERBAYAR_TANGGAL",
        "SUPPLY_STATUS", "SUPPLY_TANGGAL",
        "LAST_UPDATE",
    ]
    for c in show_cols:
        if c not in df.columns:
            df[c] = ""

    df_show = df[show_cols].copy()

    # convert tanggal kolom ke date (untuk editor)
    date_cols = [c for c in df_show.columns if c.endswith("_TANGGAL")] + ["TANGGAL_UPLOAD", "LAST_UPDATE"]
    for c in date_cols:
        df_show[c] = df_show[c].apply(parse_date_any)

    # buat baseline untuk deteksi perubahan
    df_base = df_show.copy(deep=True)

    st.markdown("### Daftar Permintaan (edit langsung di tabel, lalu klik **Simpan Update**)")

    col_config = {
        "REQUEST_ID": st.column_config.TextColumn("REQUEST_ID", disabled=True),
        "TANGGAL_UPLOAD": st.column_config.DateColumn("TANGGAL_UPLOAD", format="DD-MM-YYYY", disabled=True),
        "NO_SPBJ_KAPAL": st.column_config.TextColumn("NO_SPBJ_KAPAL", disabled=True),
        "JUDUL_PERMINTAAN": st.column_config.TextColumn("JUDUL_PERMINTAAN", disabled=True),
        "FILE_1": st.column_config.LinkColumn("FILE_1 (Download)", display_text="Download"),
        "LAST_UPDATE": st.column_config.DateColumn("LAST_UPDATE", format="DD-MM-YYYY", disabled=True),
    }

    # config status/date columns
    for code, label in STAGES:
        col_config[f"{code}_STATUS"] = st.column_config.SelectboxColumn(
            f"{label} - STATUS",
            options=STATUS_OPTIONS,
            required=True,
        )
        col_config[f"{code}_TANGGAL"] = st.column_config.DateColumn(
            f"{label} - TANGGAL",
            format="DD-MM-YYYY",
        )

    edited = st.data_editor(
        df_show,
        use_container_width=True,
        hide_index=True,
        column_config=col_config,
        key="editor_teknik",
    )

    # enforce rule after edit (front-end enforcement)
    for code, _label in STAGES:
        s_col = f"{code}_STATUS"
        d_col = f"{code}_TANGGAL"
        mask_not_done = edited[s_col].apply(clean_status) != "Done"
        edited.loc[mask_not_done, d_col] = None

    # tombol simpan
    if st.button("💾 Simpan Update"):
        # validasi: Done harus punya tanggal
        errors = []
        for code, label in STAGES:
            s_col = f"{code}_STATUS"
            d_col = f"{code}_TANGGAL"
            done_no_date = (edited[s_col].apply(clean_status) == "Done") & (edited[d_col].isna())
            if done_no_date.any():
                errors.append(f"- {label}: STATUS Done wajib isi TANGGAL")

        if errors:
            st.error("Ada yang belum valid:\n" + "\n".join(errors))
            st.stop()

        # cari perubahan per row
        updated_count = 0
        for i in range(len(edited)):
            rid = str(edited.loc[i, "REQUEST_ID"])
            fields = {}

            # status/tanggal stages
            for code, _label in STAGES:
                s_col = f"{code}_STATUS"
                d_col = f"{code}_TANGGAL"

                new_s = clean_status(edited.loc[i, s_col])
                old_s = clean_status(df_base.loc[i, s_col])
                new_d = edited.loc[i, d_col]
                old_d = df_base.loc[i, d_col]

                if new_s != old_s:
                    fields[s_col] = new_s

                # tanggal: hanya disimpan kalau Done, selain itu ""
                if new_s != "Done":
                    new_d_str = ""
                else:
                    new_d_str = iso_or_empty(new_d)

                if old_s != "Done":
                    old_d_str = ""
                else:
                    old_d_str = iso_or_empty(old_d)

                if new_d_str != old_d_str:
                    fields[d_col] = new_d_str

            if fields:
                try:
                    res = api_update_request(rid, fields)
                    if not res.get("ok"):
                        st.error(f"Gagal update {rid}: {res.get('error')}")
                        st.stop()
                    updated_count += 1
                except Exception as e:
                    st.error(f"Error update {rid}: {e}")
                    st.stop()

        st.success(f"✅ Tersimpan. Baris yang berubah: {updated_count}")
        st.rerun()
