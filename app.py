import base64
import json
from datetime import date, datetime, timezone

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
# API
# =========================
def post_api(payload: dict) -> dict:
    r = requests.post(WEBAPP_URL, json=payload, timeout=60)
    r.raise_for_status()
    return r.json()


def api_list_requests() -> pd.DataFrame:
    res = post_api({"action": "list_requests", "key": TEKNIK_KEY})
    if not res.get("ok"):
        raise RuntimeError(res.get("error", "API list_requests gagal"))

    rows = res.get("data") or res.get("rows") or []
    df = pd.DataFrame(rows)
    return df


def api_update_request(request_id: str, fields: dict) -> dict:
    """
    Ada backend yang pakai "fields", ada yang pakai "patch".
    Kita coba "fields" dulu, kalau gagal baru coba "patch".
    """
    payload_fields = {
        "action": "update_request",
        "key": TEKNIK_KEY,
        "request_id": request_id,
        "fields": fields,
    }
    res = post_api(payload_fields)
    if res.get("ok"):
        return res

    # fallback: beberapa versi backend pakai "patch"
    payload_patch = {
        "action": "update_request",
        "key": TEKNIK_KEY,
        "request_id": request_id,
        "patch": fields,
    }
    return post_api(payload_patch)


# =========================
# HELPERS
# =========================
def parse_date_safe(x):
    """
    Terima: '2025-12-15T10:00:00.000Z' / '2025-12-15' / '' / None / False
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

    # ISO datetime panjang -> ambil YYYY-MM-DD
    if "T" in s:
        s = s.split("T")[0]

    try:
        return date.fromisoformat(s[:10])
    except Exception:
        return None


def iso_or_empty(d: date | None) -> str:
    return d.isoformat() if d else ""


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_files_any(*values):
    """
    Mencoba membaca daftar file dari beberapa kemungkinan kolom:
    - list of dicts
    - string JSON list/dict
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


def normalize_cols_upper(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().upper() for c in df.columns]
    return df


def ensure_cols(df: pd.DataFrame, cols: list[str], default=""):
    for c in cols:
        if c not in df.columns:
            df[c] = default
    return df


def clean_date_cell_for_table(x):
    """
    Untuk tampilan tabel: kalau bool/None/"None" => kosong.
    """
    if x is None:
        return ""
    if isinstance(x, bool):
        return ""
    s = str(x).strip()
    if s == "" or s.lower() == "none":
        return ""
    return s


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

    df = normalize_cols_upper(df)

    # kolom yang kita gunakan (akan dibuat kalau belum ada)
    required_cols = [
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
    df = ensure_cols(df, required_cols, default="")

    # Default status kalau kosong
    for col in [
        "EVALUASI_STATUS",
        "SURAT_USULAN_STATUS", "SURAT_PERSETUJUAN_STATUS",
        "SP2BJ_STATUS", "PO_STATUS", "TERBAYAR_STATUS",
        "SUPPLY_STATUS",
    ]:
        df[col] = df[col].apply(lambda x: x if str(x).strip() in STATUS_OPTIONS else ("None" if str(x).strip() == "" else x))

    # =========================
    # TABEL RINGKAS (SATU KALI)
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
        "LAST_UPDATE",
    ]].copy()

    # rapihin tampilan tanggal (hindari False / None tampil)
    date_cols = [
        "TANGGAL_UPLOAD",
        "EVALUASI_TANGGAL",
        "SURAT_USULAN_TANGGAL", "SURAT_PERSETUJUAN_TANGGAL",
        "SP2BJ_TANGGAL", "PO_TANGGAL", "TERBAYAR_TANGGAL",
        "SUPPLY_TANGGAL",
        "LAST_UPDATE",
    ]
    for c in date_cols:
        show_df[c] = show_df[c].apply(clean_date_cell_for_table)

    st.dataframe(show_df, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("### Update Progress (pilih 1 REQUEST_ID)")

    rid_list = df["REQUEST_ID"].astype(str).tolist()
    selected_rid = st.selectbox("REQUEST_ID", rid_list)

    row = df[df["REQUEST_ID"].astype(str) == str(selected_rid)].iloc[0].to_dict()

    # file lampiran: coba ambil dari beberapa tempat
    files_list = parse_files_any(
        row.get("FILES"),
        row.get("FILES_JSON"),
        row.get("EVALUASI_STATUS"),  # fallback kalau file nyasar ke kolom ini
    )

    # =========================
    # DETAIL & FORM
    # =========================
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

    with colB:
        # 1) Evaluasi
        st.markdown("#### 1) Evaluasi Cabang")
        eval_status = st.selectbox(
            "Status Evaluasi",
            STATUS_OPTIONS,
            index=STATUS_OPTIONS.index(row.get("EVALUASI_STATUS") or "None") if (row.get("EVALUASI_STATUS") or "None") in STATUS_OPTIONS else 0,
            key="eval_status",
        )

        eval_tgl_val = parse_date_safe(row.get("EVALUASI_TANGGAL"))
        if eval_status == "None":
            eval_tgl = None
            st.caption("Tanggal Evaluasi: (kosong)")
        else:
            eval_tgl = st.date_input(
                "Tanggal Evaluasi",
                value=eval_tgl_val or date.today(),
                key="eval_tgl",
            )

        # 2) Surat Usulan
        st.markdown("#### 2) Surat Usulan ke Pusat")
        usulan_status = st.selectbox(
            "Status Surat Usulan",
            STATUS_OPTIONS,
            index=STATUS_OPTIONS.index(row.get("SURAT_USULAN_STATUS") or "None") if (row.get("SURAT_USULAN_STATUS") or "None") in STATUS_OPTIONS else 0,
            key="usulan_status",
        )
        usulan_tgl_val = parse_date_safe(row.get("SURAT_USULAN_TANGGAL"))
        if usulan_status == "None":
            usulan_tgl = None
            st.caption("Tanggal Surat Usulan: (kosong)")
        else:
            usulan_tgl = st.date_input(
                "Tanggal Surat Usulan",
                value=usulan_tgl_val or date.today(),
                key="usulan_tgl",
            )

        # 3) Surat Persetujuan
        st.markdown("#### 3) Surat Persetujuan Pusat")
        setuju_status = st.selectbox(
            "Status Surat Persetujuan",
            STATUS_OPTIONS,
            index=STATUS_OPTIONS.index(row.get("SURAT_PERSETUJUAN_STATUS") or "None") if (row.get("SURAT_PERSETUJUAN_STATUS") or "None") in STATUS_OPTIONS else 0,
            key="setuju_status",
        )
        setuju_tgl_val = parse_date_safe(row.get("SURAT_PERSETUJUAN_TANGGAL"))
        if setuju_status == "None":
            setuju_tgl = None
            st.caption("Tanggal Surat Persetujuan: (kosong)")
        else:
            setuju_tgl = st.date_input(
                "Tanggal Surat Persetujuan",
                value=setuju_tgl_val or date.today(),
                key="setuju_tgl",
            )

    # 4) Administrasi Cabang -> ubah jadi STATUS + TANGGAL (seperti supply)
    st.markdown("#### 4) Administrasi Cabang")
    c1, c2, c3 = st.columns(3)

    # SP2BJ
    with c1:
        st.markdown("**SP2B/J**")
        sp2bj_status = st.selectbox(
            "Status SP2B/J",
            STATUS_OPTIONS,
            index=STATUS_OPTIONS.index(row.get("SP2BJ_STATUS") or "None") if (row.get("SP2BJ_STATUS") or "None") in STATUS_OPTIONS else 0,
            key="sp2bj_status",
        )
        sp2bj_tgl_val = parse_date_safe(row.get("SP2BJ_TANGGAL"))
        if sp2bj_status == "None":
            sp2bj_tgl = None
            st.caption("Tanggal SP2B/J: (kosong)")
        else:
            sp2bj_tgl = st.date_input(
                "Tanggal SP2B/J",
                value=sp2bj_tgl_val or date.today(),
                key="sp2bj_tgl",
            )

    # PO
    with c2:
        st.markdown("**PO**")
        po_status = st.selectbox(
            "Status PO",
            STATUS_OPTIONS,
            index=STATUS_OPTIONS.index(row.get("PO_STATUS") or "None") if (row.get("PO_STATUS") or "None") in STATUS_OPTIONS else 0,
            key="po_status",
        )
        po_tgl_val = parse_date_safe(row.get("PO_TANGGAL"))
        if po_status == "None":
            po_tgl = None
            st.caption("Tanggal PO: (kosong)")
        else:
            po_tgl = st.date_input(
                "Tanggal PO",
                value=po_tgl_val or date.today(),
                key="po_tgl",
            )

    # Terbayar
    with c3:
        st.markdown("**Terbayar**")
        terbayar_status = st.selectbox(
            "Status Terbayar",
            STATUS_OPTIONS,
            index=STATUS_OPTIONS.index(row.get("TERBAYAR_STATUS") or "None") if (row.get("TERBAYAR_STATUS") or "None") in STATUS_OPTIONS else 0,
            key="terbayar_status",
        )
        terbayar_tgl_val = parse_date_safe(row.get("TERBAYAR_TANGGAL"))
        if terbayar_status == "None":
            terbayar_tgl = None
            st.caption("Tanggal Terbayar: (kosong)")
        else:
            terbayar_tgl = st.date_input(
                "Tanggal Terbayar",
                value=terbayar_tgl_val or date.today(),
                key="terbayar_tgl",
            )

    # 5) Supply
    st.markdown("#### 5) Supply Barang")
    supply_status = st.selectbox(
        "Status Supply",
        STATUS_OPTIONS,
        index=STATUS_OPTIONS.index(row.get("SUPPLY_STATUS") or "None") if (row.get("SUPPLY_STATUS") or "None") in STATUS_OPTIONS else 0,
        key="supply_status",
    )
    supply_tgl_val = parse_date_safe(row.get("SUPPLY_TANGGAL"))
    if supply_status == "None":
        supply_tgl = None
        st.caption("Tanggal Supply: (kosong)")
    else:
        supply_tgl = st.date_input(
            "Tanggal Supply",
            value=supply_tgl_val or date.today(),
            key="supply_tgl",
        )

    st.markdown("---")

    if st.button("💾 Simpan Update"):
        patch = {
            # evaluasi
            "EVALUASI_STATUS": eval_status,
            "EVALUASI_TANGGAL": iso_or_empty(eval_tgl) if eval_status != "None" else "",

            # surat usulan/persetujuan
            "SURAT_USULAN_STATUS": usulan_status,
            "SURAT_USULAN_TANGGAL": iso_or_empty(usulan_tgl) if usulan_status != "None" else "",

            "SURAT_PERSETUJUAN_STATUS": setuju_status,
            "SURAT_PERSETUJUAN_TANGGAL": iso_or_empty(setuju_tgl) if setuju_status != "None" else "",

            # administrasi cabang (status + tanggal)
            "SP2BJ_STATUS": sp2bj_status,
            "SP2BJ_TANGGAL": iso_or_empty(sp2bj_tgl) if sp2bj_status != "None" else "",

            "PO_STATUS": po_status,
            "PO_TANGGAL": iso_or_empty(po_tgl) if po_status != "None" else "",

            "TERBAYAR_STATUS": terbayar_status,
            "TERBAYAR_TANGGAL": iso_or_empty(terbayar_tgl) if terbayar_status != "None" else "",

            # supply
            "SUPPLY_STATUS": supply_status,
            "SUPPLY_TANGGAL": iso_or_empty(supply_tgl) if supply_status != "None" else "",

            # audit
            "LAST_UPDATE": now_utc_iso(),
        }

        try:
            res2 = api_update_request(selected_rid, patch)
            if res2.get("ok"):
                st.success("✅ Update tersimpan. Reload data...")
                st.rerun()
            else:
                st.error(f"Gagal: {res2.get('error')}")
        except Exception as e:
            st.error(f"Error simpan: {e}")
