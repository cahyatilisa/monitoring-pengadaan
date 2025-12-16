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
    """Normalisasi status ke: None / In Process / Done"""
    if x is None:
        return "None"
    s = str(x).strip()
    if s == "" or s.lower() in ["none", "null", "nan", "false", "0"]:
        return "None"
    s_low = s.lower()
    if s_low in ["in process", "inprogress", "process", "on progress", "progress"]:
        return "In Process"
    if s_low in ["done", "finish", "finished", "selesai", "complete", "completed", "ok", "yes", "true", "1"]:
        return "Done"
    # fallback: biar tidak liar
    if s in ["None", "In Process", "Done"]:
        return s
    return "None"


def parse_date_safe(s):
    """Terima 'YYYY-MM-DD' atau ISO panjang, balikin date atau None."""
    if not s:
        return None
    if isinstance(s, bool):
        return None
    s = str(s).strip()
    if s in ["None", "nan", "NaT", "False", "false"]:
        return None
    try:
        return date.fromisoformat(s[:10])
    except Exception:
        return None


def iso_or_empty(d: date | None) -> str:
    """Untuk disimpan ke backend: YYYY-MM-DD atau '' """
    return d.isoformat() if d else ""


def fmt_ddmmyyyy(x) -> str:
    """Untuk tampilan tabel/teks: dd-mm-yyyy"""
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

    # ===== sudah login =====
    try:
        df = api_list_requests()
    except Exception as e:
        st.error(f"Error ambil data: {e}")
        st.stop()

    if df.empty:
        st.info("Belum ada permintaan masuk.")
        st.stop()

    # Normalisasi nama kolom => UPPERCASE (biar konsisten dengan backend kamu)
    df.columns = [str(c).strip().upper() for c in df.columns]

    # Kolom yang kita butuhkan (kalau belum ada, buat)
    must_have = [
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
    for c in must_have:
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
        # kalau status None => tanggal jadi kosong (display & update logic)
        df.loc[df[s_col] == "None", d_col] = ""

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

    # format tanggal dd-mm-yyyy untuk tampilan
    for c in show_df.columns:
        if "TANGGAL" in c or c in ["TANGGAL_UPLOAD", "LAST_UPDATE"]:
            show_df[c] = show_df[c].apply(fmt_ddmmyyyy)

    st.dataframe(show_df, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("### Update Progress (pilih 1 REQUEST_ID)")

    rid_list = df["REQUEST_ID"].astype(str).tolist()
    selected_rid = st.selectbox("REQUEST_ID", rid_list)

    row = df[df["REQUEST_ID"].astype(str) == str(selected_rid)].iloc[0].to_dict()

    # Ambil file lampiran (fallback kalau ada yang nyasar)
    files_list = parse_files_any(
        row.get("FILES"),
        row.get("FILES_JSON"),
        row.get("EVALUASI_STATUS"),  # kadang datamu file nyasar di sini
    )

    colA, colB = st.columns([1.2, 1])

    # =========================
    # PANEL KIRI (INFO)
    # =========================
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

    # =========================
    # PANEL KANAN (FORM)
    # =========================
    with colB:
        status_opts = ["None", "In Process", "Done"]

        # 1) Evaluasi Cabang
        st.markdown("#### 1) Evaluasi Cabang")
        eval_status = st.selectbox(
            "Status Evaluasi",
            status_opts,
            index=status_opts.index(clean_status(row.get("EVALUASI_STATUS"))),
            key="eval_status",
        )
        if eval_status == "None":
            eval_tgl = None
            st.caption("Tanggal Evaluasi: (kosong)")
        else:
            eval_tgl = st.date_input(
                "Tanggal Evaluasi",
                value=parse_date_safe(row.get("EVALUASI_TANGGAL")) or date.today(),
                key="eval_tgl",
            )

        # 2) Surat Usulan ke Pusat
        st.markdown("#### 2) Surat Usulan ke Pusat")
        usulan_status = st.selectbox(
            "Status Surat Usulan",
            status_opts,
            index=status_opts.index(clean_status(row.get("SURAT_USULAN_STATUS"))),
            key="usulan_status",
        )
        if usulan_status == "None":
            usulan_tgl = None
            st.caption("Tanggal Surat Usulan: (kosong)")
        else:
            usulan_tgl = st.date_input(
                "Tanggal Surat Usulan",
                value=parse_date_safe(row.get("SURAT_USULAN_TANGGAL")) or date.today(),
                key="usulan_tgl",
            )

        # 3) Surat Persetujuan Pusat
        st.markdown("#### 3) Surat Persetujuan Pusat")
        setuju_status = st.selectbox(
            "Status Surat Persetujuan",
            status_opts,
            index=status_opts.index(clean_status(row.get("SURAT_PERSETUJUAN_STATUS"))),
            key="setuju_status",
        )
        if setuju_status == "None":
            setuju_tgl = None
            st.caption("Tanggal Surat Persetujuan: (kosong)")
        else:
            setuju_tgl = st.date_input(
                "Tanggal Surat Persetujuan",
                value=parse_date_safe(row.get("SURAT_PERSETUJUAN_TANGGAL")) or date.today(),
                key="setuju_tgl",
            )

    # 4) Administrasi Cabang (3 kolom)
    st.markdown("#### 4) Administrasi Cabang")
    c1, c2, c3 = st.columns(3)
    status_opts = ["None", "In Process", "Done"]

    with c1:
        st.markdown("**SP2B/J**")
        sp2bj_status = st.selectbox(
            "Status SP2B/J",
            status_opts,
            index=status_opts.index(clean_status(row.get("SP2BJ_STATUS"))),
            key="sp2bj_status",
        )
        if sp2bj_status == "None":
            sp2bj_tgl = None
            st.caption("Tanggal SP2B/J: (kosong)")
        else:
            sp2bj_tgl = st.date_input(
                "Tanggal SP2B/J",
                value=parse_date_safe(row.get("SP2BJ_TANGGAL")) or date.today(),
                key="sp2bj_tgl",
            )

    with c2:
        st.markdown("**PO**")
        po_status = st.selectbox(
            "Status PO",
            status_opts,
            index=status_opts.index(clean_status(row.get("PO_STATUS"))),
            key="po_status",
        )
        if po_status == "None":
            po_tgl = None
            st.caption("Tanggal PO: (kosong)")
        else:
            po_tgl = st.date_input(
                "Tanggal PO",
                value=parse_date_safe(row.get("PO_TANGGAL")) or date.today(),
                key="po_tgl",
            )

    with c3:
        st.markdown("**Terbayar**")
        terbayar_status = st.selectbox(
            "Status Terbayar",
            status_opts,
            index=status_opts.index(clean_status(row.get("TERBAYAR_STATUS"))),
            key="terbayar_status",
        )
        if terbayar_status == "None":
            terbayar_tgl = None
            st.caption("Tanggal Terbayar: (kosong)")
        else:
            terbayar_tgl = st.date_input(
                "Tanggal Terbayar",
                value=parse_date_safe(row.get("TERBAYAR_TANGGAL")) or date.today(),
                key="terbayar_tgl",
            )

    # 5) Supply Barang
    st.markdown("#### 5) Supply Barang")
    supply_status = st.selectbox(
        "Status Supply",
        status_opts,
        index=status_opts.index(clean_status(row.get("SUPPLY_STATUS"))),
        key="supply_status",
    )
    if supply_status == "None":
        supply_tgl = None
        st.caption("Tanggal Supply: (kosong)")
    else:
        supply_tgl = st.date_input(
            "Tanggal Supply",
            value=parse_date_safe(row.get("SUPPLY_TANGGAL")) or date.today(),
            key="supply_tgl",
        )

    st.markdown("---")

    if st.button("💾 Simpan Update"):
        # final rule: kalau status None => tanggal pasti kosong
        patch = {
            "EVALUASI_STATUS": clean_status(eval_status),
            "EVALUASI_TANGGAL": iso_or_empty(eval_tgl) if clean_status(eval_status) != "None" else "",

            "SURAT_USULAN_STATUS": clean_status(usulan_status),
            "SURAT_USULAN_TANGGAL": iso_or_empty(usulan_tgl) if clean_status(usulan_status) != "None" else "",

            "SURAT_PERSETUJUAN_STATUS": clean_status(setuju_status),
            "SURAT_PERSETUJUAN_TANGGAL": iso_or_empty(setuju_tgl) if clean_status(setuju_status) != "None" else "",

            "SP2BJ_STATUS": clean_status(sp2bj_status),
            "SP2BJ_TANGGAL": iso_or_empty(sp2bj_tgl) if clean_status(sp2bj_status) != "None" else "",

            "PO_STATUS": clean_status(po_status),
            "PO_TANGGAL": iso_or_empty(po_tgl) if clean_status(po_status) != "None" else "",

            "TERBAYAR_STATUS": clean_status(terbayar_status),
            "TERBAYAR_TANGGAL": iso_or_empty(terbayar_tgl) if clean_status(terbayar_status) != "None" else "",

            "SUPPLY_STATUS": clean_status(supply_status),
            "SUPPLY_TANGGAL": iso_or_empty(supply_tgl) if clean_status(supply_status) != "None" else "",
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
