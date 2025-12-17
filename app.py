import base64
import json
from datetime import date, datetime
from typing import Optional, Any, Dict, List

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


def api_list_requests() -> pd.DataFrame:
    # backend kamu biasanya balikin res["data"] (kadang "rows")
    res = post_api({"action": "list_requests", "key": TEKNIK_KEY})
    if not res.get("ok"):
        raise RuntimeError(res.get("error", "API list_requests gagal"))
    rows = res.get("data") or res.get("rows") or []
    return pd.DataFrame(rows)


def api_update_request(request_id: str, fields: dict) -> dict:
    # konsisten: pakai key + fields
    return post_api(
        {
            "action": "update_request",
            "key": TEKNIK_KEY,
            "request_id": request_id,
            "fields": fields,
        }
    )


# =========================
# DATA / FORMAT HELPERS
# =========================
def clean_status(x: Any) -> str:
    """Normalisasi status -> 'None' / 'In Process' / 'Done'."""
    if x is None:
        return "None"
    s = str(x).strip()
    if s == "" or s.lower() in ["none", "nan", "nat", "null", "false", "0"]:
        return "None"
    s_low = s.lower()
    if s_low in ["done", "selesai", "complete", "completed", "finish", "finished", "ok", "ya", "yes", "true", "1"]:
        return "Done"
    if s_low in ["in process", "in_progress", "progress", "proses", "on progress", "ongoing", "jalan"]:
        return "In Process"
    # fallback: kalau user isi sesuatu, anggap In Process
    return "In Process"


def parse_date_value(x: Any) -> Optional[date]:
    """
    Terima:
    - '2025-12-15T10:00:00.000Z'
    - '2025-12-15'
    - '' / None / 'None'
    Return date atau None
    """
    if x is None:
        return None
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return None

    s = str(x).strip()
    if s == "" or s.lower() in ["none", "nan", "nat", "null", "false"]:
        return None

    # buang jam (ISO)
    if "T" in s:
        s = s.split("T")[0]
    try:
        return date.fromisoformat(s[:10])
    except Exception:
        return None


def iso_or_empty(d: Optional[date]) -> str:
    return d.isoformat() if d else ""


def fmt_ddmmyyyy(x: Any) -> str:
    d = parse_date_value(x)
    return d.strftime("%d-%m-%Y") if d else ""


def parse_files_any(*values) -> List[dict]:
    """
    Mencoba membaca daftar file dari beberapa kemungkinan kolom:
    - list of dict
    - string JSON list
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


def status_date_widget(
    label: str,
    status_raw: Any,
    tanggal_raw: Any,
    key_prefix: str,
) -> tuple[str, Optional[date]]:
    """
    UI: status dropdown + tanggal optional.
    Aturan:
    - jika status == 'None' => tanggal None (kosong)
    - jika status != 'None' => user boleh isi tanggal atau kosongkan via checkbox
    """
    status = clean_status(status_raw)
    tanggal_val = parse_date_value(tanggal_raw)

    status = st.selectbox(
        f"Status {label}",
        ["None", "In Process", "Done"],
        index=["None", "In Process", "Done"].index(status),
        key=f"{key_prefix}_status",
    )

    if status == "None":
        st.caption(f"Tanggal {label}: (kosong)")
        return status, None

    # status bukan None -> boleh pilih tanggal / boleh dikosongkan
    set_tanggal_default = True if tanggal_val else False
    set_tanggal = st.checkbox(
        f"Isi Tanggal {label}",
        value=set_tanggal_default,
        key=f"{key_prefix}_set_tgl",
    )

    if not set_tanggal:
        st.caption(f"Tanggal {label}: (kosong)")
        return status, None

    tgl = st.date_input(
        f"Tanggal {label}",
        value=tanggal_val or date.today(),
        key=f"{key_prefix}_tgl",
    )
    return status, tgl


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
            type=None,
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
            files_payload.append(
                {
                    "name": f.name,
                    "mime": f.type or "application/octet-stream",
                    "b64": base64.b64encode(content).decode("utf-8"),
                }
            )

        try:
            res = post_api(
                {
                    "action": "submit_request",
                    "tanggal_upload": tanggal_upload.isoformat(),
                    "no_spbj_kapal": no_spbj.strip(),
                    "judul_permintaan": judul.strip(),
                    "files": files_payload,
                }
            )
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

    # Pakai UPPERCASE biar konsisten (hindari mismatch kolom)
    df.columns = [str(c).strip().upper() for c in df.columns]

    # Pastikan kolom penting ada (kalau belum ada -> buat)
    expected_cols = [
        "REQUEST_ID",
        "TANGGAL_UPLOAD",
        "NO_SPBJ_KAPAL",
        "JUDUL_PERMINTAAN",
        "FILES",
        "FILES_JSON",
        "EVALUASI_STATUS",
        "EVALUASI_TANGGAL",
        "SURAT_USULAN_STATUS",
        "SURAT_USULAN_TANGGAL",
        "SURAT_PERSETUJUAN_STATUS",
        "SURAT_PERSETUJUAN_TANGGAL",
        "SP2BJ_STATUS",
        "SP2BJ_TANGGAL",
        "PO_STATUS",
        "PO_TANGGAL",
        "TERBAYAR_STATUS",
        "TERBAYAR_TANGGAL",
        "SUPPLY_STATUS",
        "SUPPLY_TANGGAL",
        "LAST_UPDATE",
    ]
    for c in expected_cols:
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
    # TABEL (HANYA SATU) + FORMAT TANGGAL DD-MM-YYYY
    # =========================
    st.markdown("### Daftar Permintaan")

    show_cols = [
        "REQUEST_ID",
        "TANGGAL_UPLOAD",
        "NO_SPBJ_KAPAL",
        "JUDUL_PERMINTAAN",
        "EVALUASI_STATUS",
        "EVALUASI_TANGGAL",
        "SURAT_USULAN_STATUS",
        "SURAT_USULAN_TANGGAL",
        "SURAT_PERSETUJUAN_STATUS",
        "SURAT_PERSETUJUAN_TANGGAL",
        "SP2BJ_STATUS",
        "SP2BJ_TANGGAL",
        "PO_STATUS",
        "PO_TANGGAL",
        "TERBAYAR_STATUS",
        "TERBAYAR_TANGGAL",
        "SUPPLY_STATUS",
        "SUPPLY_TANGGAL",
        "LAST_UPDATE",
    ]
    show_df = df[show_cols].copy()

    # format semua kolom tanggal menjadi dd-mm-yyyy
    date_cols = [c for c in show_df.columns if c.endswith("_TANGGAL") or c == "TANGGAL_UPLOAD" or c == "LAST_UPDATE"]
    for c in date_cols:
        show_df[c] = show_df[c].apply(fmt_ddmmyyyy)

    st.dataframe(show_df, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("### Update Progress (pilih 1 REQUEST_ID)")

    rid_list = df["REQUEST_ID"].astype(str).tolist()
    selected_rid = st.selectbox("REQUEST_ID", rid_list, key="rid_select")

    row = df[df["REQUEST_ID"].astype(str) == str(selected_rid)].iloc[0].to_dict()

    # Lampiran file: ambil dari beberapa kemungkinan
    files_list = parse_files_any(
        row.get("FILES"),
        row.get("FILES_JSON"),
        row.get("EVALUASI_STATUS"),  # fallback kalau pernah nyasar
    )

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

    # FORM INPUTS (HEADING SERAGAM = '###')
    with colB:
        st.markdown("### 1) Evaluasi Cabang")
        evaluasi_status, evaluasi_tgl = status_date_widget(
            "Evaluasi",
            row.get("EVALUASI_STATUS"),
            row.get("EVALUASI_TANGGAL"),
            key_prefix="evaluasi",
        )

        st.markdown("### 2) Surat Usulan ke Pusat")
        surat_usulan_status, surat_usulan_tgl = status_date_widget(
            "Surat Usulan",
            row.get("SURAT_USULAN_STATUS"),
            row.get("SURAT_USULAN_TANGGAL"),
            key_prefix="surat_usulan",
        )

        st.markdown("### 3) Surat Persetujuan Pusat")
        surat_setuju_status, surat_setuju_tgl = status_date_widget(
            "Surat Persetujuan",
            row.get("SURAT_PERSETUJUAN_STATUS"),
            row.get("SURAT_PERSETUJUAN_TANGGAL"),
            key_prefix="surat_setuju",
        )

        st.markdown("### 4) SP2BJ")
        sp2bj_status, sp2bj_tgl = status_date_widget(
            "SP2BJ",
            row.get("SP2BJ_STATUS"),
            row.get("SP2BJ_TANGGAL"),
            key_prefix="sp2bj",
        )

        st.markdown("### 5) PO")
        po_status, po_tgl = status_date_widget(
            "PO",
            row.get("PO_STATUS"),
            row.get("PO_TANGGAL"),
            key_prefix="po",
        )

        st.markdown("### 6) Terbayar")
        terbayar_status, terbayar_tgl = status_date_widget(
            "Terbayar",
            row.get("TERBAYAR_STATUS"),
            row.get("TERBAYAR_TANGGAL"),
            key_prefix="terbayar",
        )

        st.markdown("### 7) Supply Barang")
        supply_status, supply_tgl = status_date_widget(
            "Supply",
            row.get("SUPPLY_STATUS"),
            row.get("SUPPLY_TANGGAL"),
            key_prefix="supply",
        )

    st.markdown("---")

    if st.button("💾 Simpan Update", key="btn_save"):
        # aturan: kalau status None => tanggal kosong
        patch = {
            "EVALUASI_STATUS": evaluasi_status,
            "EVALUASI_TANGGAL": iso_or_empty(evaluasi_tgl) if evaluasi_status != "None" else "",

            "SURAT_USULAN_STATUS": surat_usulan_status,
            "SURAT_USULAN_TANGGAL": iso_or_empty(surat_usulan_tgl) if surat_usulan_status != "None" else "",

            "SURAT_PERSETUJUAN_STATUS": surat_setuju_status,
            "SURAT_PERSETUJUAN_TANGGAL": iso_or_empty(surat_setuju_tgl) if surat_setuju_status != "None" else "",

            "SP2BJ_STATUS": sp2bj_status,
            "SP2BJ_TANGGAL": iso_or_empty(sp2bj_tgl) if sp2bj_status != "None" else "",

            "PO_STATUS": po_status,
            "PO_TANGGAL": iso_or_empty(po_tgl) if po_status != "None" else "",

            "TERBAYAR_STATUS": terbayar_status,
            "TERBAYAR_TANGGAL": iso_or_empty(terbayar_tgl) if terbayar_status != "None" else "",

            "SUPPLY_STATUS": supply_status,
            "SUPPLY_TANGGAL": iso_or_empty(supply_tgl) if supply_status != "None" else "",

            # optional: kalau backend punya kolom ini
            "LAST_UPDATE": datetime.now().isoformat(timespec="seconds"),
        }

        try:
            res2 = api_update_request(selected_rid, patch)
            if res2.get("ok"):
                st.success("✅ Update tersimpan.")
                st.rerun()
            else:
                st.error(f"Gagal: {res2.get('error')}")
        except Exception as e:
            st.error(f"Error simpan: {e}")
