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
def run_simulation(df: pd.DataFrame, threshold: float) -> pd.DataFrame:
    """
    threshold 기준으로 고/저 부하 설비 구분 후
    고부하 설비의 블로킹 대상 STEPSEQ 결정
    """
    # 설비별 총 Workload 합산
    eq_workload = df.groupby("설비")["Workload"].sum().reset_index()
    eq_workload.columns = ["설비", "설비총Workload"]

    # 고/저 부하 분류
    eq_workload["부하구분"] = eq_workload["설비총Workload"].apply(
        lambda w: "고부하" if w > threshold else "저부하"
    )

    df2 = df.merge(eq_workload, on="설비")

    # 블로킹 로직
    # - 고부하 설비 중 전용설비여부=False 인 STEPSEQ 만 블로킹 후보
    # - 고부하 설비에서 Workload 내림차순 정렬
    def determine_block(row):
        if row["부하구분"] != "고부하":
            return "해당없음"
        if row["전용설비여부"]:
            return "블로킹불가(전용)"
        return "블로킹대상"

    df2["블로킹여부"] = df2.apply(determine_block, axis=1)

    # 블로킹 대상 STEPSEQ 이 저부하 설비에서 진행 가능한지 확인
    low_load_steps = set(
        df2[df2["부하구분"] == "저부하"]["STEPSEQ"].unique()
    )

    def check_redirect(row):
        if row["블로킹여부"] != "블로킹대상":
            return row["블로킹여부"]
        if row["STEPSEQ"] in low_load_steps:
            return "블로킹(저부하 이전 가능)"
        return "블로킹(이전 불가 – 주의)"

    df2["블로킹여부"] = df2.apply(check_redirect, axis=1)

    return df2

# ── Plotly 차트 헬퍼 ──────────────────────────────────────────────────────────
PLOTLY_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#e6edf3", family="JetBrains Mono"),
    margin=dict(l=10, r=10, t=40, b=10),
)

def chart_eq_workload(eq_wl: pd.DataFrame, threshold: float):
    colors = [
        "#ff6b6b" if w > threshold else "#00d4aa"
        for w in eq_wl["설비총Workload"]
    ]
    fig = go.Figure(go.Bar(
        x=eq_wl["설비"],
        y=eq_wl["설비총Workload"],
        marker_color=colors,
        text=eq_wl["설비총Workload"].round(1),
        textposition="outside",
        textfont=dict(size=11),
    ))
    fig.add_hline(
        y=threshold,
        line_dash="dash",
        line_color="#ffd93d",
        annotation_text=f"  Threshold: {threshold:,.0f}",
        annotation_font_color="#ffd93d",
    )
    fig.update_layout(
        **PLOTLY_LAYOUT,
        title="설비별 총 Workload",
        xaxis=dict(showgrid=False),
        yaxis=dict(gridcolor="#21262d"),
        showlegend=False,
        height=350,
    )
    return fig


def chart_step_workload(df_sim: pd.DataFrame, selected_eq: str):
    df_eq = df_sim[df_sim["설비"] == selected_eq].sort_values("Workload", ascending=True)

    color_map = {
        "블로킹대상":            "#ff6b6b",
        "블로킹(저부하 이전 가능)": "#ff9f43",
        "블로킹(이전 불가 – 주의)": "#ee5a24",
        "블로킹불가(전용)":        "#ffd93d",
        "해당없음":              "#00d4aa",
    }
    bar_colors = [color_map.get(v, "#8b949e") for v in df_eq["블로킹여부"]]

    fig = go.Figure(go.Bar(
        y=df_eq["STEPSEQ"],
        x=df_eq["Workload"],
        orientation="h",
        marker_color=bar_colors,
        text=df_eq["Workload"].round(1),
        textposition="outside",
    ))
    fig.update_layout(
        **PLOTLY_LAYOUT,
        title=f"{selected_eq} – STEPSEQ별 Workload",
        xaxis=dict(gridcolor="#21262d"),
        yaxis=dict(showgrid=False),
        height=max(300, len(df_eq) * 28),
    )
    return fig


def chart_heatmap(df_sim: pd.DataFrame):
    pivot = df_sim.pivot_table(
        index="STEPSEQ", columns="설비", values="Workload", fill_value=0
    )
    fig = go.Figure(go.Heatmap(
        z=pivot.values,
        x=pivot.columns.tolist(),
        y=pivot.index.tolist(),
        colorscale=[
            [0.0,  "#0d1117"],
            [0.3,  "#00d4aa"],
            [0.7,  "#ffd93d"],
            [1.0,  "#ff6b6b"],
        ],
        showscale=True,
        colorbar=dict(tickfont=dict(color="#e6edf3")),
    ))
    fig.update_layout(
        **PLOTLY_LAYOUT,
        title="설비 × STEPSEQ Workload 히트맵",
        height=max(400, len(pivot) * 22),
        xaxis=dict(side="top"),
    )
    return fig


def chart_threshold_sweep(df: pd.DataFrame):
    """threshold 구간별 고부하 설비 수 & 블로킹 STEPSEQ 수 변화"""
    eq_total = df.groupby("설비")["Workload"].sum()
    min_w, max_w = eq_total.min(), eq_total.max()
    thresholds = np.linspace(min_w * 0.5, max_w * 1.1, 120)

    high_cnt, block_cnt, no_redirect = [], [], []
    for t in thresholds:
        sim = run_simulation(df, t)
        hi = (sim.groupby("설비")["설비총Workload"].first() > t).sum()
        bl = (sim["블로킹여부"] == "블로킹(저부하 이전 가능)").sum()
        nr = (sim["블로킹여부"] == "블로킹(이전 불가 – 주의)").sum()
        high_cnt.append(hi)
        block_cnt.append(bl)
        no_redirect.append(nr)

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(
        x=thresholds, y=high_cnt,
        name="고부하 설비 수", line=dict(color="#ff6b6b", width=2),
    ), secondary_y=False)
    fig.add_trace(go.Scatter(
        x=thresholds, y=block_cnt,
        name="블로킹 STEPSEQ 수 (이전 가능)", line=dict(color="#ffd93d", width=2),
    ), secondary_y=True)
    fig.add_trace(go.Scatter(
        x=thresholds, y=no_redirect,
        name="블로킹 STEPSEQ 수 (이전 불가)", line=dict(color="#ff9f43", width=2, dash="dot"),
    ), secondary_y=True)

    fig.update_layout(
        **PLOTLY_LAYOUT,
        title="Threshold 변화에 따른 고부하 설비·블로킹 STEPSEQ 추이",
        height=360,
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            orientation="h",
            yanchor="bottom", y=1.02,
        ),
        xaxis=dict(title="Threshold", gridcolor="#21262d"),
    )
    fig.update_yaxes(title_text="고부하 설비 수", secondary_y=False, gridcolor="#21262d")
    fig.update_yaxes(title_text="블로킹 STEPSEQ 수", secondary_y=True, showgrid=False)
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

        # Threshold 슬라이더
        eq_wl_total = df_raw.groupby("설비")["Workload"].sum()
        wl_min = float(eq_wl_total.min())
        wl_max = float(eq_wl_total.max())
        wl_mid = float(eq_wl_total.mean())

        st.markdown("**Workload Threshold**")
        threshold = st.slider(
            "기준값 (이 값 초과 → 고부하)",
            min_value=round(wl_min * 0.5, 1),
            max_value=round(wl_max * 1.2, 1),
            value=round(wl_mid, 1),
            step=1.0,
            format="%.1f",
        )

        st.markdown("---")
        st.markdown("**설비 상세 보기**")
        eq_list = sorted(df_raw["설비"].unique())
        selected_eq = st.selectbox("설비 선택", eq_list)

        st.markdown("---")
        st.caption("🔴 고부하 · 🟢 저부하 · 🟡 전용설비")

    # ── 시뮬레이션 실행 ──────────────────────────────────────────────────────
    df_sim = run_simulation(df_raw, threshold)
    eq_summary = df_sim.groupby("설비").agg(
        설비총Workload=("설비총Workload", "first"),
        부하구분=("부하구분", "first"),
        총STEPSEQ수=("STEPSEQ", "count"),
        블로킹대상수=("블로킹여부", lambda x: (x == "블로킹(저부하 이전 가능)").sum()),
        블로킹불가수=("블로킹여부", lambda x: (x == "블로킹(이전 불가 – 주의)").sum()),
        전용고정수=("블로킹여부", lambda x: (x == "블로킹불가(전용)").sum()),
    ).reset_index()

    high_eq = (eq_summary["부하구분"] == "고부하").sum()
    low_eq  = (eq_summary["부하구분"] == "저부하").sum()
    total_blocked  = df_sim["블로킹여부"].str.startswith("블로킹(").sum()
    no_redir = (df_sim["블로킹여부"] == "블로킹(이전 불가 – 주의)").sum()

    # ── 요약 지표 ────────────────────────────────────────────────────────────
    st.markdown('<div class="section-title">Summary</div>', unsafe_allow_html=True)
    c1, c2, c3, c4, c5 = st.columns(5)

    def metric_html(label, value, css_class=""):
        return f"""
        <div class="metric-card {css_class}">
          <div class="label">{label}</div>
          <div class="value">{value}</div>
        </div>"""

    with c1: st.markdown(metric_html("Threshold", f"{threshold:,.0f}"), unsafe_allow_html=True)
    with c2: st.markdown(metric_html("고부하 설비", f"{high_eq}대", "high-load"), unsafe_allow_html=True)
    with c3: st.markdown(metric_html("저부하 설비", f"{low_eq}대", "low-load"), unsafe_allow_html=True)
    with c4: st.markdown(metric_html("블로킹 STEP", f"{total_blocked}건"), unsafe_allow_html=True)
    with c5: st.markdown(metric_html("이전불가(주의)", f"{no_redir}건", "high-load" if no_redir > 0 else ""), unsafe_allow_html=True)

    # ── 차트 영역 ─────────────────────────────────────────────────────────────
    st.markdown('<div class="section-title">설비별 Workload 현황</div>', unsafe_allow_html=True)
    eq_wl_df = eq_summary[["설비", "설비총Workload"]].copy()
    st.plotly_chart(chart_eq_workload(eq_wl_df, threshold), use_container_width=True)

    col_l, col_r = st.columns([1, 1])
    with col_l:
        st.markdown('<div class="section-title">Threshold Sweep 분석</div>', unsafe_allow_html=True)
        st.plotly_chart(chart_threshold_sweep(df_raw), use_container_width=True)
    with col_r:
        st.markdown(f'<div class="section-title">{selected_eq} 상세 분석</div>', unsafe_allow_html=True)
        st.plotly_chart(chart_step_workload(df_sim, selected_eq), use_container_width=True)

    st.markdown('<div class="section-title">Workload 히트맵 (설비 × STEPSEQ)</div>', unsafe_allow_html=True)
    st.plotly_chart(chart_heatmap(df_raw), use_container_width=True)

    # ── 설비 요약 테이블 ──────────────────────────────────────────────────────
    st.markdown('<div class="section-title">설비 요약</div>', unsafe_allow_html=True)

    def style_row(row):
        if row["부하구분"] == "고부하":
            return ["background-color: rgba(255,107,107,0.08)"] * len(row)
        return ["background-color: rgba(0,212,170,0.05)"] * len(row)

    styled = eq_summary.style.apply(style_row, axis=1).format({
        "설비총Workload": "{:,.1f}",
    })
    st.dataframe(styled, use_container_width=True, hide_index=True)

    # ── 블로킹 대상 STEPSEQ 상세 테이블 ────────────────────────────────────
    st.markdown('<div class="section-title">블로킹 대상 STEPSEQ 상세</div>', unsafe_allow_html=True)

    tab1, tab2, tab3 = st.tabs([
        "🔴 블로킹 (이전 가능)",
        "⚠️ 블로킹 (이전 불가)",
        "🟡 전용설비 고정",
    ])

    cols_show = ["설비", "STEPSEQ", "진행WIP", "대기WIP", "총WIP", "ST(hr)", "Workload", "전용설비여부"]

    with tab1:
        df_t1 = df_sim[df_sim["블로킹여부"] == "블로킹(저부하 이전 가능)"][cols_show].sort_values("Workload", ascending=False)
        if df_t1.empty:
            st.success("블로킹(이전 가능) 대상 STEPSEQ 없음")
        else:
            st.dataframe(df_t1, use_container_width=True, hide_index=True)

    with tab2:
        df_t2 = df_sim[df_sim["블로킹여부"] == "블로킹(이전 불가 – 주의)"][cols_show].sort_values("Workload", ascending=False)
        if df_t2.empty:
            st.success("블로킹(이전 불가) 대상 STEPSEQ 없음")
        else:
            st.warning(f"⚠️ {len(df_t2)}건의 STEPSEQ가 저부하 설비에 없습니다. 블로킹 전 확인 필요!")
            st.dataframe(df_t2, use_container_width=True, hide_index=True)

    with tab3:
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
