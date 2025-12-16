import base64
import json
from datetime import date, datetime, timezone, timedelta

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
# TIMEZONE (WIB)
# =========================
try:
    from zoneinfo import ZoneInfo
    JAKARTA_TZ = ZoneInfo("Asia/Jakarta")
except Exception:
    JAKARTA_TZ = None


# =========================
# HELPERS
# =========================
def post_api(payload: dict) -> dict:
    r = requests.post(WEBAPP_URL, json=payload, timeout=60)
    r.raise_for_status()
    return r.json()


def clean_status(x) -> str:
    """Normalisasi status ke salah satu: None / In Process / Done."""
    if x is None:
        return "None"
    s = str(x).strip()
    if s == "" or s.lower() in ["none", "null", "nan", "false"]:
        return "None"
    # normalisasi variasi
    s_low = s.lower()
    if s_low in ["done", "selesai", "finish", "finished", "ok"]:
        return "Done"
    if s_low in ["in process", "process", "proses", "on progress", "progress"]:
        return "In Process"
    # kalau user nyimpen "True" (legacy)
    if s_low in ["true", "1", "checked", "yes", "y"]:
        return "Done"
    # fallback: kalau sudah bukan None, tetap tampilkan (tapi kita batasi opsinya di UI)
    if s in ["None", "In Process", "Done"]:
        return s
    return "In Process"


def parse_date_safe(x):
    """
    Terima:
      - 'YYYY-MM-DD'
      - 'YYYY-MM-DDTHH:MM:SS.sssZ'
      - 'YYYY-MM-DDTHH:MM:SS+00:00'
      - '' / None / False / 'None'
    Return:
      - date atau None
    """
    if not x:
        return None
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return None

    s = str(x).strip()
    if s.lower() in ["none", "nan", "nat", "false", "0"]:
        return None

    # ISO datetime
    if "T" in s:
        try:
            if s.endswith("Z"):
                dt_utc = datetime.fromisoformat(s.replace("Z", "+00:00"))
            else:
                dt_utc = datetime.fromisoformat(s)

            if dt_utc.tzinfo is None:
                dt_utc = dt_utc.replace(tzinfo=timezone.utc)

            if JAKARTA_TZ:
                return dt_utc.astimezone(JAKARTA_TZ).date()
            else:
                return (dt_utc + timedelta(hours=7)).date()
        except Exception:
            return None

    # tanggal polos
    try:
        return date.fromisoformat(s[:10])
    except Exception:
        return None


def iso_or_empty(d: date | None) -> str:
    """Simpan ke backend sebagai YYYY-MM-DD (tanpa jam) supaya aman timezone."""
    return d.isoformat() if d else ""


def fmt_ddmmyyyy(x) -> str:
    d = x if isinstance(x, date) else parse_date_safe(x)
    return d.strftime("%d-%m-%Y") if d else ""


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

        if isinstance(v, list):
            return v

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
    # super kompatibel (kadang backend minta key / teknik_key)
    res = post_api({"action": "list_requests", "key": TEKNIK_KEY, "teknik_key": TEKNIK_KEY})
    if not res.get("ok"):
        raise RuntimeError(res.get("error", "API list_requests gagal"))

    rows = res.get("data") or res.get("rows") or []
    df = pd.DataFrame(rows)
    return df


def api_update_request(request_id: str, patch: dict) -> dict:
    # super kompatibel: kirim banyak alias biar backend kamu pasti kebaca
    payload = {
        "action": "update_request",
        "key": TEKNIK_KEY,
        "teknik_key": TEKNIK_KEY,
        "request_id": request_id,
        "REQUEST_ID": request_id,
        "requestId": request_id,
        "fields": patch,
        "patch": patch,
    }
    return post_api(payload)


def ensure_cols(df: pd.DataFrame, cols: list[str], default=""):
    for c in cols:
        if c not in df.columns:
            df[c] = default
    return df


def status_date_widget(label: str, status_val_raw, date_val_raw, key_prefix: str):
    """
    UI status (None/In Process/Done) + tanggal bisa kosong.
    - Kalau status None -> tanggal otomatis kosong
    - Kalau status != None -> user boleh pilih isi tanggal atau kosong
    """
    options = ["None", "In Process", "Done"]

    status_val = clean_status(status_val_raw)
    if status_val not in options:
        status_val = "None"

    status = st.selectbox(
        f"Status {label}",
        options,
        index=options.index(status_val),
        key=f"{key_prefix}_status",
    )

    existing_date = parse_date_safe(date_val_raw)

    if status == "None":
        st.caption(f"Tanggal {label}: (kosong)")
        return status, None

    # status In Process / Done
    set_date_default = existing_date is not None
    set_date = st.checkbox(
        f"Isi tanggal {label}",
        value=set_date_default,
        key=f"{key_prefix}_setdate",
    )

    if not set_date:
        st.caption(f"Tanggal {label}: (kosong)")
        return status, None

    d = st.date_input(
        f"Tanggal {label}",
        value=existing_date or date.today(),
        key=f"{key_prefix}_date",
    )
    return status, d


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
        df_raw = api_list_requests()
    except Exception as e:
        st.error(f"Error ambil data: {e}")
        st.stop()

    if df_raw.empty:
        st.info("Belum ada permintaan masuk.")
        st.stop()

    # Normalisasi kolom menjadi UPPER biar stabil
    df = df_raw.copy()
    df.columns = [str(c).strip().upper() for c in df.columns]

    # Kolom wajib (versi STATUS + TANGGAL)
    expected_cols = [
        "REQUEST_ID", "TANGGAL_UPLOAD", "NO_SPBJ_KAPAL", "JUDUL_PERMINTAAN",
        "FILES", "FILES_JSON",

        "EVALUASI_STATUS", "EVALUASI_TANGGAL",

        "SURAT_USULAN_STATUS", "SURAT_USULAN_TANGGAL",
        "SURAT_PERSETUJUAN_STATUS", "SURAT_PERSETUJUAN_TANGGAL",

        "SP2BJ_STATUS", "SP2BJ_TANGGAL",
        "PO_STATUS", "PO_TANGGAL",
        "TERBAYAR_STATUS", "TERBAYAR_TANGGAL",

        "SUPPLY_STATUS", "SUPPLY_TANGGAL",
        "LAST_UPDATE",
    ]
    df = ensure_cols(df, expected_cols, default="")

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
    # TABEL (HANYA SATU)
    # =========================
    st.markdown("### Daftar Permintaan")

    show_cols = [
        "REQUEST_ID", "TANGGAL_UPLOAD", "NO_SPBJ_KAPAL", "JUDUL_PERMINTAAN",

        "EVALUASI_STATUS", "EVALUASI_TANGGAL",

        "SURAT_USULAN_STATUS", "SURAT_USULAN_TANGGAL",
        "SURAT_PERSETUJUAN_STATUS", "SURAT_PERSETUJUAN_TANGGAL",

        "SP2BJ_STATUS", "SP2BJ_TANGGAL",
        "PO_STATUS", "PO_TANGGAL",
        "TERBAYAR_STATUS", "TERBAYAR_TANGGAL",

        "SUPPLY_STATUS", "SUPPLY_TANGGAL",
        "LAST_UPDATE",
    ]
    show_df = df[show_cols].copy()

    # Format tanggal jadi dd-mm-yyyy untuk tampilan tabel
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
    for c in date_cols:
        if c in show_df.columns:
            show_df[c] = show_df[c].apply(fmt_ddmmyyyy)

    st.dataframe(show_df, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("### Update Progress (pilih 1 REQUEST_ID)")

    rid_list = df["REQUEST_ID"].astype(str).tolist()
    selected_rid = st.selectbox("REQUEST_ID", rid_list)

    row = df[df["REQUEST_ID"].astype(str) == str(selected_rid)].iloc[0].to_dict()

    # Ambil file lampiran (beberapa data kadang nyasar di kolom lain)
    files_list = parse_files_any(
        row.get("FILES"),
        row.get("FILES_JSON"),
    )

    # DETAIL INFO
    colA, colB = st.columns([1.2, 1])

    with colA:
        st.write("**Tanggal Upload:**", fmt_ddmmyyyy(row.get("TANGGAL_UPLOAD", "")))
        st.write("**No SPBJ Kapal:**", row.get("NO_SPBJ_KAPAL", ""))
        st.write("**Judul:**", row.get("JUDUL_PERMINTAAN", ""))

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

    # ===== FORM INPUTS =====
    with colB:
        st.markdown("#### 1) Evaluasi Cabang")
        eval_status, eval_tgl = status_date_widget(
            "Evaluasi",
            row.get("EVALUASI_STATUS"),
            row.get("EVALUASI_TANGGAL"),
            key_prefix="eval"
        )

        st.markdown("#### 2) Surat Usulan ke Pusat")
        usulan_status, usulan_tgl = status_date_widget(
            "Surat Usulan",
            row.get("SURAT_USULAN_STATUS"),
            row.get("SURAT_USULAN_TANGGAL"),
            key_prefix="usulan"
        )

        st.markdown("#### 3) Surat Persetujuan Pusat")
        setuju_status, setuju_tgl = status_date_widget(
            "Surat Persetujuan",
            row.get("SURAT_PERSETUJUAN_STATUS"),
            row.get("SURAT_PERSETUJUAN_TANGGAL"),
            key_prefix="setuju"
        )

    st.markdown("#### 4) Administrasi Cabang")
    c1, c2, c3 = st.columns(3)
    with c1:
        sp2bj_status, sp2bj_tgl = status_date_widget(
            "SP2B/J",
            row.get("SP2BJ_STATUS"),
            row.get("SP2BJ_TANGGAL"),
            key_prefix="sp2bj"
        )
    with c2:
        po_status, po_tgl = status_date_widget(
            "PO",
            row.get("PO_STATUS"),
            row.get("PO_TANGGAL"),
            key_prefix="po"
        )
    with c3:
        terbayar_status, terbayar_tgl = status_date_widget(
            "Terbayar",
            row.get("TERBAYAR_STATUS"),
            row.get("TERBAYAR_TANGGAL"),
            key_prefix="terbayar"
        )

    st.markdown("#### 5) Supply Barang")
    supply_status, supply_tgl = status_date_widget(
        "Supply",
        row.get("SUPPLY_STATUS"),
        row.get("SUPPLY_TANGGAL"),
        key_prefix="supply"
    )

    st.markdown("---")

    if st.button("💾 Simpan Update"):
        patch = {
            # Evaluasi
            "EVALUASI_STATUS": eval_status,
            "EVALUASI_TANGGAL": iso_or_empty(eval_tgl),

            # Surat
            "SURAT_USULAN_STATUS": usulan_status,
            "SURAT_USULAN_TANGGAL": iso_or_empty(usulan_tgl),

            "SURAT_PERSETUJUAN_STATUS": setuju_status,
            "SURAT_PERSETUJUAN_TANGGAL": iso_or_empty(setuju_tgl),

            # Administrasi
            "SP2BJ_STATUS": sp2bj_status,
            "SP2BJ_TANGGAL": iso_or_empty(sp2bj_tgl),

            "PO_STATUS": po_status,
            "PO_TANGGAL": iso_or_empty(po_tgl),

            "TERBAYAR_STATUS": terbayar_status,
            "TERBAYAR_TANGGAL": iso_or_empty(terbayar_tgl),

            # Supply
            "SUPPLY_STATUS": supply_status,
            "SUPPLY_TANGGAL": iso_or_empty(supply_tgl),
        }

        # Pastikan: kalau status None, tanggal kosong (double safety)
        for s_col, d_col in pairs:
            if s_col in patch and d_col in patch:
                if clean_status(patch[s_col]) == "None":
                    patch[d_col] = ""

        # Alias lowercase juga (banyak backend Apps Script pakai lowercase)
        patch_alias = {}
        for k, v in patch.items():
            patch_alias[k] = v
            patch_alias[k.lower()] = v

        try:
            res2 = api_update_request(selected_rid, patch_alias)

            if res2.get("ok"):
                st.success("✅ Update tersimpan. Refresh data…")
                st.rerun()
            else:
                st.error(f"Gagal: {res2.get('error')}")
                st.json(res2)
        except Exception as e:
            st.error(f"Error simpan: {e}")
