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
        return x.strip().lower() in ["true", "yes", "y", "1", "checked", "ok", "done"]
    return False


def parse_date_safe(x):
    """
    Terima: '2025-12-15T10:00:00.000Z' / '2025-12-15' / '' / 'None' / False
    Return: date atau None
    """
    if x is None:
        return None
    if isinstance(x, (bool, int, float)):
        return None

    s = str(x).strip()
    if s == "" or s.lower() in ["none", "nan", "nat", "false"]:
        return None

    s = s[:10]
    try:
        return date.fromisoformat(s)
    except Exception:
        return None


def iso_or_empty(d: date | None) -> str:
    return d.isoformat() if d else ""


def normalize_status(x):
    s = ("" if x is None else str(x)).strip()
    if s.lower() in ["", "none", "null", "nan"]:
        return "None"
    if s.lower() in ["in process", "in_progress", "progress", "process"]:
        return "In Process"
    if s.lower() in ["done", "finish", "completed", "complete"]:
        return "Done"
    # kalau ada nilai lain, paksa none biar aman
    return "None"


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

    # NORMALISASI: kolom jadi lower-case
    df.columns = [str(c).strip().lower() for c in df.columns]
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

    # pastikan kolom-kolom ada (lower-case)
    must_have = [
        "request_id", "tanggal_upload", "no_spbj_kapal", "judul_permintaan",
        "files", "files_json",

        "evaluasi_status", "evaluasi_tanggal",
        "surat_usulan_tanggal", "surat_persetujuan_tanggal",

        # status baru (seperti supply)
        "sp2bj_status", "sp2bj_tanggal",
        "po_status", "po_tanggal",
        "terbayar_status", "terbayar_tanggal",

        "supply_status", "supply_tanggal",
        "last_update",

        # tetap jaga kompatibilitas jika backend masih punya *_check
        "sp2bj_check", "po_check", "terbayar_check",
    ]
    for c in must_have:
        if c not in df.columns:
            df[c] = ""

    # =========================
    # TABEL RINGKAS (SATU SAJA)
    # =========================
    st.markdown("### Daftar Permintaan")

    show_df = df[[
        "request_id", "tanggal_upload", "no_spbj_kapal", "judul_permintaan",

        "evaluasi_status", "evaluasi_tanggal",
        "surat_usulan_tanggal", "surat_persetujuan_tanggal",

        "sp2bj_status", "sp2bj_tanggal",
        "po_status", "po_tanggal",
        "terbayar_status", "terbayar_tanggal",

        "supply_status", "supply_tanggal",
        "last_update"
    ]].copy()

    # rapihin status
    for c in ["evaluasi_status", "sp2bj_status", "po_status", "terbayar_status", "supply_status"]:
        show_df[c] = show_df[c].apply(normalize_status)

    # rename untuk tampilan
    show_df = show_df.rename(columns={
        "request_id": "REQUEST_ID",
        "tanggal_upload": "TANGGAL_UPLOAD",
        "no_spbj_kapal": "NO_SPBJ_KAPAL",
        "judul_permintaan": "JUDUL_PERMINTAAN",

        "evaluasi_status": "EVALUASI_STATUS",
        "evaluasi_tanggal": "EVALUASI_TANGGAL",
        "surat_usulan_tanggal": "SURAT_USULAN_TANGGAL",
        "surat_persetujuan_tanggal": "SURAT_PERSETUJUAN_TANGGAL",

        "sp2bj_status": "SP2BJ_STATUS",
        "sp2bj_tanggal": "SP2BJ_TANGGAL",
        "po_status": "PO_STATUS",
        "po_tanggal": "PO_TANGGAL",
        "terbayar_status": "TERBAYAR_STATUS",
        "terbayar_tanggal": "TERBAYAR_TANGGAL",

        "supply_status": "SUPPLY_STATUS",
        "supply_tanggal": "SUPPLY_TANGGAL",
        "last_update": "LAST_UPDATE",
    })

    st.dataframe(show_df, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("### Update Progress (pilih 1 REQUEST_ID)")

    rid_list = df["request_id"].astype(str).tolist()
    selected_rid = st.selectbox("REQUEST_ID", rid_list)

    row = df[df["request_id"].astype(str) == str(selected_rid)].iloc[0].to_dict()

    # file lampiran
    files_list = parse_files_any(
        row.get("files"),
        row.get("files_json"),
        row.get("evaluasi_status")  # fallback kalau ternyata evaluasi_status berisi JSON file
    )

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
                    fid = f.get("fileId") or f.get("id")
                    if fid:
                        st.markdown(f"- [{name}](https://drive.google.com/uc?export=download&id={fid})")
                    else:
                        st.markdown(f"- {name}")

    with colB:
        # ---------- 1) Evaluasi ----------
        st.markdown("#### 1) Evaluasi Cabang")
        eval_status_now = normalize_status(row.get("evaluasi_status"))
        eval_status = st.selectbox(
            "Status Evaluasi",
            ["None", "In Process", "Done"],
            index=["None", "In Process", "Done"].index(eval_status_now),
            key="eval_status",
        )

        eval_tgl_val = parse_date_safe(row.get("evaluasi_tanggal"))
        if eval_status == "None":
            eval_tgl = None
            st.caption("Tanggal Evaluasi: (kosong)")
        else:
            eval_tgl = st.date_input(
                "Tanggal Evaluasi (isi saat ada progress)",
                value=eval_tgl_val or date.today(),
                key="eval_tgl",
            )

        # ---------- 2) Surat Usulan ----------
        st.markdown("#### 2) Surat Usulan ke Pusat")
        usulan_tgl_val = parse_date_safe(row.get("surat_usulan_tanggal"))
        usulan_active = st.checkbox("Aktifkan Surat Usulan", value=bool(usulan_tgl_val), key="usulan_active")
        if usulan_active:
            usulan_tgl = st.date_input("Tanggal Surat Usulan", value=usulan_tgl_val or date.today(), key="usulan_tgl")
        else:
            usulan_tgl = None
            st.caption("Tanggal Surat Usulan: (kosong)")

        # ---------- 3) Surat Persetujuan ----------
        st.markdown("#### 3) Surat Persetujuan Pusat")
        setuju_tgl_val = parse_date_safe(row.get("surat_persetujuan_tanggal"))
        setuju_active = st.checkbox("Aktifkan Surat Persetujuan", value=bool(setuju_tgl_val), key="setuju_active")
        if setuju_active:
            setuju_tgl = st.date_input("Tanggal Surat Persetujuan", value=setuju_tgl_val or date.today(), key="setuju_tgl")
        else:
            setuju_tgl = None
            st.caption("Tanggal Surat Persetujuan: (kosong)")

    # ---------- 4) Administrasi Cabang (STATUS + TANGGAL) ----------
    st.markdown("#### 4) Administrasi Cabang")

    a1, a2, a3 = st.columns(3)

    # SP2BJ
    with a1:
        st.markdown("**SP2B/J**")
        sp2bj_status_now = normalize_status(row.get("sp2bj_status"))
        sp2bj_status = st.selectbox(
            "Status SP2B/J",
            ["None", "In Process", "Done"],
            index=["None", "In Process", "Done"].index(sp2bj_status_now),
            key="sp2bj_status",
        )
        sp2bj_tgl_val = parse_date_safe(row.get("sp2bj_tanggal"))
        if sp2bj_status == "None":
            sp2bj_tgl = None
            st.caption("Tanggal SP2B/J: (kosong)")
        else:
            sp2bj_tgl = st.date_input("Tanggal SP2B/J", value=sp2bj_tgl_val or date.today(), key="sp2bj_tgl")

    # PO
    with a2:
        st.markdown("**PO**")
        po_status_now = normalize_status(row.get("po_status"))
        po_status = st.selectbox(
            "Status PO",
            ["None", "In Process", "Done"],
            index=["None", "In Process", "Done"].index(po_status_now),
            key="po_status",
        )
        po_tgl_val = parse_date_safe(row.get("po_tanggal"))
        if po_status == "None":
            po_tgl = None
            st.caption("Tanggal PO: (kosong)")
        else:
            po_tgl = st.date_input("Tanggal PO", value=po_tgl_val or date.today(), key="po_tgl")

    # Terbayar
    with a3:
        st.markdown("**Terbayar**")
        terbayar_status_now = normalize_status(row.get("terbayar_status"))
        terbayar_status = st.selectbox(
            "Status Terbayar",
            ["None", "In Process", "Done"],
            index=["None", "In Process", "Done"].index(terbayar_status_now),
            key="terbayar_status",
        )
        terbayar_tgl_val = parse_date_safe(row.get("terbayar_tanggal"))
        if terbayar_status == "None":
            terbayar_tgl = None
            st.caption("Tanggal Terbayar: (kosong)")
        else:
            terbayar_tgl = st.date_input("Tanggal Terbayar", value=terbayar_tgl_val or date.today(), key="terbayar_tgl")

    # ---------- 5) Supply ----------
    st.markdown("#### 5) Supply Barang")
    supply_status_now = normalize_status(row.get("supply_status"))
    supply_status = st.selectbox(
        "Status Supply",
        ["None", "In Process", "Done"],
        index=["None", "In Process", "Done"].index(supply_status_now),
        key="supply_status",
    )

    supply_tgl_val = parse_date_safe(row.get("supply_tanggal"))
    if supply_status == "None":
        supply_tgl = None
        st.caption("Tanggal Supply: (kosong)")
    else:
        supply_tgl = st.date_input(
            "Tanggal Supply (isi saat ada progress)",
            value=supply_tgl_val or date.today(),
            key="supply_tgl",
        )

    st.markdown("---")

    if st.button("💾 Simpan Update"):
        # kompatibilitas: check = True kalau status Done
        sp2bj_check = (sp2bj_status == "Done")
        po_check = (po_status == "Done")
        terbayar_check = (terbayar_status == "Done")

        patch = {
            "evaluasi_status": eval_status,
            "evaluasi_tanggal": iso_or_empty(eval_tgl),

            "surat_usulan_tanggal": iso_or_empty(usulan_tgl),
            "surat_persetujuan_tanggal": iso_or_empty(setuju_tgl),

            # status baru
            "sp2bj_status": sp2bj_status,
            "sp2bj_tanggal": iso_or_empty(sp2bj_tgl),

            "po_status": po_status,
            "po_tanggal": iso_or_empty(po_tgl),

            "terbayar_status": terbayar_status,
            "terbayar_tanggal": iso_or_empty(terbayar_tgl),

            "supply_status": supply_status,
            "supply_tanggal": iso_or_empty(supply_tgl),

            # tetap kirim check juga (opsional tapi aman)
            "sp2bj_check": bool(sp2bj_check),
            "po_check": bool(po_check),
            "terbayar_check": bool(terbayar_check),

            "last_update": datetime.now().isoformat(timespec="seconds"),
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
