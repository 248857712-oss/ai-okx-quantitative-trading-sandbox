# 主目录文件大致组成
```
量化策略/
├── Data 主要文件
├── logs 日志文件，交易日志会存储在这里
└── model-test 该文件专门用于模型调参，具体用法请参考该目录下的README.md    
```
# 使用说明
1.Data/Entry/config.json中接入自己的okxapi，代理地址(如果没有代理地址可以直接空出来，注:国内无代理一般进不去)  
2.启动Data/Entry下的run_strategy.py,即可开始自动交易
# Config配置
以下是config配置简介
```
leverage：杠杆倍数
position_ratio: 每次开仓比例
lr_weight: 逻辑回归权重
rf_weight: 森林模型权重
vote_threshold: 权重开仓阈值
tp_prob_threshold: 设置这个值（止盈概率阈值），判断是否超过该止盈概率
sl_prob_threshold: 止损概率阈值，同上
cycle_interval: 每次执行周期（单位：s）
boll_window: 布林窗口值
boll_dev: 布林标准差
min_profit_threshold: 最小止盈阈值
target_profit_ratio: 目标收益率
min_loss_threshold: 最小止损阈值
```
# 一些问题
默认是合约交易，请不要修改，可能会出现一些未知错误
# 监控面板
该项目提供了一个监控面板,位于Data/Monitor/monitor.py  
打开方式：  
1.cmd输入 **你自己的路径\量化策略\.venv\Scripts\activate**进行虚拟化  
2.继续输入cd **你自己的路径\量化策略\Data\Monitor**  
3.运行命令**streamlit run monitor.py**如果出现
```
  You can now view your Streamlit app in your browser.

  Local URL: http://localhost:xxxx
  Network URL: http://xxx.xx.x.x:xxxx
```
和跳转网页便成功启动
