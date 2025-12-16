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


def parse_date_value(x):
    """
    Terima:
      - '2025-12-15T10:00:00.000Z'
      - '2025-12-15'
      - '' / None / 'None' / False
    Return: date atau None
    """
    if x is None:
        return None
    if isinstance(x, bool):
        return None

    s = str(x).strip()
    if s == "" or s.lower() == "none" or s.lower() == "nan":
        return None

    # ambil YYYY-MM-DD dari ISO panjang
    s = s[:10]
    try:
        return date.fromisoformat(s)
    except Exception:
        return None


def iso_or_empty(d):
    return d.isoformat() if d else ""


def display_date_str(x):
    """Buat tampilan tabel jadi rapi: ambil 10 char pertama (YYYY-MM-DD) atau kosong."""
    if x is None:
        return ""
    s = str(x).strip()
    if s == "" or s.lower() in ["none", "false", "nan"]:
        return ""
    return s[:10]


def clean_status(x):
    """Normalisasi status jadi salah satu dari: None / In Process / Done."""
    s = str(x).strip() if x is not None else ""
    if s == "" or s.lower() in ["none", "nan", "false"]:
        return "None"
    if s.lower() in ["in process", "in_progress", "progress", "process"]:
        return "In Process"
    if s.lower() in ["done", "finish", "finished", "completed", "complete"]:
        return "Done"
    # fallback: kalau ada nilai aneh, tampilkan apa adanya tapi jangan bikin crash
    return s


def parse_files_any(*values):
    """
    Mencoba membaca daftar file dari beberapa kemungkinan kolom:
    - list of dicts
    - string JSON list/dict
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
    res = post_api({"action": "list_requests", "key": TEKNIK_KEY})
    if not res.get("ok"):
        raise RuntimeError(res.get("error", "API list_requests gagal"))

    rows = res.get("data") or res.get("rows") or []
    df = pd.DataFrame(rows)
    return df


def api_update_request(request_id: str, fields: dict) -> dict:
    return post_api({
        "action": "update_request",
        "key": TEKNIK_KEY,
        "request_id": request_id,
        "fields": fields
    })


def status_with_optional_date_ui(title: str, key_prefix: str, current_status: str, current_date_value):
    """
    UI standar: selectbox status (None/In Process/Done) + tanggal (muncul hanya kalau status != None)
    Return: (status_str, date_or_none)
    """
    st.markdown(f"**{title}**")

    status = st.selectbox(
        f"Status {title}",
        ["None", "In Process", "Done"],
        index=["None", "In Process", "Done"].index(clean_status(current_status)) if clean_status(current_status) in ["None", "In Process", "Done"] else 0,
        key=f"{key_prefix}_status",
    )

    if status == "None":
        st.caption("Tanggal: (kosong)")
        return status, None

    dt = parse_date_value(current_date_value) or date.today()
    dt = st.date_input(f"Tanggal {title}", value=dt, key=f"{key_prefix}_tgl")
    return status, dt


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

    # Normalisasi kolom -> UPPERCASE agar konsisten dengan nama kolom Sheet
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
    for c in expected_cols:
        if c not in df.columns:
            df[c] = ""

    # =========================
    # TABEL RINGKAS
    # =========================
    st.markdown("### Daftar Permintaan")

    show_df = df[[
        "REQUEST_ID", "TANGGAL_UPLOAD", "NO_SPBJ_KAPAL", "JUDUL_PERMINTAAN",
        "EVALUASI_STATUS", "EVALUASI_TANGGAL",
        "SURAT_USULAN_STATUS", "SURAT_USULAN_TANGGAL",
        "SURAT_PERSETUJUAN_STATUS", "SURAT_PERSETUJUAN_TANGGAL",
        "SP2BJ_STATUS", "SP2BJ_TANGGAL",
        "PO_STATUS", "PO_TANGGAL",
        "TERBAYAR_STATUS", "TERBAYAR_TANGGAL",
        "SUPPLY_STATUS", "SUPPLY_TANGGAL",
        "LAST_UPDATE"
    ]].copy()

    # rapikan tampilan tanggal/status
    for c in [
        "TANGGAL_UPLOAD", "EVALUASI_TANGGAL",
        "SURAT_USULAN_TANGGAL", "SURAT_PERSETUJUAN_TANGGAL",
        "SP2BJ_TANGGAL", "PO_TANGGAL", "TERBAYAR_TANGGAL",
        "SUPPLY_TANGGAL", "LAST_UPDATE"
    ]:
        show_df[c] = show_df[c].apply(display_date_str)

    for c in [
        "EVALUASI_STATUS",
        "SURAT_USULAN_STATUS", "SURAT_PERSETUJUAN_STATUS",
        "SP2BJ_STATUS", "PO_STATUS", "TERBAYAR_STATUS",
        "SUPPLY_STATUS"
    ]:
        show_df[c] = show_df[c].apply(clean_status)

    st.dataframe(show_df, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("### Update Progress (pilih 1 REQUEST_ID)")

    rid_list = df["REQUEST_ID"].astype(str).tolist()
    selected_rid = st.selectbox("REQUEST_ID", rid_list)

    row = df[df["REQUEST_ID"].astype(str) == str(selected_rid)].iloc[0].to_dict()

    # Ambil file lampiran (fallback kalau nyasar)
    files_list = parse_files_any(
        row.get("FILES"),
        row.get("FILES_JSON"),
        row.get("EVALUASI_STATUS"),  # kalau ternyata isinya JSON file dari data lama
    )

    # DETAIL INFO
    colA, colB = st.columns([1.2, 1])

    with colA:
        st.write("**Tanggal Upload:**", row.get("TANGGAL_UPLOAD", ""))
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

    # FORM UPDATE
    with colB:
        st.markdown("#### 1) Evaluasi Cabang")
        eval_status, eval_tgl = status_with_optional_date_ui(
            "Evaluasi",
            "eval",
            row.get("EVALUASI_STATUS", ""),
            row.get("EVALUASI_TANGGAL", ""),
        )

        st.markdown("#### 2) Surat Usulan ke Pusat")
        usulan_status, usulan_tgl = status_with_optional_date_ui(
            "Surat Usulan",
            "usulan",
            row.get("SURAT_USULAN_STATUS", ""),
            row.get("SURAT_USULAN_TANGGAL", ""),
        )

        st.markdown("#### 3) Surat Persetujuan Pusat")
        setuju_status, setuju_tgl = status_with_optional_date_ui(
            "Surat Persetujuan",
            "setuju",
            row.get("SURAT_PERSETUJUAN_STATUS", ""),
            row.get("SURAT_PERSETUJUAN_TANGGAL", ""),
        )

    st.markdown("#### 4) Administrasi Cabang (Status + Tanggal)")
    c1, c2, c3 = st.columns(3)

    with c1:
        sp2bj_status, sp2bj_tgl = status_with_optional_date_ui(
            "SP2BJ",
            "sp2bj",
            row.get("SP2BJ_STATUS", ""),
            row.get("SP2BJ_TANGGAL", ""),
        )

    with c2:
        po_status, po_tgl = status_with_optional_date_ui(
            "PO",
            "po",
            row.get("PO_STATUS", ""),
            row.get("PO_TANGGAL", ""),
        )

    with c3:
        terbayar_status, terbayar_tgl = status_with_optional_date_ui(
            "Terbayar",
            "terbayar",
            row.get("TERBAYAR_STATUS", ""),
            row.get("TERBAYAR_TANGGAL", ""),
        )

    st.markdown("#### 5) Supply Barang")
    supply_status, supply_tgl = status_with_optional_date_ui(
        "Supply",
        "supply",
        row.get("SUPPLY_STATUS", ""),
        row.get("SUPPLY_TANGGAL", ""),
    )

    st.markdown("---")
    if st.button("💾 Simpan Update"):
        patch = {
            # evaluasi
            "EVALUASI_STATUS": eval_status,
            "EVALUASI_TANGGAL": iso_or_empty(eval_tgl) if eval_status != "None" else "",

            # surat usulan + persetujuan
            "SURAT_USULAN_STATUS": usulan_status,
            "SURAT_USULAN_TANGGAL": iso_or_empty(usulan_tgl) if usulan_status != "None" else "",

            "SURAT_PERSETUJUAN_STATUS": setuju_status,
            "SURAT_PERSETUJUAN_TANGGAL": iso_or_empty(setuju_tgl) if setuju_status != "None" else "",

            # administrasi cabang
            "SP2BJ_STATUS": sp2bj_status,
            "SP2BJ_TANGGAL": iso_or_empty(sp2bj_tgl) if sp2bj_status != "None" else "",

            "PO_STATUS": po_status,
            "PO_TANGGAL": iso_or_empty(po_tgl) if po_status != "None" else "",

            "TERBAYAR_STATUS": terbayar_status,
            "TERBAYAR_TANGGAL": iso_or_empty(terbayar_tgl) if terbayar_status != "None" else "",

            # supply
            "SUPPLY_STATUS": supply_status,
            "SUPPLY_TANGGAL": iso_or_empty(supply_tgl) if supply_status != "None" else "",

            # last update
            "LAST_UPDATE": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        }

        try:
            res2 = api_update_request(str(selected_rid), patch)
            if res2.get("ok"):
                st.success("✅ Update tersimpan.")
                st.rerun()
            else:
                st.error(f"Gagal: {res2.get('error')}")
        except Exception as e:
            st.error(f"Error simpan: {e}")
