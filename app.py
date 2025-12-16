import base64
import json
from datetime import date
import requests
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Monitoring Pengadaan", layout="wide")

WEBAPP_URL = st.secrets.get("WEBAPP_URL", "").strip()
TEKNIK_KEY = st.secrets.get("TEKNIK_KEY", "").strip()

if not WEBAPP_URL:
    st.error("WEBAPP_URL belum diisi di Streamlit Secrets.")
    st.stop()
import json
import pandas as pd
import requests
import streamlit as st
from datetime import date

WEBAPP_URL = st.secrets["WEBAPP_URL"]
TEKNIK_KEY = st.secrets["TEKNIK_KEY"]

def post_api(payload: dict) -> dict:
    r = requests.post(WEBAPP_URL, json=payload, timeout=60)
    r.raise_for_status()
    return r.json()

def api_list_requests() -> pd.DataFrame:
    res = post_api({"action": "list_requests", "key": TEKNIK_KEY})
    if not res.get("ok"):
        raise RuntimeError(res.get("error", "API list_requests gagal"))
    rows = res.get("rows") or res.get("data") or []
    df = pd.DataFrame(rows)
    return df

def api_update_request(request_id: str, fields: dict) -> dict:
    res = post_api({
        "action": "update_request",
        "key": TEKNIK_KEY,
        "request_id": request_id,
        "fields": fields
    })
    return res

def drive_link_from_value(v: str) -> str:
    if not v:
        return ""
    v = str(v).strip()

    # kalau FILES_JSON kamu ternyata berisi JSON list file, ambil folder/file pertama
    if v.startswith("[") or v.startswith("{"):
        try:
            obj = json.loads(v)
            if isinstance(obj, list) and len(obj) > 0:
                # kalau ada folderId atau id file
                cand = obj[0].get("folderId") or obj[0].get("id")
                if cand:
                    v = cand
        except Exception:
            pass

    # asumsi paling aman: ini folder ID Drive
    return f"https://drive.google.com/drive/folders/{v}"

def post_api(payload: dict) -> dict:
    r = requests.post(WEBAPP_URL, json=payload, timeout=60)
    r.raise_for_status()
    return r.json()

def iso_or_empty(d: date | None) -> str:
    return d.isoformat() if d else ""

def to_bool(x) -> bool:
    if isinstance(x, bool):
        return x
    if isinstance(x, str):
        return x.strip().lower() in ["true", "yes", "y", "1", "checked"]
    if isinstance(x, (int, float)):
        return x != 0
    return False

def parse_files_json(x):
    if not x:
        return []
    if isinstance(x, list):
        return x
    if isinstance(x, str):
        try:
            return json.loads(x)
        except Exception:
            return []
    return []

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
        st.stop()  # <- WAJIB di sini (biar halaman stop kalau belum login)

    # =============== mulai dari sini: sudah login ===============
    # Ambil data
    try:
        res = post_api({"action": "list_requests"})
        if not res.get("ok"):
            st.error(res.get("error"))
            st.stop()
        data = res.get("data", [])
    except Exception as e:
        st.error(f"Error ambil data: {e}")
        st.stop()

    if not data:
        st.info("Belum ada permintaan masuk.")
        st.stop()

    # ... lanjutkan kode monitoring kamu di bawah sini ...


    # Ambil data
    try:
        res = post_api({"action": "list_requests"})
        if not res.get("ok"):
            st.error(res.get("error"))
            st.stop()
        data = res.get("data", [])
    except Exception as e:
        st.error(f"Error ambil data: {e}")
        st.stop()

    if not data:
        st.info("Belum ada permintaan masuk.")
        st.stop()

    df = pd.DataFrame(data)

    # Rapihin kolom (kalau ada kolom yang belum ada di data)
    expected_cols = [
        "REQUEST_ID","TANGGAL_UPLOAD","NO_SPBJ_KAPAL","JUDUL_PERMINTAAN","FILES_JSON",
        "EVALUASI_STATUS","EVALUASI_TANGGAL",
        "SURAT_USULAN_TANGGAL","SURAT_PERSETUJUAN_TANGGAL",
        "SP2BJ_CHECK","SP2BJ_TANGGAL",
        "PO_CHECK","PO_TANGGAL",
        "TERBAYAR_CHECK","TERBAYAR_TANGGAL",
        "SUPPLY_STATUS","SUPPLY_TANGGAL",
        "LAST_UPDATE"
    ]
    for c in expected_cols:
        if c not in df.columns:
            df[c] = ""

    # Tampilkan ringkas
    show_df = df[["REQUEST_ID","TANGGAL_UPLOAD","NO_SPBJ_KAPAL","JUDUL_PERMINTAAN",
                  "EVALUASI_STATUS","SURAT_USULAN_TANGGAL","SURAT_PERSETUJUAN_TANGGAL",
                  "SP2BJ_CHECK","PO_CHECK","TERBAYAR_CHECK",
                  "SUPPLY_STATUS","LAST_UPDATE"]].copy()

    st.markdown("### Daftar Permintaan")
    st.dataframe(show_df, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("### Update Progress (pilih 1 REQUEST_ID)")

    rid_list = df["REQUEST_ID"].tolist()
    selected_rid = st.selectbox("REQUEST_ID", rid_list)

    row = df[df["REQUEST_ID"] == selected_rid].iloc[0].to_dict()

    files_list = parse_files_json(row.get("FILES_JSON"))

    colA, colB = st.columns([1.2, 1])
    with colA:
        st.write("**Tanggal Upload:**", row.get("TANGGAL_UPLOAD",""))
        st.write("**No SPBJ Kapal:**", row.get("NO_SPBJ_KAPAL",""))
        st.write("**Judul:**", row.get("JUDUL_PERMINTAAN",""))

        st.markdown("**File Lampiran (Download):**")
        if not files_list:
            st.caption("(Tidak ada file)")
        else:
            for f in files_list:
                name = f.get("name","file")
                url = f.get("downloadUrl") or f.get("viewUrl")
                if url:
                    st.markdown(f"- [{name}]({url})")
                else:
                    st.markdown(f"- {name}")

    with colB:
        st.markdown("#### 1) Evaluasi Cabang")
        eval_status = st.selectbox(
            "Status Evaluasi",
            ["None","In Process","Done"],
            index=["None","In Process","Done"].index(row.get("EVALUASI_STATUS") or "None")
            if (row.get("EVALUASI_STATUS") or "None") in ["None","In Process","Done"] else 0
        )
        eval_tgl = st.date_input(
            "Tanggal Evaluasi (isi saat selesai/ada progress)",
            value=date.fromisoformat(row["EVALUASI_TANGGAL"]) if row.get("EVALUASI_TANGGAL") else date.today()
        )

        st.markdown("#### 2) Surat Usulan ke Pusat")
        usulan_tgl = st.date_input(
            "Tanggal Surat Usulan",
            value=date.fromisoformat(row["SURAT_USULAN_TANGGAL"]) if row.get("SURAT_USULAN_TANGGAL") else date.today()
        )

        st.markdown("#### 3) Surat Persetujuan Pusat")
        setuju_tgl = st.date_input(
            "Tanggal Surat Persetujuan",
            value=date.fromisoformat(row["SURAT_PERSETUJUAN_TANGGAL"]) if row.get("SURAT_PERSETUJUAN_TANGGAL") else date.today()
        )

    st.markdown("#### 4) Administrasi Cabang")
    c1, c2, c3 = st.columns(3)

    sp2bj_check = to_bool(row.get("SP2BJ_CHECK"))
    po_check = to_bool(row.get("PO_CHECK"))
    terbayar_check = to_bool(row.get("TERBAYAR_CHECK"))

    with c1:
        sp2bj_check_new = st.checkbox("SP2B/J", value=sp2bj_check)
        sp2bj_tgl = st.date_input(
            "Tanggal SP2B/J",
            value=date.fromisoformat(row["SP2BJ_TANGGAL"]) if row.get("SP2BJ_TANGGAL") else date.today(),
            key="sp2bj_tgl"
        )
    with c2:
        po_check_new = st.checkbox("PO", value=po_check)
        po_tgl = st.date_input(
            "Tanggal PO",
            value=date.fromisoformat(row["PO_TANGGAL"]) if row.get("PO_TANGGAL") else date.today(),
            key="po_tgl"
        )
    with c3:
        terbayar_check_new = st.checkbox("Terbayar", value=terbayar_check)
        terbayar_tgl = st.date_input(
            "Tanggal Terbayar",
            value=date.fromisoformat(row["TERBAYAR_TANGGAL"]) if row.get("TERBAYAR_TANGGAL") else date.today(),
            key="terbayar_tgl"
        )

    st.markdown("#### 5) Supply Barang")
    supply_status = st.selectbox(
        "Status Supply",
        ["None","In Process","Done"],
        index=["None","In Process","Done"].index(row.get("SUPPLY_STATUS") or "None")
        if (row.get("SUPPLY_STATUS") or "None") in ["None","In Process","Done"] else 0
    )
    supply_tgl = st.date_input(
        "Tanggal Supply (isi saat selesai/ada progress)",
        value=date.fromisoformat(row["SUPPLY_TANGGAL"]) if row.get("SUPPLY_TANGGAL") else date.today(),
        key="supply_tgl"
    )

    st.markdown("---")
    if st.button("💾 Simpan Update"):
        patch = {
            "EVALUASI_STATUS": eval_status,
            "EVALUASI_TANGGAL": iso_or_empty(eval_tgl),

            "SURAT_USULAN_TANGGAL": iso_or_empty(usulan_tgl),
            "SURAT_PERSETUJUAN_TANGGAL": iso_or_empty(setuju_tgl),

            "SP2BJ_CHECK": bool(sp2bj_check_new),
            "SP2BJ_TANGGAL": iso_or_empty(sp2bj_tgl) if sp2bj_check_new else "",

            "PO_CHECK": bool(po_check_new),
            "PO_TANGGAL": iso_or_empty(po_tgl) if po_check_new else "",

            "TERBAYAR_CHECK": bool(terbayar_check_new),
            "TERBAYAR_TANGGAL": iso_or_empty(terbayar_tgl) if terbayar_check_new else "",

            "SUPPLY_STATUS": supply_status,
            "SUPPLY_TANGGAL": iso_or_empty(supply_tgl),
        }

        try:
            res2 = post_api({
                "action": "update_request",
                "teknik_key": TEKNIK_KEY,
                "request_id": selected_rid,
                "patch": patch
            })
            if res2.get("ok"):
                st.success("✅ Update tersimpan.")
                st.rerun()
            else:
                st.error(f"Gagal: {res2.get('error')}")
        except Exception as e:
            st.error(f"Error simpan: {e}")
