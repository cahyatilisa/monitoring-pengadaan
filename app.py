import base64
import json
from datetime import date
import pandas as pd
import requests
import streamlit as st

# =========================
# CONFIG + STYLE
# =========================
st.set_page_config(page_title="Monitoring Pengadaan", layout="wide")

st.markdown(
    """
<style>
/* Besarin font tabel */
div[data-testid="stDataFrame"] * { font-size: 15px !important; }

/* Bungkus teks supaya tidak melebar ke kanan */
div[data-testid="stDataFrame"] td,
div[data-testid="stDataFrame"] th {
  white-space: normal !important;
  word-break: break-word !important;
}

/* Sedikit rapihin padding */
.block-container { padding-top: 1rem; padding-bottom: 2rem; }
</style>
""",
    unsafe_allow_html=True,
)

WEBAPP_URL = st.secrets.get("WEBAPP_URL", "").strip()
TEKNIK_KEY = st.secrets.get("TEKNIK_KEY", "").strip()

if not WEBAPP_URL:
    st.error("WEBAPP_URL belum diisi di Streamlit Secrets.")
    st.stop()

# OPTIONAL: kalau kamu mau User Kapal bisa search status tanpa login teknik,
# isi READ_KEY di secrets, dan di Apps Script kamu izinkan list_requests pakai READ_KEY.
READ_KEY = st.secrets.get("READ_KEY", "").strip()

STAGES = [
    ("EVALUASI", "1) Evaluasi Cabang"),
    ("SURAT_USULAN", "2) Surat Usulan ke Pusat"),
    ("SURAT_PERSETUJUAN", "3) Surat Persetujuan Pusat"),
    ("SP2BJ", "4) SP2BJ"),
    ("PO", "5) PO"),
    ("TERBAYAR", "6) Terbayar"),
    ("SUPPLY", "7) Supply Barang"),
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
    return post_api(
        {
            "action": "submit_request",
            "tanggal_upload": tanggal_upload.strftime("%Y-%m-%d"),
            "no_spbj_kapal": (no_spbj or "").strip(),
            "judul_permintaan": judul.strip(),
            "files": files_payload,
        }
    )


def api_list_requests(key: str) -> pd.DataFrame:
    res = post_api({"action": "list_requests", "key": key})
    if not res.get("ok"):
        raise RuntimeError(res.get("error", "API list_requests gagal"))
    rows = res.get("data") or res.get("rows") or []
    return pd.DataFrame(rows)


def api_update_request(request_id: str, fields: dict) -> dict:
    return post_api(
        {
            "action": "update_request",
            "key": TEKNIK_KEY,
            "request_id": request_id,
            "fields": fields,
        }
    )


# =========================
# DATA HELPERS
# =========================
def clean_status(x) -> str:
    s = str(x or "").strip()
    if not s or s.lower() == "none":
        return "None"
    low = s.lower()
    if low in ["in process", "in_progress", "progress", "ongoing", "process"]:
        return "In Process"
    if low in ["done", "selesai", "completed", "finish", "finished", "ok", "yes", "true", "1"]:
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


def iso_or_empty(d: date | None) -> str:
    return d.strftime("%Y-%m-%d") if d else ""


def fmt_ddmmyyyy(x) -> str:
    """Terima 'YYYY-MM-DD' atau ISO panjang, keluarkan 'DD-MM-YYYY' atau ''."""
    d = parse_date_any(x)
    return d.strftime("%d-%m-%Y") if d else ""


def stage_cell(status, tanggal) -> str:
    stt = clean_status(status)
    t = fmt_ddmmyyyy(tanggal)
    if stt == "Done" and t:
        return f"✅ Done • {t}"
    if stt == "In Process":
        return "🟡 In Process"
    return "⚪ None"


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


def first_file_download_link(files_json: str) -> str:
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
            res = api_submit_request(tanggal_upload, no_spbj, judul, files_payload)
            if res.get("ok"):
                st.success(f"✅ Berhasil! REQUEST_ID: {res.get('request_id')}")
                st.info("Simpan REQUEST_ID ini. Tim Teknik akan memproses dan update status.")
            else:
                st.error(f"Gagal: {res.get('error')}")
        except Exception as e:
            st.error(f"Error koneksi / API: {e}")

    st.markdown("---")
    st.subheader("Cek Status (Opsional)")
    st.caption("Fitur ini hanya aktif kalau kamu isi READ_KEY di Secrets dan Apps Script mengizinkan akses baca.")

    q_public = st.text_input("Cari berdasarkan No. SPBJ / Judul / REQUEST_ID", key="public_search")
    if q_public:
        if not READ_KEY:
            st.info("READ_KEY belum diisi di Secrets, jadi User Kapal belum bisa cek status.")
        else:
            try:
                df_pub = api_list_requests(READ_KEY)
                if df_pub.empty:
                    st.info("Belum ada data.")
                else:
                    df_pub.columns = [str(c).strip().upper() for c in df_pub.columns]

                    for col in ["REQUEST_ID", "NO_SPBJ_KAPAL", "JUDUL_PERMINTAAN", "TANGGAL_UPLOAD", "FILES_JSON"]:
                        if col not in df_pub.columns:
                            df_pub[col] = ""

                    qq = q_public.lower()
                    df_pub2 = df_pub[
                        df_pub["REQUEST_ID"].astype(str).str.lower().str.contains(qq, na=False)
                        | df_pub["NO_SPBJ_KAPAL"].astype(str).str.lower().str.contains(qq, na=False)
                        | df_pub["JUDUL_PERMINTAAN"].astype(str).str.lower().str.contains(qq, na=False)
                    ].copy()

                    if df_pub2.empty:
                        st.info("Tidak ada hasil.")
                    else:
                        # ringkas
                        df_pub2["FILE_1"] = df_pub2["FILES_JSON"].apply(first_file_download_link)
                        show_pub = pd.DataFrame(
                            {
                                "REQUEST_ID": df_pub2["REQUEST_ID"].astype(str),
                                "TGL_UPLOAD": df_pub2["TANGGAL_UPLOAD"].apply(fmt_ddmmyyyy),
                                "NO_SPBJ": df_pub2["NO_SPBJ_KAPAL"].astype(str),
                                "JUDUL": df_pub2["JUDUL_PERMINTAAN"].astype(str),
                                "FILE": df_pub2["FILE_1"].astype(str),
                            }
                        )
                        st.dataframe(
                            show_pub,
                            use_container_width=True,
                            hide_index=True,
                            column_config={
                                "FILE": st.column_config.LinkColumn("Lampiran", display_text="Download"),
                            },
                        )
            except Exception as e:
                st.error(f"Gagal cek status: {e}")


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

    col_top1, col_top2 = st.columns([1, 4])
    with col_top1:
        if st.button("Logout"):
            st.session_state.teknik_logged = False
            st.rerun()
    with col_top2:
        st.caption("Tips: gunakan search agar tabel tidak terlalu panjang.")

    # ambil data
    try:
        df = api_list_requests(TEKNIK_KEY)
    except Exception as e:
        st.error(f"Error ambil data: {e}")
        st.stop()

    if df.empty:
        st.info("Belum ada permintaan masuk.")
        st.stop()

    # NORMALISASI KOLOM (penting agar nyambung ke spreadsheet)
    df.columns = [str(c).strip().upper() for c in df.columns]

    # Pastikan kolom minimal ada
    base_cols = ["REQUEST_ID", "TANGGAL_UPLOAD", "NO_SPBJ_KAPAL", "JUDUL_PERMINTAAN", "FILES_JSON", "LAST_UPDATE"]
    for c in base_cols:
        if c not in df.columns:
            df[c] = ""

    # Pastikan stage status/tanggal ada
    for code, _label in STAGES:
        s_col = f"{code}_STATUS"
        d_col = f"{code}_TANGGAL"
        if s_col not in df.columns:
            df[s_col] = "None"
        if d_col not in df.columns:
            df[d_col] = ""

    # AUTO-CLEAN DATA WARISAN: jika status bukan Done => tanggal dikosongkan
    for code, _label in STAGES:
        s_col = f"{code}_STATUS"
        d_col = f"{code}_TANGGAL"
        df[s_col] = df[s_col].apply(clean_status)
        df.loc[df[s_col] != "Done", d_col] = ""

    # file link pertama (ringkas)
    df["FILE_1"] = df["FILES_JSON"].apply(first_file_download_link)

    st.markdown("### Daftar Permintaan (Ringkas)")
    q = st.text_input("🔎 Cari (No SPBJ / Judul / Request ID)", placeholder="contoh: 123 / pompa / REQ-...", key="teknik_search")

    df_view = df.copy()
    if q:
        qq = q.lower()
        df_view = df_view[
            df_view["REQUEST_ID"].astype(str).str.lower().str.contains(qq, na=False)
            | df_view["NO_SPBJ_KAPAL"].astype(str).str.lower().str.contains(qq, na=False)
            | df_view["JUDUL_PERMINTAAN"].astype(str).str.lower().str.contains(qq, na=False)
        ].copy()

    show_df = pd.DataFrame(
        {
            "REQUEST_ID": df_view["REQUEST_ID"].astype(str),
            "TGL_UPLOAD": df_view["TANGGAL_UPLOAD"].apply(fmt_ddmmyyyy),
            "NO_SPBJ": df_view["NO_SPBJ_KAPAL"].astype(str),
            "JUDUL": df_view["JUDUL_PERMINTAAN"].astype(str),
            "LAMPIRAN": df_view["FILE_1"].astype(str),
            "Evaluasi": df_view.apply(lambda r: stage_cell(r["EVALUASI_STATUS"], r["EVALUASI_TANGGAL"]), axis=1),
            "Usulan": df_view.apply(lambda r: stage_cell(r["SURAT_USULAN_STATUS"], r["SURAT_USULAN_TANGGAL"]), axis=1),
            "Persetujuan": df_view.apply(lambda r: stage_cell(r["SURAT_PERSETUJUAN_STATUS"], r["SURAT_PERSETUJUAN_TANGGAL"]), axis=1),
            "SP2BJ": df_view.apply(lambda r: stage_cell(r["SP2BJ_STATUS"], r["SP2BJ_TANGGAL"]), axis=1),
            "PO": df_view.apply(lambda r: stage_cell(r["PO_STATUS"], r["PO_TANGGAL"]), axis=1),
            "Terbayar": df_view.apply(lambda r: stage_cell(r["TERBAYAR_STATUS"], r["TERBAYAR_TANGGAL"]), axis=1),
            "Supply": df_view.apply(lambda r: stage_cell(r["SUPPLY_STATUS"], r["SUPPLY_TANGGAL"]), axis=1),
        }
    )

    st.dataframe(
        show_df,
        use_container_width=True,
        hide_index=True,
        height=420,
        column_config={
            "LAMPIRAN": st.column_config.LinkColumn("Lampiran", display_text="Download"),
        },
    )

    st.markdown("---")
    st.markdown("### Update Progress (Pilih 1 REQUEST_ID)")

    rid_list = df_view["REQUEST_ID"].astype(str).tolist()
    if not rid_list:
        st.info("Tidak ada data sesuai filter.")
        st.stop()

    selected_rid = st.selectbox("REQUEST_ID", rid_list, key="pick_rid")

    row = df[df["REQUEST_ID"].astype(str) == str(selected_rid)].iloc[0].to_dict()

    # detail + lampiran
    colA, colB = st.columns([1.1, 1.2], gap="large")

    with colA:
        st.write("**Tanggal Upload:**", fmt_ddmmyyyy(row.get("TANGGAL_UPLOAD")))
        st.write("**No SPBJ Kapal:**", row.get("NO_SPBJ_KAPAL", ""))
        st.write("**Judul:**", row.get("JUDUL_PERMINTAAN", ""))

        files_list = parse_files_json(row.get("FILES_JSON"))
        st.markdown("**Lampiran (Download):**")
        if not files_list:
            st.caption("(Tidak ada file / belum terbaca)")
        else:
            for f in files_list:
                name = f.get("name", "file")
                url = f.get("downloadUrl") or f.get("viewUrl")
                if not url:
                    fid = f.get("fileId") or f.get("id")
                    if fid:
                        url = f"https://drive.google.com/uc?export=download&id={fid}"
                if url:
                    st.markdown(f"- [{name}]({url})")
                else:
                    st.markdown(f"- {name}")

    with colB:
        st.info("Aturan: pilih **Done** ➜ wajib isi tanggal. Pilih **None/In Process** ➜ tanggal otomatis kosong.")

        patch = {}

        for code, label in STAGES:
            s_col = f"{code}_STATUS"
            d_col = f"{code}_TANGGAL"

            st.markdown(f"#### {label}")

            cur_status = clean_status(row.get(s_col, "None"))
            status = st.selectbox(
                f"Status {label}",
                STATUS_OPTIONS,
                index=STATUS_OPTIONS.index(cur_status) if cur_status in STATUS_OPTIONS else 0,
                key=f"{selected_rid}_{code}_status",
            )

            if status == "Done":
                cur_date = parse_date_any(row.get(d_col))
                dval = st.date_input(
                    f"Tanggal {label}",
                    value=cur_date or date.today(),
                    format="DD/MM/YYYY",
                    key=f"{selected_rid}_{code}_date",
                )
                patch[s_col] = "Done"
                patch[d_col] = iso_or_empty(dval)
            else:
                st.caption(f"Tanggal {label}: (kosong)")
                patch[s_col] = status
                patch[d_col] = ""  # kosongkan

        st.markdown("---")
        if st.button("💾 Simpan Update", key="save_update"):
            # validasi: Done harus punya tanggal (sudah dipastikan ada date_input)
            try:
                res = api_update_request(str(selected_rid), patch)
                if res.get("ok"):
                    st.success("✅ Update tersimpan.")
                    st.rerun()
                else:
                    st.error(f"Gagal: {res.get('error')}")
            except Exception as e:
                st.error(f"Error simpan: {e}")
