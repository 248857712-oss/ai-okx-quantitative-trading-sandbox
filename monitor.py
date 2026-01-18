import streamlit as st
import pandas as pd
import plotly.express as px
import os
import time
from trade_utils import load_trade_records

# 页面配置
st.set_page_config(
    page_title="OKX量化策略监控面板",
    page_icon="📈",
    layout="wide"
)

st.title("📈 OKX 量化策略实时监控面板")

# ================= 1. 读取交易记录 =================
trades_df = load_trade_records("./trades.csv")

# 分两列展示
col1, col2 = st.columns(2)

with col1:
    st.subheader("📋 交易记录")
    if trades_df.empty:
        st.info("暂无交易记录，请先运行策略")
    else:
        # 显示表格
        st.dataframe(
            trades_df,
            column_config={
                "time": st.column_config.DatetimeColumn("时间", format="YYYY-MM-DD HH:mm:ss"),
                "type": st.column_config.SelectboxColumn("交易类型", options=["开多", "平仓"]),
                "price": st.column_config.NumberColumn("价格 (USDT)", format="%.2f"),
                "size": st.column_config.NumberColumn("持仓张数", format="%.6f"),
                "profit": st.column_config.NumberColumn("盈亏 (USDT)", format="%.2f"),
                "order_id": "订单ID"
            },
            use_container_width=True
        )

with col2:
    st.subheader("💰 盈亏统计")
    if trades_df.empty:
        total_profit = 0.0
        trade_count = 0
    else:
        total_profit = trades_df["profit"].sum()
        trade_count = len(trades_df)

    # 显示关键指标
    st.metric("累计盈亏", f"{total_profit:.2f} USDT")
    st.metric("总交易次数", trade_count)
    st.metric("单笔最大盈利", f"{trades_df['profit'].max():.2f} USDT" if trade_count > 0 else "0.00 USDT")
    st.metric("单笔最大亏损", f"{trades_df['profit'].min():.2f} USDT" if trade_count > 0 else "0.00 USDT")

# ================= 2. 盈亏走势图 =================
st.subheader("📊 盈亏走势")
if not trades_df.empty:
    # 按时间排序
    trades_df["time"] = pd.to_datetime(trades_df["time"])
    trades_df = trades_df.sort_values("time")
    # 计算累计盈亏
    trades_df["累计盈亏"] = trades_df["profit"].cumsum()

    # 画图
    fig = px.line(
        trades_df,
        x="time",
        y="累计盈亏",
        title="累计盈亏变化曲线",
        labels={"time": "时间", "累计盈亏": "累计盈亏 (USDT)"},
        line_shape="spline",
        color_discrete_sequence=["#1E90FF"]
    )
    fig.update_layout(height=400)
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("暂无交易数据，无法生成走势图")

# ================= 3. 最新运行日志 =================
st.subheader("📜 最新运行日志")
log_dir = "./logs"
if os.path.exists(log_dir):
    # 获取最新的日志文件
    log_files = [f for f in os.listdir(log_dir) if f.startswith("okx_strategy_")]
    if log_files:
        latest_log_file = max(log_files)
        log_path = os.path.join(log_dir, latest_log_file)

        # 读取最后 2000 字符（避免加载过大）
        with open(log_path, "r", encoding="utf-8") as f:
            log_content = f.read()[-2000:]

        st.text_area("日志内容", log_content, height=300)
    else:
        st.info("暂无日志文件")
else:
    st.info("日志目录不存在，请先运行策略生成日志")

# ================= 4. 自动刷新 =================
st.sidebar.button("🔄 手动刷新", on_click=lambda: st.rerun())
st.sidebar.write("自动刷新间隔：30秒")
st_autorefresh = st.sidebar.checkbox("开启自动刷新", value=True)

if st_autorefresh:
    time.sleep(30)  # 等待30秒
    st.rerun()