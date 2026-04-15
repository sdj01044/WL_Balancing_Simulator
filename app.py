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
</style>
""", unsafe_allow_html=True)

# ── 샘플 데이터 생성 ──────────────────────────────────────────────────────────
@st.cache_data
def generate_sample_data():
    random.seed(42)
    np.random.seed(42)
    equipments = [f"EQ{str(i).zfill(2)}" for i in range(1, 9)]
    all_steps = [f"STEP_{chr(65+i)}{str(j).zfill(2)}" for i in range(4) for j in range(1, 6)]
    constrained_map = {
        "STEP_A01": ["EQ01"],
        "STEP_B03": ["EQ03", "EQ04"],
        "STEP_C02": ["EQ06"],
        "STEP_D04": ["EQ07", "EQ08"],
    }
    rows = []
    for eq in equipments:
        n_steps = random.randint(8, 14)
        assigned = random.sample(all_steps, n_steps)
        for step in assigned:
            wip_in_progress = random.randint(0, 30)
            wip_waiting     = random.randint(0, 80)
            st_time         = round(random.uniform(0.5, 8.0), 2)
            is_constrained = False
            if step in constrained_map:
                if eq in constrained_map[step]:
                    is_constrained = True
                else:
                    continue
            rows.append({
                "설비": eq, "STEPSEQ": step, "진행WIP": wip_in_progress,
                "대기WIP": wip_waiting, "총WIP": wip_in_progress + wip_waiting,
                "ST(hr)": st_time, "Workload": round((wip_in_progress + wip_waiting) * st_time, 2),
                "전용설비여부": is_constrained,
            })
    return pd.DataFrame(rows)

# ── 로직 ────────────────────────────────────────────────────────────────────
def run_simulation(df: pd.DataFrame, k_high: float, k_low: float, k_block: int = 999) -> pd.DataFrame:
    eq_workload = df.groupby("설비")["Workload"].sum().reset_index()
    eq_workload.columns = ["설비", "설비총Workload"]
    def classify(w):
        if w > k_high: return "고부하"
        elif w < k_low: return "저부하"
        return "보통"
    eq_workload["부하구분"] = eq_workload["설비총Workload"].apply(classify)
    df2 = df.merge(eq_workload, on="설비")
    def determine_block(row):
        if row["부하구분"] != "고부하": return "해당없음"
        return "블로킹불가(전용)" if row["전용설비여부"] else "블로킹후보"
    df2["블로킹여부"] = df2.apply(determine_block, axis=1)
    low_load_steps = set(df2[df2["부하구분"] == "저부하"]["STEPSEQ"].unique())
    def check_redirect(row):
        if row["블로킹여부"] != "블로킹후보": return row["블로킹여부"]
        return "블로킹(저부하 이전 가능)" if row["STEPSEQ"] in low_load_steps else "블로킹(이전 불가 – 주의)"
    df2["블로킹여부"] = df2.apply(check_redirect, axis=1)
    if k_block < 999:
        candidate_mask = df2["블로킹여부"] == "블로킹(저부하 이전 가능)"
        candidates = df2[candidate_mask].copy()
        candidates["_rank"] = candidates.groupby("설비")["Workload"].rank(ascending=False, method="first")
        blocked_idx = candidates[candidates["_rank"] <= k_block].index
        df2.loc[candidate_mask, "블로킹여부"] = "대기(K_block 초과)"
        df2.loc[blocked_idx, "블로킹여부"] = "블로킹(저부하 이전 가능)"
    return df2

# ── 차트 설정 ────────────────────────────────────────────────────────────────
PLOTLY_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#e6edf3", family="JetBrains Mono"),
    margin=dict(l=10, r=10, t=40, b=10),
)

def chart_eq_workload(eq_wl: pd.DataFrame, k_high: float, k_low: float):
    colors = ["#ff6b6b" if w > k_high else "#00d4aa" if w < k_low else "#ffd93d" for w in eq_wl["설비총Workload"]]
    fig = go.Figure(go.Bar(x=eq_wl["설비"], y=eq_wl["설비총Workload"], marker_color=colors, text=eq_wl["설비총Workload"].round(1), textposition="outside"))
    fig.add_hline(y=k_high, line_dash="dash", line_color="#ff6b6b", annotation_text=f"K_high: {k_high:,.0f}")
    fig.add_hline(y=k_low, line_dash="dash", line_color="#00d4aa", annotation_text=f"K_low: {k_low:,.0f}")
    fig.update_layout(**PLOTLY_LAYOUT, title="설비별 총 Workload", height=370)
    return fig

def chart_step_workload(df_sim: pd.DataFrame, selected_eq: str):
    df_eq = df_sim[df_sim["설비"] == selected_eq].sort_values("Workload", ascending=True)
    color_map = {"블로킹(저부하 이전 가능)": "#ff6b6b", "블로킹(이전 불가 – 주의)": "#ee5a24", "블로킹불가(전용)": "#ffd93d", "해당없음": "#00d4aa"}
    fig = go.Figure(go.Bar(y=df_eq["STEPSEQ"], x=df_eq["Workload"], orientation="h", marker_color=[color_map.get(v, "#8b949e") for v in df_eq["블로킹여부"]]))
    fig.update_layout(**PLOTLY_LAYOUT, title=f"{selected_eq} – 상세 Workload", height=max(300, len(df_eq) * 28))
    return fig

def chart_heatmap(df_sim: pd.DataFrame):
    pivot_wl = df_sim.pivot_table(index="STEPSEQ", columns="설비", values="Workload", fill_value=0)
    status_map = {"블로킹(저부하 이전 가능)": 3, "블로킹(이전 불가 – 주의)": 4, "블로킹불가(전용)": 2, "대기(K_block 초과)": 1, "해당없음": 0}
    df_status = df_sim.copy()
    df_status["_status_num"] = df_status["블로킹여부"].map(status_map).fillna(0)
    pivot_st = df_status.pivot_table(index="STEPSEQ", columns="설비", values="_status_num", fill_value=-1)
    
    stepseqs, equipments = pivot_wl.index.tolist(), pivot_wl.columns.tolist()
    color_palette = {-1: "rgba(0,0,0,0)", 0: "rgba(33,38,45,0.9)", 1: "rgba(116,185,255,0.25)", 2: "rgba(255,217,61,0.35)", 3: "rgba(255,107,107,0.55)", 4: "rgba(238,90,36,0.75)"}
    
    fig = go.Figure()
    shapes, annotations = [], []
    for ci, eq in enumerate(equipments):
        for ri, step in enumerate(stepseqs):
            snum = int(pivot_st.loc[step, eq]) if step in pivot_st.index else -1
            wl = pivot_wl.loc[step, eq] if step in pivot_wl.index else 0
            shapes.append(dict(type="rect", xref="x", yref="y", x0=ci-0.5, x1=ci+0.5, y0=ri-0.5, y1=ri+0.5, fillcolor=color_palette.get(snum), line=dict(width=0), layer="below"))
            if wl > 0: annotations.append(dict(x=ci, y=ri, text=f"{wl:.0f}", showarrow=False, font=dict(size=9, color="#ffffff" if snum in (3, 4) else "#c9d1d9")))

    # 중복 에러 방지: PLOTLY_LAYOUT 적용 후 개별 값 덮어쓰기
    fig.update_layout(**PLOTLY_LAYOUT)
    fig.update_layout(
        title="설비 × STEPSEQ 현황",
        shapes=shapes, annotations=annotations,
        xaxis=dict(tickvals=list(range(len(equipments))), ticktext=equipments, side="top"),
        yaxis=dict(tickvals=list(range(len(stepseqs))), ticktext=stepseqs, autorange="reversed"),
        height=max(500, len(stepseqs) * 22 + 120),
        margin=dict(l=10, r=10, t=100, b=10) # Heatmap 전용 마진
    )
    return fig

# ── 메인 ────────────────────────────────────────────────────────────────────
def main():
    st.markdown('<h1 style="color:#e6edf3;">⚙️ Workload Balancing <span style="color:#00d4aa;">Simulator</span></h1>', unsafe_allow_html=True)
    df_raw = generate_sample_data()
    
    with st.sidebar:
        st.header("⚙️ Settings")
        wl_mean = df_raw.groupby("설비")["Workload"].sum().mean()
        k_high = st.slider("K_high", 0.0, wl_mean*2, wl_mean*1.1)
        k_low = st.slider("K_low", 0.0, wl_mean*2, wl_mean*0.9)
        k_block = st.slider("K_block", 0, 10, 3)
        selected_eq = st.selectbox("설비 선택", sorted(df_raw["설비"].unique()))

    df_sim = run_simulation(df_raw, k_high, k_low, k_block)
    
    # 지표 표시
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("고부하 설비", f"{(df_sim.groupby('설비')['부하구분'].first() == '고부하').sum()}대")
    c2.metric("저부하 설비", f"{(df_sim.groupby('설비')['부하구분'].first() == '저부하').sum()}대")
    c3.metric("블로킹 대상", f"{(df_sim['블로킹여부'] == '블로킹(저부하 이전 가능)').sum()}건")
    c4.metric("이전불가(주의)", f"{(df_sim['블로킹여부'] == '블로킹(이전 불가 – 주의)').sum()}건")

    st.plotly_chart(chart_eq_workload(df_sim.groupby("설비")["Workload"].sum().reset_index(), k_high, k_low), use_container_width=True)
    
    col1, col2 = st.columns([1, 1.5])
    with col1: st.plotly_chart(chart_step_workload(df_sim, selected_eq), use_container_width=True)
    with col2: st.plotly_chart(chart_heatmap(df_sim), use_container_width=True)

    st.markdown('<div class="section-title">상세 데이터</div>', unsafe_allow_html=True)
    st.dataframe(df_sim[df_sim["블로킹여부"].str.contains("블로킹|대기")], use_container_width=True, hide_index=True)

if __name__ == "__main__":
    main()
