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
    st.markdown("### Daftar Permintaan")

    show_df = df[[
        "request_id", "tanggal_upload", "no_spbj_kapal", "judul_permintaan",
        "evaluasi_status", "surat_usulan_tanggal", "surat_persetujuan_tanggal",
        "sp2bj_check", "po_check", "terbayar_check",
        "supply_status", "last_update"
    ]].copy()

    # Rename untuk tampilan
    show_df = show_df.rename(columns={
        "request_id": "REQUEST_ID",
        "tanggal_upload": "TANGGAL_UPLOAD",
        "no_spbj_kapal": "NO_SPBJ_KAPAL",
        "judul_permintaan": "JUDUL_PERMINTAAN",
        "evaluasi_status": "EVALUASI_STATUS",
        "surat_usulan_tanggal": "SURAT_USULAN_TANGGAL",
        "surat_persetujuan_tanggal": "SURAT_PERSETUJUAN_TANGGAL",
        "sp2bj_check": "SP2BJ_CHECK",
        "po_check": "PO_CHECK",
        "terbayar_check": "TERBAYAR_CHECK",
        "supply_status": "SUPPLY_STATUS",
        "last_update": "LAST_UPDATE",
    })

    st.dataframe(show_df, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("### Update Progress (pilih 1 REQUEST_ID)")

    rid_list = df["request_id"].astype(str).tolist()
    selected_rid = st.selectbox("REQUEST_ID", rid_list)

    row = df[df["request_id"].astype(str) == str(selected_rid)].iloc[0].to_dict()

    # Ambil file lampiran (kadang filenya nyasar ke evaluasi_status dari data kamu)
    files_list = parse_files_any(
        row.get("files"),
        row.get("files_json"),
        row.get("FILES_JSON"),
        row.get("evaluasi_status")  # fallback kalau ternyata ini berisi JSON file
    )

    # DETAIL INFO
    colA, colB = st.columns([1.2, 1])

    with colA:
        st.write("**Tanggal Upload:**", row.get("tanggal_upload", ""))
        st.write("**No SPBJ Kapal:**", row.get("no_spbj_kapal", ""))
        st.write("**Judul:**", row.get("judul_permintaan", ""))

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
                    # kalau cuma ada fileId
                    fid = f.get("fileId") or f.get("id")
                    if fid:
                        st.markdown(f"- [{name}](https://drive.google.com/uc?export=download&id={fid})")
                    else:
                        st.markdown(f"- {name}")

    # INPUT FORM UPDATE
    with colB:
        st.markdown("#### 1) Evaluasi Cabang")
        eval_status_current = row.get("evaluasi_status") or "None"
        if eval_status_current not in ["None", "In Process", "Done"]:
            eval_status_current = "None"

        eval_status = st.selectbox(
            "Status Evaluasi",
            ["None", "In Process", "Done"],
            index=["None", "In Process", "Done"].index(eval_status_current)
        )

        eval_tgl = st.date_input(
            "Tanggal Evaluasi (isi saat selesai/ada progress)",
            value=parse_date_value(row.get("evaluasi_tanggal")) or date.today(),
            key="eval_tgl"
        )

        st.markdown("#### 2) Surat Usulan ke Pusat")
        usulan_tgl = st.date_input(
            "Tanggal Surat Usulan",
            value=parse_date_value(row.get("surat_usulan_tanggal")) or date.today(),
            key="usulan_tgl"
        )

        st.markdown("#### 3) Surat Persetujuan Pusat")
        setuju_tgl = st.date_input(
            "Tanggal Surat Persetujuan",
            value=parse_date_value(row.get("surat_persetujuan_tanggal")) or date.today(),
            key="setuju_tgl"
        )

    st.markdown("#### 4) Administrasi Cabang")
    c1, c2, c3 = st.columns(3)

    sp2bj_check = to_bool(row.get("sp2bj_check"))
    po_check = to_bool(row.get("po_check"))
    terbayar_check = to_bool(row.get("terbayar_check"))

    with c1:
        sp2bj_check_new = st.checkbox("SP2B/J", value=sp2bj_check)
        sp2bj_tgl = st.date_input(
            "Tanggal SP2B/J",
            value=parse_date_value(row.get("sp2bj_tanggal")) or date.today(),
            key="sp2bj_tgl"
        )
    with c2:
        po_check_new = st.checkbox("PO", value=po_check)
        po_tgl = st.date_input(
            "Tanggal PO",
            value=parse_date_value(row.get("po_tanggal")) or date.today(),
            key="po_tgl"
        )
    with c3:
        terbayar_check_new = st.checkbox("Terbayar", value=terbayar_check)
        terbayar_tgl = st.date_input(
            "Tanggal Terbayar",
            value=parse_date_value(row.get("terbayar_tanggal")) or date.today(),
            key="terbayar_tgl"
        )

    st.markdown("#### 5) Supply Barang")
    supply_status_current = row.get("supply_status") or "None"
    if supply_status_current not in ["None", "In Process", "Done"]:
        supply_status_current = "None"

    supply_status = st.selectbox(
        "Status Supply",
        ["None", "In Process", "Done"],
        index=["None", "In Process", "Done"].index(supply_status_current)
    )

    supply_tgl = st.date_input(
        "Tanggal Supply (isi saat selesai/ada progress)",
        value=parse_date_value(row.get("supply_tanggal")) or date.today(),
        key="supply_tgl"
    )

    st.markdown("---")
    if st.button("💾 Simpan Update"):
        fields = {
            "evaluasi_status": eval_status,
            "evaluasi_tanggal": iso_or_empty(eval_tgl),

            "surat_usulan_tanggal": iso_or_empty(usulan_tgl),
            "surat_persetujuan_tanggal": iso_or_empty(setuju_tgl),

            "sp2bj_check": bool(sp2bj_check_new),
            "sp2bj_tanggal": iso_or_empty(sp2bj_tgl) if sp2bj_check_new else "",

            "po_check": bool(po_check_new),
            "po_tanggal": iso_or_empty(po_tgl) if po_check_new else "",

            "terbayar_check": bool(terbayar_check_new),
            "terbayar_tanggal": iso_or_empty(terbayar_tgl) if terbayar_check_new else "",

            "supply_status": supply_status,
            "supply_tanggal": iso_or_empty(supply_tgl),
        }

        try:
            res2 = api_update_request(selected_rid, fields)
            if res2.get("ok"):
                st.success("✅ Update tersimpan.")
                st.rerun()
            else:
                st.error(f"Gagal: {res2.get('error')}")
        except Exception as e:
            st.error(f"Error simpan: {e}")
