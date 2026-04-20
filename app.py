import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import random

# ── 페이지 설정 ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Workload Balancing Simulator",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ──────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Noto+Sans+KR:wght@400;500;700&display=swap');

:root {
    --bg: #0d1117;
    --surface: #161b22;
    --surface2: #21262d;
    --border: #30363d;
    --accent: #00d4aa;
    --accent2: #ff6b6b;
    --accent3: #ffd93d;
    --text: #e6edf3;
    --text-muted: #8b949e;
}

html, body, [data-testid="stApp"] {
    background-color: var(--bg) !important;
    color: var(--text) !important;
    font-family: 'Noto Sans KR', sans-serif;
}

[data-testid="stSidebar"] {
    background-color: var(--surface) !important;
    border-right: 1px solid var(--border);
}

[data-testid="stSidebar"] * { color: var(--text) !important; }

.metric-card {
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px 20px;
    margin-bottom: 8px;
}

.metric-card .label {
    font-size: 11px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 1px;
    font-family: 'JetBrains Mono', monospace;
}

.metric-card .value {
    font-size: 28px;
    font-weight: 700;
    font-family: 'JetBrains Mono', monospace;
    color: var(--accent);
}

.high-load  { border-left: 3px solid var(--accent2) !important; }
.low-load   { border-left: 3px solid var(--accent)  !important; }
.normal-load{ border-left: 3px solid var(--accent3) !important; }

.blocked-badge {
    display: inline-block;
    background: rgba(255,107,107,0.15);
    color: var(--accent2);
    border: 1px solid var(--accent2);
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 11px;
    font-family: 'JetBrains Mono', monospace;
}

.open-badge {
    display: inline-block;
    background: rgba(0,212,170,0.12);
    color: var(--accent);
    border: 1px solid var(--accent);
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 11px;
    font-family: 'JetBrains Mono', monospace;
}

.constrained-badge {
    display: inline-block;
    background: rgba(255,217,61,0.12);
    color: var(--accent3);
    border: 1px solid var(--accent3);
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 11px;
    font-family: 'JetBrains Mono', monospace;
}

.section-title {
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: var(--text-muted);
    border-bottom: 1px solid var(--border);
    padding-bottom: 8px;
    margin: 24px 0 16px 0;
}

[data-testid="stDataFrame"] { background: var(--surface2) !important; }

div[data-testid="stSlider"] > div { color: var(--text) !important; }

.stSlider [data-baseweb="slider"] div[role="slider"] {
    background-color: var(--accent) !important;
}
</style>
""", unsafe_allow_html=True)

# ── 샘플 데이터 생성 ──────────────────────────────────────────────────────────
@st.cache_data
def generate_sample_data():
    """샘플 설비·STEPSEQ 데이터 생성"""
    random.seed(42)
    np.random.seed(42)

    equipments = [f"EQ{str(i).zfill(2)}" for i in range(1, 9)]  # 8대 설비

    # 전체 STEPSEQ 목록 (일부는 특정 설비 전용)
    all_steps = [f"STEP_{chr(65+i)}{str(j).zfill(2)}" for i in range(4) for j in range(1, 6)]
    # 특정 설비 전용 STEPSEQ (제약)
    constrained_map = {
        "STEP_A01": ["EQ01"],
        "STEP_B03": ["EQ03", "EQ04"],
        "STEP_C02": ["EQ06"],
        "STEP_D04": ["EQ07", "EQ08"],
    }

    rows = []
    for eq in equipments:
        # 각 설비는 8~14개 STEPSEQ 진행
        n_steps = random.randint(8, 14)
        assigned = random.sample(all_steps, n_steps)
        for step in assigned:
            wip_in_progress = random.randint(0, 30)
            wip_waiting     = random.randint(0, 80)
            st_time         = round(random.uniform(0.5, 8.0), 2)  # 시간 단위

            # 제약 여부
            is_constrained = False
            if step in constrained_map:
                if eq in constrained_map[step]:
                    is_constrained = True
                else:
                    continue  # 전용 설비 아닌 곳에는 해당 STEPSEQ 미배정

            rows.append({
                "설비":         eq,
                "STEPSEQ":     step,
                "진행WIP":      wip_in_progress,
                "대기WIP":      wip_waiting,
                "총WIP":        wip_in_progress + wip_waiting,
                "ST(hr)":      st_time,
                "Workload":    round((wip_in_progress + wip_waiting) * st_time, 2),
                "전용설비여부": is_constrained,
            })

    return pd.DataFrame(rows)

# ── Workload Balancing 로직 ────────────────────────────────────────────────
def run_simulation(df: pd.DataFrame, k_high: float, k_low: float, k_block: int = 999) -> pd.DataFrame:
    """
    k_high  : 이 값 초과  → 고부하 설비  (블로킹 후보)
    k_low   : 이 값 미만  → 저부하 설비  (이전 대상)
    k_block : 고부하 설비당 Workload 상위 k_block개만 실제 블로킹 (0 = 블로킹 없음)
    """
    eq_workload = df.groupby("설비")["Workload"].sum().reset_index()
    eq_workload.columns = ["설비", "설비총Workload"]

    def classify(w):
        if w > k_high:
            return "고부하"
        elif w < k_low:
            return "저부하"
        else:
            return "보통"

    eq_workload["부하구분"] = eq_workload["설비총Workload"].apply(classify)
    df2 = df.merge(eq_workload, on="설비")

    def determine_block(row):
        if row["부하구분"] != "고부하":
            return "해당없음"
        if row["전용설비여부"]:
            return "블로킹불가(전용)"
        return "블로킹후보"

    df2["블로킹여부"] = df2.apply(determine_block, axis=1)

    # 저부하 설비에서 진행 가능한 STEPSEQ 목록
    low_load_steps = set(df2[df2["부하구분"] == "저부하"]["STEPSEQ"].unique())

    def check_redirect(row):
        if row["블로킹여부"] != "블로킹후보":
            return row["블로킹여부"]
        if row["STEPSEQ"] in low_load_steps:
            return "블로킹(저부하 이전 가능)"
        return "블로킹(이전 불가 – 주의)"

    df2["블로킹여부"] = df2.apply(check_redirect, axis=1)

    # ── K_block 적용: 설비별 이전가능 STEPSEQ 중 Workload 상위 k_block개만 실제 블로킹 ──
    if k_block < 999:
        # 이전 가능한 후보 중 상위 k_block개 인덱스 선택
        candidate_mask = df2["블로킹여부"] == "블로킹(저부하 이전 가능)"
        candidates = df2[candidate_mask].copy()

        # 설비별 Workload 내림차순 정렬 후 rank
        candidates["_rank"] = candidates.groupby("설비")["Workload"].rank(
            ascending=False, method="first"
        )
        blocked_idx = candidates[candidates["_rank"] <= k_block].index

        # 블로킹 대상이지만 k_block 초과 → "대기(K_block 초과)"로 표시
        df2.loc[candidate_mask, "블로킹여부"] = "대기(K_block 초과)"
        df2.loc[blocked_idx, "블로킹여부"] = "블로킹(저부하 이전 가능)"

    return df2

# ── Plotly 차트 헬퍼 ──────────────────────────────────────────────────────────
PLOTLY_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#e6edf3", family="JetBrains Mono"),
    margin=dict(l=10, r=10, t=40, b=10),
)

NO_ZOOM = dict(
    scrollZoom=False,
    displayModeBar=False,
)

def chart_eq_workload(eq_wl: pd.DataFrame, k_high: float, k_low: float):
    def bar_color(w):
        if w > k_high:
            return "#ff6b6b"
        elif w < k_low:
            return "#00d4aa"
        else:
            return "#ffd93d"

    colors = [bar_color(w) for w in eq_wl["설비총Workload"]]
    fig = go.Figure(go.Bar(
        x=eq_wl["설비"],
        y=eq_wl["설비총Workload"],
        marker_color=colors,
        text=eq_wl["설비총Workload"].round(1),
        textposition="outside",
        textfont=dict(size=11),
    ))
    fig.add_hline(
        y=k_high,
        line_dash="dash", line_color="#ff6b6b",
        annotation_text=f"  K_high: {k_high:,.0f}",
        annotation_font_color="#ff6b6b",
    )
    fig.add_hline(
        y=k_low,
        line_dash="dash", line_color="#00d4aa",
        annotation_text=f"  K_low: {k_low:,.0f}",
        annotation_font_color="#00d4aa",
    )
    fig.update_layout(
        **PLOTLY_LAYOUT,
        title="설비별 총 Workload  (🔴 고부하 · 🟡 보통 · 🟢 저부하)",
        xaxis=dict(showgrid=False, fixedrange=True),
        yaxis=dict(gridcolor="#21262d", fixedrange=True),
        showlegend=False,
        height=370,
    )
    return fig


def chart_step_workload(df_sim: pd.DataFrame, selected_eq: str):
    df_eq = df_sim[df_sim["설비"] == selected_eq].sort_values("Workload", ascending=True)

    color_map = {
        "블로킹(저부하 이전 가능)":  "#ff6b6b",
        "블로킹(이전 불가 – 주의)":  "#6495ed",
        "블로킹불가(전용)":          "#ffd93d",
        "해당없음":                  "#00d4aa",
        "대기(K_block 초과)":        "#74b9ff",
    }
    bar_colors = [color_map.get(v, "#8b949e") for v in df_eq["블로킹여부"]]

    fig = go.Figure(go.Bar(
        y=df_eq["STEPSEQ"],
        x=df_eq["Workload"],
        orientation="h",
        marker_color=bar_colors,
        text=df_eq["Workload"].round(1),
        textposition="outside",
        showlegend=False,
    ))

    # 범례용 dummy scatter
    legend_items = [
        ("해당없음",             "#00d4aa"),
        ("블로킹(이전 가능)",    "#ff6b6b"),
        ("블로킹(이전 불가)",    "#6495ed"),
        ("전용설비(블로킹불가)", "#ffd93d"),
        ("대기(K_block 초과)",   "#74b9ff"),
    ]
    for label, color in legend_items:
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers",
            marker=dict(size=10, color=color, symbol="square"),
            name=label, showlegend=True,
        ))

    fig.update_layout(
        **PLOTLY_LAYOUT,
        title=f"{selected_eq} – STEPSEQ별 Workload",
        xaxis=dict(gridcolor="#21262d", fixedrange=True),
        yaxis=dict(showgrid=False, fixedrange=True),
        height=max(340, len(df_eq) * 28 + 60),
        legend=dict(
            bgcolor="rgba(22,27,34,0.85)",
            bordercolor="#30363d", borderwidth=1,
            font=dict(size=11, color="#e6edf3"),
            orientation="h",
            yanchor="top", y=-0.08,
            xanchor="left", x=0,
        ),
    )
    fig.update_layout(margin=dict(l=10, r=10, t=40, b=60))
    return fig


def chart_heatmap(df_raw: pd.DataFrame, df_sim: pd.DataFrame):
    # ── 피벗 ──────────────────────────────────────────────────────────────────
    pivot_wl = df_raw.pivot_table(
        index="STEPSEQ", columns="설비", values="Workload", fill_value=0
    )
    stepseqs   = pivot_wl.index.tolist()
    equipments = pivot_wl.columns.tolist()

    # 설비별 부하구분
    eq_class = df_sim.groupby("설비")["부하구분"].first().to_dict()

    # 블로킹 상태 피벗
    block_map = {
        "블로킹(저부하 이전 가능)": 2,   # 빨강
        "블로킹(이전 불가 – 주의)": 3,   # 파랑
    }
    df_block = df_sim.copy()
    df_block["_bnum"] = df_block["블로킹여부"].map(block_map)
    pivot_block = df_block.pivot_table(
        index="STEPSEQ", columns="설비", values="_bnum", aggfunc="first"
    ).reindex(index=stepseqs, columns=equipments, fill_value=0).fillna(0)

    # ── 셀 색상 행렬 구성 ────────────────────────────────────────────────────
    # 0 = 해당없음(회색), 2 = 블로킹 이전가능(빨강), 3 = 블로킹 이전불가(파랑)
    # Workload가 0인 셀(설비-STEPSEQ 조합 없음)은 -1로 처리
    z_color  = []
    z_text   = []
    for step in stepseqs:
        row_c, row_t = [], []
        for eq in equipments:
            wl   = pivot_wl.loc[step, eq]
            bnum = int(pivot_block.loc[step, eq]) if wl > 0 else -1
            row_c.append(bnum)
            row_t.append(f"{wl:.0f}" if wl > 0 else "")
        z_color.append(row_c)
        z_text.append(row_t)

    # colorscale: -1=투명(없음), 0=회색, 2=빨강, 3=파랑
    # 값 범위 -1~3 → 0~1 정규화
    colorscale = [
        [0/4,  "rgba(13,17,23,0)"],      # -1 → 투명 (조합 없음)
        [1/4,  "rgba(48,54,61,0.8)"],    #  0 → 회색 (해당없음)
        [2/4,  "rgba(48,54,61,0.8)"],    #  0~1 구간 채우기
        [3/4,  "rgba(255,107,107,0.75)"],#  2 → 빨강
        [3/4,  "rgba(255,107,107,0.75)"],
        [4/4,  "rgba(100,181,246,0.75)"],#  3 → 파랑
    ]

    fig = go.Figure(go.Heatmap(
        z=z_color,
        x=equipments,
        y=stepseqs,
        text=z_text,
        texttemplate="%{text}",
        textfont=dict(size=9, color="white", family="JetBrains Mono"),
        colorscale=colorscale,
        zmin=-1, zmax=3,
        showscale=False,
        xgap=2, ygap=2,
    ))

    # ── 범례용 dummy scatter ──────────────────────────────────────────────────
    legend_items = [
        ("해당없음",          "rgba(48,54,61,0.8)"),
        ("블로킹(이전 가능)", "rgba(255,107,107,0.85)"),
        ("블로킹(이전 불가)", "rgba(100,181,246,0.85)"),
    ]
    for label, color in legend_items:
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers",
            marker=dict(size=12, color=color, symbol="square"),
            name=label, showlegend=True,
        ))

    # ── X축 레이블: 고부하=빨강▲, 저부하=초록▼, 보통=기본색 ─────────────────
    ticktext = []
    for eq in equipments:
        cls = eq_class.get(eq, "보통")
        if cls == "고부하":
            ticktext.append(f'<b><span style="color:#ff6b6b">{eq} ▲</span></b>')
        elif cls == "저부하":
            ticktext.append(f'<b><span style="color:#00d4aa">{eq} ▼</span></b>')
        else:
            ticktext.append(eq)

    fig.update_layout(
        **PLOTLY_LAYOUT,
        title="설비 × STEPSEQ  Workload & 블로킹 현황",
        height=max(460, len(stepseqs) * 22 + 120),
        xaxis=dict(
            side="top",
            tickvals=equipments,
            ticktext=ticktext,
            fixedrange=True,
            showgrid=False,
            tickfont=dict(size=11),
        ),
        yaxis=dict(
            fixedrange=True, showgrid=False,
            tickfont=dict(size=9, family="JetBrains Mono"),
        ),
        legend=dict(
            bgcolor="rgba(22,27,34,0.85)",
            bordercolor="#30363d", borderwidth=1,
            font=dict(size=11, color="#e6edf3"),
            orientation="h",
            yanchor="top", y=-0.05,
            xanchor="left", x=0,
        ),
    )
    fig.update_layout(margin=dict(l=10, r=10, t=60, b=60))
    return fig



# ── 메인 앱 ──────────────────────────────────────────────────────────────────
def main():
    # 헤더
    st.markdown("""
    <div style="padding: 20px 0 8px 0;">
      <div style="font-family:'JetBrains Mono',monospace; font-size:11px;
                  letter-spacing:3px; color:#8b949e; text-transform:uppercase;">
        MES · Semiconductor
      </div>
      <h1 style="margin:4px 0 2px 0; font-family:'JetBrains Mono',monospace;
                 font-size:26px; color:#e6edf3; font-weight:700;">
        ⚙️ Workload Balancing <span style="color:#00d4aa;">Simulator</span>
      </h1>
      <div style="color:#8b949e; font-size:13px;">
        Threshold 기준값에 따른 고/저부하 설비 구분 및 STEPSEQ 블로킹 시뮬레이션
      </div>
    </div>
    <hr style="border-color:#30363d; margin: 16px 0 0 0;">
    """, unsafe_allow_html=True)

    # ── 사이드바 ─────────────────────────────────────────────────────────────
    # 슬라이더 범위를 사이드바 밖에서 미리 계산 (인라인 슬라이더에서도 사용)
    _df_init = generate_sample_data()  # 초기 범위 계산용 (CSV 업로드 전)
    _eq_init = _df_init.groupby("설비")["Workload"].sum()
    slider_min = round(float(_eq_init.min()) * 0.4, 1)
    slider_max = round(float(_eq_init.max()) * 1.2, 1)

    with st.sidebar:
        st.markdown("### ⚙️ 시뮬레이션 설정")
        st.markdown("---")

        # 데이터 소스 선택
        data_source = st.radio(
            "데이터 소스",
            ["샘플 데이터 사용", "CSV 업로드"],
            help="직접 CSV를 올리거나 샘플 데이터로 테스트하세요."
        )

        if data_source == "CSV 업로드":
            uploaded = st.file_uploader(
                "CSV 파일 업로드",
                type=["csv"],
                help="컬럼: 설비, STEPSEQ, 진행WIP, 대기WIP, ST(hr), 전용설비여부(True/False)"
            )
            if uploaded:
                df_raw = pd.read_csv(uploaded)
                df_raw["총WIP"]    = df_raw["진행WIP"] + df_raw["대기WIP"]
                df_raw["Workload"] = (df_raw["총WIP"] * df_raw["ST(hr)"]).round(2)
                df_raw["전용설비여부"] = df_raw["전용설비여부"].astype(bool)
            else:
                st.info("파일을 업로드하거나 샘플 데이터를 사용하세요.")
                df_raw = generate_sample_data()
        else:
            df_raw = generate_sample_data()

        st.markdown("---")

        # K_high / K_low 슬라이더 범위 (CSV 업로드 시 갱신)
        eq_wl_total = df_raw.groupby("설비")["Workload"].sum()
        wl_min = float(eq_wl_total.min())
        wl_max = float(eq_wl_total.max())
        wl_mean = float(eq_wl_total.mean())
        slider_min = round(wl_min * 0.4, 1)
        slider_max = round(wl_max * 1.2, 1)

        st.markdown("**🔴 K_high  (고부하 기준)**")
        st.caption("이 값 초과 → 고부하 설비 (블로킹 후보)")
        k_high = st.slider(
            "K_high",
            min_value=slider_min,
            max_value=slider_max,
            value=round(wl_mean * 1.1, 1),
            step=1.0,
            format="%.1f",
            key="k_high",
        )

        st.markdown("**🟢 K_low  (저부하 기준)**")
        st.caption("이 값 미만 → 저부하 설비 (이전 수용 대상)")
        # K_low는 K_high와 독립적으로 동작 — max만 전체 범위로 고정
        k_low = st.slider(
            "K_low",
            min_value=slider_min,
            max_value=slider_max,
            value=round(wl_mean * 0.9, 1),
            step=1.0,
            format="%.1f",
            key="k_low",
        )

        st.markdown("**🔵 K_block  (설비당 블로킹 수)**")
        st.caption("고부하 설비당 Workload 상위 K개 STEPSEQ를 블로킹")

        # 블로킹 후보 최대 수 계산 (고부하 설비의 비전용 STEPSEQ 최대치)
        _sim_preview = run_simulation(df_raw, k_high, k_low)
        _max_block = int(
            _sim_preview[_sim_preview["블로킹여부"] == "블로킹(저부하 이전 가능)"]
            .groupby("설비").size().max()
        ) if not _sim_preview[_sim_preview["블로킹여부"] == "블로킹(저부하 이전 가능)"].empty else 1

        k_block = st.slider(
            "K_block",
            min_value=0,
            max_value=max(_max_block, 1),
            value=min(3, _max_block),
            step=1,
            key="k_block",
        )

        if k_low >= k_high:
            st.warning("⚠️ K_low ≥ K_high: 보통 구간 없음 (모든 설비가 고/저부하로만 분류됩니다)")

        st.markdown("---")
        st.markdown("**설비 상세 보기**")
        eq_list = sorted(df_raw["설비"].unique())
        selected_eq = st.selectbox("설비 선택", eq_list)

        st.markdown("---")
        st.caption("🔴 고부하(K_high 초과) · 🟡 보통 · 🟢 저부하(K_low 미만) · 전용설비 제약")

    # ── 시뮬레이션 실행 ──────────────────────────────────────────────────────
    df_sim = run_simulation(df_raw, k_high, k_low, k_block)
    eq_summary = df_sim.groupby("설비").agg(
        설비총Workload=("설비총Workload", "first"),
        부하구분=("부하구분", "first"),
        총STEPSEQ수=("STEPSEQ", "count"),
        블로킹대상수=("블로킹여부", lambda x: (x == "블로킹(저부하 이전 가능)").sum()),
        블로킹불가수=("블로킹여부", lambda x: (x == "블로킹(이전 불가 – 주의)").sum()),
        전용고정수=("블로킹여부", lambda x: (x == "블로킹불가(전용)").sum()),
    ).reset_index()

    high_eq  = (eq_summary["부하구분"] == "고부하").sum()
    mid_eq   = (eq_summary["부하구분"] == "보통").sum()
    low_eq   = (eq_summary["부하구분"] == "저부하").sum()
    total_blocked = (df_sim["블로킹여부"] == "블로킹(저부하 이전 가능)").sum()
    no_redir = (df_sim["블로킹여부"] == "블로킹(이전 불가 – 주의)").sum()
    waiting  = (df_sim["블로킹여부"] == "대기(K_block 초과)").sum()

    # ── 요약 지표 ────────────────────────────────────────────────────────────
    st.markdown('<div class="section-title">Summary</div>', unsafe_allow_html=True)
    c1, c2, c3, c4, c5, c6, c7 = st.columns(7)

    def metric_html(label, value, css_class=""):
        return f"""
        <div class="metric-card {css_class}">
          <div class="label">{label}</div>
          <div class="value">{value}</div>
        </div>"""

    with c1: st.markdown(metric_html("K_high", f"{k_high:,.0f}", "high-load"), unsafe_allow_html=True)
    with c2: st.markdown(metric_html("K_low",  f"{k_low:,.0f}",  "low-load"),  unsafe_allow_html=True)
    with c3: st.markdown(metric_html("K_block", f"{k_block}개"), unsafe_allow_html=True)
    with c4: st.markdown(metric_html("고부하 설비", f"{high_eq}대", "high-load"), unsafe_allow_html=True)
    with c5: st.markdown(metric_html("저부하 설비", f"{low_eq}대", "low-load"), unsafe_allow_html=True)
    with c6: st.markdown(metric_html("블로킹 STEP", f"{total_blocked}건"), unsafe_allow_html=True)
    with c7: st.markdown(metric_html("이전불가(주의)", f"{no_redir}건", "high-load" if no_redir > 0 else ""), unsafe_allow_html=True)

    # ── 차트 영역 ─────────────────────────────────────────────────────────────
    st.markdown('<div class="section-title">설비별 Workload 현황</div>', unsafe_allow_html=True)

    # 가로 K_high / K_low / K_block 슬라이더
    ic1, ic2, ic3 = st.columns(3)
    with ic1:
        st.markdown(
            '<span style="font-family:JetBrains Mono,monospace; font-size:12px; color:#ff6b6b;">▶ K_high</span>'
            '<span style="font-size:11px; color:#8b949e; margin-left:8px;">이 값 초과 → 고부하</span>',
            unsafe_allow_html=True,
        )
        k_high = st.slider(
            "K_high_inline", min_value=slider_min, max_value=slider_max,
            value=k_high, step=1.0, format="%.1f",
            key="k_high_inline", label_visibility="collapsed",
        )
    with ic2:
        st.markdown(
            '<span style="font-family:JetBrains Mono,monospace; font-size:12px; color:#00d4aa;">▶ K_low</span>'
            '<span style="font-size:11px; color:#8b949e; margin-left:8px;">이 값 미만 → 저부하</span>',
            unsafe_allow_html=True,
        )
        # K_low는 K_high와 독립 — max 범위 전체로 고정
        k_low = st.slider(
            "K_low_inline", min_value=slider_min, max_value=slider_max,
            value=k_low, step=1.0, format="%.1f",
            key="k_low_inline", label_visibility="collapsed",
        )
    with ic3:
        st.markdown(
            '<span style="font-family:JetBrains Mono,monospace; font-size:12px; color:#74b9ff;">▶ K_block</span>'
            '<span style="font-size:11px; color:#8b949e; margin-left:8px;">설비당 블로킹 수</span>',
            unsafe_allow_html=True,
        )
        k_block = st.slider(
            "K_block_inline", min_value=0, max_value=max(_max_block, 1),
            value=k_block, step=1,
            key="k_block_inline", label_visibility="collapsed",
        )

    # 인라인 슬라이더 값으로 시뮬레이션 재실행
    df_sim = run_simulation(df_raw, k_high, k_low, k_block)
    eq_summary = df_sim.groupby("설비").agg(
        설비총Workload=("설비총Workload", "first"),
        부하구분=("부하구분", "first"),
        총STEPSEQ수=("STEPSEQ", "count"),
        블로킹대상수=("블로킹여부", lambda x: (x == "블로킹(저부하 이전 가능)").sum()),
        블로킹불가수=("블로킹여부", lambda x: (x == "블로킹(이전 불가 – 주의)").sum()),
        전용고정수=("블로킹여부", lambda x: (x == "블로킹불가(전용)").sum()),
    ).reset_index()

    eq_wl_df = eq_summary[["설비", "설비총Workload"]].copy()
    st.plotly_chart(chart_eq_workload(eq_wl_df, k_high, k_low), use_container_width=True, config=NO_ZOOM)

    col_l2, col_r2 = st.columns([1, 1.6])
    with col_l2:
        st.markdown(f'<div class="section-title">{selected_eq} 상세 분석</div>', unsafe_allow_html=True)
        st.plotly_chart(chart_step_workload(df_sim, selected_eq), use_container_width=True, config=NO_ZOOM)
    with col_r2:
        st.markdown('<div class="section-title">Workload 히트맵 (설비 × STEPSEQ)</div>', unsafe_allow_html=True)
        st.plotly_chart(chart_heatmap(df_raw, df_sim), use_container_width=True, config=NO_ZOOM)

    # ── 블로킹 대상 STEPSEQ 상세 테이블 ────────────────────────────────────
    st.markdown('<div class="section-title">블로킹 대상 STEPSEQ 상세</div>', unsafe_allow_html=True)

    tab1, tab2, tab3, tab4 = st.tabs([
        "🔴 블로킹 (이전 가능)",
        "⏸️ 대기 (K_block 초과)",
        "⚠️ 블로킹 (이전 불가)",
        "🟡 전용설비 고정",
    ])

    cols_show = ["설비", "STEPSEQ", "진행WIP", "대기WIP", "총WIP", "ST(hr)", "Workload", "전용설비여부"]

    with tab1:
        df_t1 = df_sim[df_sim["블로킹여부"] == "블로킹(저부하 이전 가능)"][cols_show].sort_values(["설비", "Workload"], ascending=[True, False])
        if df_t1.empty:
            st.success("블로킹(이전 가능) 대상 STEPSEQ 없음")
        else:
            st.dataframe(df_t1, use_container_width=True, hide_index=True)

    with tab2:
        df_t_wait = df_sim[df_sim["블로킹여부"] == "대기(K_block 초과)"][cols_show].sort_values(["설비", "Workload"], ascending=[True, False])
        if df_t_wait.empty:
            st.info("K_block 초과 대기 STEPSEQ 없음 (모두 블로킹 처리됨)")
        else:
            st.info(f"ℹ️ {len(df_t_wait)}건 — K_block 한도 초과로 이번 차수에 블로킹되지 않은 STEPSEQ입니다.")
            st.dataframe(df_t_wait, use_container_width=True, hide_index=True)

    with tab3:
        df_t2 = df_sim[df_sim["블로킹여부"] == "블로킹(이전 불가 – 주의)"][cols_show].sort_values("Workload", ascending=False)
        if df_t2.empty:
            st.success("블로킹(이전 불가) 대상 STEPSEQ 없음")
        else:
            st.warning(f"⚠️ {len(df_t2)}건의 STEPSEQ가 저부하 설비에 없습니다. 블로킹 전 확인 필요!")
            st.dataframe(df_t2, use_container_width=True, hide_index=True)

    with tab4:
        df_t3 = df_sim[df_sim["블로킹여부"] == "블로킹불가(전용)"][cols_show].sort_values("Workload", ascending=False)
        if df_t3.empty:
            st.info("전용 설비 고정 STEPSEQ 없음")
        else:
            st.dataframe(df_t3, use_container_width=True, hide_index=True)

    # ── 전체 데이터 ───────────────────────────────────────────────────────────
    with st.expander("📋 전체 시뮬레이션 데이터 보기"):
        st.dataframe(df_sim, use_container_width=True, hide_index=True)
        csv = df_sim.to_csv(index=False, encoding="utf-8-sig")
        st.download_button(
            "📥 결과 CSV 다운로드",
            data=csv,
            file_name="workload_balancing_result.csv",
            mime="text/csv",
        )

    # ── 푸터 ────────────────────────────────────────────────────────────────
    st.markdown("""
    <hr style="border-color:#30363d; margin-top:40px;">
    <div style="text-align:center; color:#8b949e; font-size:11px;
                font-family:'JetBrains Mono',monospace; padding:12px 0;">
      MES Workload Balancing Simulator · Semiconductor MFG
    </div>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()

