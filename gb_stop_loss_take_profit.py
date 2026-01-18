# gb_stop_loss_take_profit.py
import pandas as pd
import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score

class GBSLTPModel:
    """基于梯度提升树的止盈止损预测模型"""
    def __init__(self, random_state=42):
        # 初始化模型和标准化器
        self.scaler = StandardScaler()
        self.tp_model = GradientBoostingClassifier(
            n_estimators=100,
            max_depth=5,
            learning_rate=0.1,
            random_state=random_state
        )
        self.sl_model = GradientBoostingClassifier(
            n_estimators=100,
            max_depth=5,
            learning_rate=0.1,
            random_state=random_state
        )
        self.tp_trained = False
        self.sl_trained = False

    def extract_features(self, df):
        """提取止盈止损模型特征（比交易信号特征更丰富）"""
        df = df.copy()
        # 基础行情特征
        df['ret'] = (df['close'] - df['open']) / df['open']
        df['range'] = (df['high'] - df['low']) / df['open']
        df['vol_ratio'] = df['vol'] / df['vol'].rolling(20).mean()
        # 均线特征
        df['ma5'] = df['close'].rolling(5).mean()
        df['ma20'] = df['close'].rolling(20).mean()
        df['ma_ratio'] = df['ma5'] / df['ma20']
        # 布林带特征
        df['bb_mid'] = df['close'].rolling(20).mean()
        df['bb_std'] = df['close'].rolling(20).std()
        df['bb_upper'] = df['bb_mid'] + 2 * df['bb_std']
        df['bb_lower'] = df['bb_mid'] - 2 * df['bb_std']
        df['bb_pos'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])
        # RSI特征
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        # 去除空值
        df = df.dropna()
        return df

    def create_labels(self, df, tp_threshold=0.01, sl_threshold=0.01):
        """
        创建止盈止损标签
        tp_threshold: 止盈阈值（上涨幅度≥该值标记为1）
        sl_threshold: 止损阈值（下跌幅度≥该值标记为1）
        """
        df = df.copy()
        # 计算未来收益率
        df['future_ret'] = df['close'].shift(-1) / df['close'] - 1
        # 止盈标签：未来上涨≥tp_threshold → 1
        df['tp_label'] = (df['future_ret'] >= tp_threshold).astype(int)
        # 止损标签：未来下跌≥sl_threshold → 1
        df['sl_label'] = (df['future_ret'] <= -sl_threshold).astype(int)
        return df

    def train(self, df, tp_threshold=0.01, sl_threshold=0.01):
        """训练止盈止损模型"""
        # 提取特征和标签
        df = self.extract_features(df)
        df = self.create_labels(df, tp_threshold, sl_threshold)
        if len(df) < 50:
            print("❌ 止盈止损模型训练样本不足（需≥50条）")
            return

        features = ['ret', 'range', 'vol_ratio', 'ma_ratio', 'bb_pos', 'rsi']
        X = df[features]
        y_tp = df['tp_label']
        y_sl = df['sl_label']

        # 标准化特征
        X_scaled = self.scaler.fit_transform(X)

        # 划分训练集和测试集
        X_train, X_test, y_tp_train, y_tp_test = train_test_split(X_scaled, y_tp, test_size=0.2, random_state=42)
        _, _, y_sl_train, y_sl_test = train_test_split(X_scaled, y_sl, test_size=0.2, random_state=42)

        # 训练模型
        self.tp_model.fit(X_train, y_tp_train)
        self.sl_model.fit(X_train, y_sl_train)

        # 验证模型准确率
        tp_pred = self.tp_model.predict(X_test)
        sl_pred = self.sl_model.predict(X_test)
        tp_acc = accuracy_score(y_tp_test, tp_pred)
        sl_acc = accuracy_score(y_sl_test, sl_pred)

        self.tp_trained = True
        self.sl_trained = True
        print(f"✅ 止盈止损模型训练完成 | 止盈准确率:{tp_acc:.2%} | 止损准确率:{sl_acc:.2%}")

    def predict(self, df):
        """预测当前K线的止盈/止损概率"""
        if not self.tp_trained or not self.sl_trained:
            print("❌ 止盈止损模型未训练，无法预测")
            return 0.0, 0.0

        # 提取最新一条数据的特征
        df = self.extract_features(df)
        if df.empty:
            return 0.0, 0.0
        latest = df.iloc[-1][['ret', 'range', 'vol_ratio', 'ma_ratio', 'bb_pos', 'rsi']].values.reshape(1, -1)
        latest_scaled = self.scaler.transform(latest)

        # 预测概率（取正类概率）
        tp_prob = self.tp_model.predict_proba(latest_scaled)[0][1]
        sl_prob = self.sl_model.predict_proba(latest_scaled)[0][1]
        return tp_prob, sl_prob