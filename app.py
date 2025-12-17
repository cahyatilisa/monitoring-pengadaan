import base64
import json
from datetime import date, datetime
from typing import Any, Optional

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


STATUS_OPTIONS = ["None", "In Process", "Done"]


# =========================
# HELPERS
# =========================
def post_api(payload: dict) -> dict:
    r = requests.post(WEBAPP_URL, json=payload, timeout=60)
    r.raise_for_status()
    return r.json()


def clean_status(x: Any) -> str:
    if x is None:
        return "None"
    s = str(x).strip()
    if s == "" or s.lower() in ["none", "null", "nan", "nat"]:
        return "None"
    s_low = s.lower()
    if s_low in ["in process", "in_progress", "progress", "process", "ongoing"]:
        return "In Process"
    if s_low in ["done", "completed", "finish", "finished", "ok", "yes", "true", "1"]:
        return "Done"
    if s in STATUS_OPTIONS:
        return s
    return "None"


def parse_date_value(x: Any) -> Optional[date]:
    if x is None:
        return None
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return None
    s = str(x).strip()
    if s == "" or s.lower() in ["none", "nan", "nat", "false"]:
        return None
    s = s[:10]  # ambil YYYY-MM-DD dari ISO panjang
    try:
        return date.fromisoformat(s)
    except Exception:
        return None


def iso_or_empty(d: Optional[date]) -> str:
    return d.isoformat() if d else ""


def fmt_ddmmyyyy(x: Any) -> str:
    d = parse_date_value(x)
    return d.strftime("%d-%m-%Y") if d else ""


def ensure_cols(df: pd.DataFrame, cols: list[str], default: Any = "") -> pd.DataFrame:
    for c in cols:
        if c not in df.columns:
            df[c] = default
    return df


def looks_like_files_json_str(s: str) -> bool:
    if not isinstance(s, str):
        return False
    t = s.strip()
    if not (t.startswith("[") or t.startswith("{")):
        return False
    # indikator kuat file json
    return ("fileId" in t) or ("downloadUrl" in t) or ("viewUrl" in t) or ('"name"' in t)


def parse_files_from_any(v: Any):
    """Return list[dict] dari v (bisa list, dict, atau string JSON)."""
    if v is None:
        return []
    if v == "":
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, dict):
        return [v]
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
                return []
    return []


def find_files_in_row(row: dict) -> list[dict]:
    """
    Cari lampiran dari semua kemungkinan kolom.
    - Prioritas FILES/FILES_JSON
    - Kalau kosong, scan semua kolom untuk string JSON yang mengandung fileId/viewUrl/downloadUrl
    """
    # 1) prioritas kolom umum
    for k in ["FILES", "FILES_JSON", "FILESRAW", "EVALUASI_FILES_RAW"]:
        if k in row:
            got = parse_files_from_any(row.get(k))
            if got:
                return got

    # 2) scan semua value dalam row
    for _, v in row.items():
        if isinstance(v, str) and looks_like_files_json_str(v):
            got = parse_files_from_any(v)
            if got:
                return got

    return []


# =========================
# API WRAPPERS (dibuat kompatibel dengan backend apapun)
# =========================
def api_list_requests() -> pd.DataFrame:
    # kirim key + teknik_key agar cocok untuk backend kamu yang beda versi
    res = post_api({"action": "list_requests", "key": TEKNIK_KEY, "teknik_key": TEKNIK_KEY})
    if not res.get("ok"):
        raise RuntimeError(res.get("error", "API list_requests gagal"))

    rows = res.get("data") or res.get("rows") or []
    return pd.DataFrame(rows)


def api_update_request(request_id: str, patch: dict) -> dict:
    """
    Kirim payload update dalam 2 gaya sekaligus:
    - key dan teknik_key
    - fields dan patch
    Ditambah: duplikasi key UPPERCASE dan lowercase di patch.
    """
    patch2 = {}
    for k, v in patch.items():
        patch2[k] = v
        patch2[k.lower()] = v  # duplikasi lowercase

    payload = {
        "action": "update_request",
        "key": TEKNIK_KEY,
        "teknik_key": TEKNIK_KEY,
        "request_id": request_id,
        "fields": patch2,
        "patch": patch2,
    }
    return post_api(payload)


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

    debug_mode = st.checkbox("Tampilkan debug (response API)", value=False)

    # ===== ambil data =====
    try:
        df = api_list_requests()
    except Exception as e:
        st.error(f"Error ambil data: {e}")
        st.stop()

    if df.empty:
        st.info("Belum ada permintaan masuk.")
        st.stop()

    # Normalisasi kolom ke UPPERCASE supaya konsisten di UI
    df.columns = [str(c).strip().upper() for c in df.columns]

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
    # SIMPAN LAMPIRAN WARISAN:
    # kalau dulu lampiran nyasar ke EVALUASI_STATUS
    # =========================
    if "EVALUASI_FILES_RAW" not in df.columns:
        df["EVALUASI_FILES_RAW"] = ""
    df["EVALUASI_FILES_RAW"] = df["EVALUASI_STATUS"].apply(lambda v: v if looks_like_files_json_str(v) else "")

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
    # TABEL RINGKAS
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

    # Format tanggal tampilan
    for c in [x for x in show_cols if x.endswith("_TANGGAL") or x in ["TANGGAL_UPLOAD", "LAST_UPDATE"]]:
        show_df[c] = show_df[c].apply(fmt_ddmmyyyy)

    st.dataframe(show_df, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("## Update Progress (pilih 1 REQUEST_ID)")

    rid_list = df["REQUEST_ID"].astype(str).tolist()
    selected_rid = st.selectbox("REQUEST_ID", rid_list, key="rid_select")

    row = df[df["REQUEST_ID"].astype(str) == str(selected_rid)].iloc[0].to_dict()

    # Lampiran: cari dari semua kemungkinan kolom
    files_list = find_files_in_row(row)

    # DETAIL
    colA, colB = st.columns([1.2, 1])

    with colA:
        st.write("**Tanggal Upload:**", fmt_ddmmyyyy(row.get("TANGGAL_UPLOAD")))
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

    def status_date_block(title: str, status_key: str, date_key: str, ui_key_prefix: str):
        st.markdown(f"### {title}")

        cur_status = clean_status(row.get(status_key))
        status = st.selectbox(
            f"Status {title.split(') ')[-1]}",
            STATUS_OPTIONS,
            index=STATUS_OPTIONS.index(cur_status) if cur_status in STATUS_OPTIONS else 0,
            key=f"{ui_key_prefix}_status_{selected_rid}"
        )

        cur_date = parse_date_value(row.get(date_key))

        if status == "None":
            st.caption(f"Tanggal {title.split(') ')[-1]}: (kosong)")
            d = None
        else:
            d = st.date_input(
                f"Tanggal {title.split(') ')[-1]}",
                value=cur_date or date.today(),
                key=f"{ui_key_prefix}_date_{selected_rid}"
            )

        return status, d

    with colB:
        eval_status, eval_tgl = status_date_block("1) Evaluasi Cabang", "EVALUASI_STATUS", "EVALUASI_TANGGAL", "eval")
        usulan_status, usulan_tgl = status_date_block("2) Surat Usulan ke Pusat", "SURAT_USULAN_STATUS", "SURAT_USULAN_TANGGAL", "usulan")
        setuju_status, setuju_tgl = status_date_block("3) Surat Persetujuan Pusat", "SURAT_PERSETUJUAN_STATUS", "SURAT_PERSETUJUAN_TANGGAL", "setuju")

    st.markdown("---")

    c1, c2, c3 = st.columns(3)
    with c1:
        sp2bj_status, sp2bj_tgl = status_date_block("4) SP2BJ", "SP2BJ_STATUS", "SP2BJ_TANGGAL", "sp2bj")
    with c2:
        po_status, po_tgl = status_date_block("5) PO", "PO_STATUS", "PO_TANGGAL", "po")
    with c3:
        terbayar_status, terbayar_tgl = status_date_block("6) Terbayar", "TERBAYAR_STATUS", "TERBAYAR_TANGGAL", "terbayar")

    st.markdown("---")

    supply_status, supply_tgl = status_date_block("7) Supply Barang", "SUPPLY_STATUS", "SUPPLY_TANGGAL", "supply")

    st.markdown("---")

    if st.button("💾 Simpan Update", key="btn_save"):
        patch = {
            "EVALUASI_STATUS": eval_status,
            "EVALUASI_TANGGAL": iso_or_empty(eval_tgl) if eval_status != "None" else "",

            "SURAT_USULAN_STATUS": usulan_status,
            "SURAT_USULAN_TANGGAL": iso_or_empty(usulan_tgl) if usulan_status != "None" else "",

            "SURAT_PERSETUJUAN_STATUS": setuju_status,
            "SURAT_PERSETUJUAN_TANGGAL": iso_or_empty(setuju_tgl) if setuju_status != "None" else "",

            "SP2BJ_STATUS": sp2bj_status,
            "SP2BJ_TANGGAL": iso_or_empty(sp2bj_tgl) if sp2bj_status != "None" else "",

            "PO_STATUS": po_status,
            "PO_TANGGAL": iso_or_empty(po_tgl) if po_status != "None" else "",

            "TERBAYAR_STATUS": terbayar_status,
            "TERBAYAR_TANGGAL": iso_or_empty(terbayar_tgl) if terbayar_status != "None" else "",

            "SUPPLY_STATUS": supply_status,
            "SUPPLY_TANGGAL": iso_or_empty(supply_tgl) if supply_status != "None" else "",

            "LAST_UPDATE": datetime.now().strftime("%Y-%m-%d"),
        }

        # Safety: kalau status None, pastikan tanggal kosong
        for s_col, d_col in pairs:
            if patch.get(s_col) == "None":
                patch[d_col] = ""

        try:
            res2 = api_update_request(str(selected_rid), patch)

            if debug_mode:
                st.write("DEBUG update_request response:")
                st.json(res2)

            if res2.get("ok"):
                st.success("✅ Update tersimpan. Reload data...")
                st.rerun()
            else:
                st.error(f"Gagal: {res2.get('error')}")
        except Exception as e:
            st.error(f"Error simpan: {e}")
