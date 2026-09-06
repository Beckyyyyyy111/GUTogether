# EmotiBit HR / EDA Viewer

实时显示单台 EmotiBit 的心率（HR）和皮肤电（EDA）信号，对每个样本的时间戳做 LSL **time alignment**（时间校正）。支持实时查看 + 离线整理两种模式。

## 原理

EmotiBit Oscilloscope 通过 LSL 输出名为 `HR` 和 `EDA` 的流（默认 `lslOutputSettings.json` 已经配置好，不用改），但 **LSL 输出默认是关闭的**——Oscilloscope 界面顶部有一个 "Send data via" 按钮，默认是 "None"，必须手动点开切换成 "LSL"，数据才会真正发送到网络上。

本软件用 `pylsl` 订阅这些流，并且：
- 用每个 `StreamInlet.time_correction()` 把 Oscilloscope 发布数据时打的时间戳，校正到**本机统一的时钟基准**上 —— 这是"time alignment"的核心机制，即使 Oscilloscope 和本软件跑在不同电脑上也一样有效
- 实时滚动绘图（HR、EDA 各一张图，横轴是经过时间 m:ss）
- 可选录制成对齐后的 CSV

## 安装

```powershell
python -m venv .venv
.venv\Scripts\pip install -e .
```

需要 Python 3.10+。

## 准备 EmotiBit 的 LSL 数据源

1. 打开 EmotiBit Oscilloscope，连接你的 EmotiBit。
2. **点击界面顶部的 "Send data via: None" 按钮，切换成 "LSL"**——这一步很容易漏掉，不做的话本软件收不到任何数据。
3. Oscilloscope 和运行本软件的电脑需要在**同一个网络**（LSL 基于本地网络的组播发现）。
4. HR、EDA 数值需要设备正常采集一段时间才会锁定（比如需要皮肤接触良好），如果 Oscilloscope 里 HR/EDA 一直是平的直线，先检查佩戴和信号质量。

## 实时查看（Live mode）

```powershell
.venv\Scripts\dual-emotibit-viewer.exe
```

- 软件会自动发现网络上的 `HR`/`EDA` 流并开始画图
- 右侧面板显示每个信号的连接状态（多久没收到新数据、对应的 EmotiBit `source_id`）
- "Window (seconds)" 控制滚动窗口长度
- 点击 "Start Recording" 会把对齐后的数据实时写入 `data/recordings/<时间戳>_aligned.csv`（长表格式：`lsl_corrected_timestamp, signal, value`，文件头有 `anchor_unix_time` 等注释行，可用来把时间戳换算成真实墙钟时间）

没有硬件也可以先跑通整个链路测试一下：

```powershell
.venv\Scripts\python.exe tools\mock_emotibit_lsl.py
```

这个脚本会模拟一台 EmotiBit 发送 HR/EDA 数据，跟真实设备的协议完全一样，可以直接用 `dual-emotibit-viewer` 连上看效果。

### 录制完之后怎么看

```powershell
.venv\Scripts\emotibit-view-recording.exe data\recordings\2026-07-05_18-30-00_aligned.csv
```

会生成 `..._aligned_wide.csv`：按统一时间网格重采样、HR 和 EDA 各一列、还原出真实 `datetime`，可以直接拖进 Excel 或 pandas 分析。

## 离线整理（Offline mode）

如果你是先用 Oscilloscope 录制到 SD 卡，再用 EmotiBitDataParser 解析出 CSV（`_HR.csv`, `_EA.csv`），可以用这个命令把两者合并成统一时间轴：

```powershell
.venv\Scripts\emotibit-combine-csv.exe --hr path\to\_HR.csv --eda path\to\_EA.csv --out combined
```

会生成：
- `combined_long.csv`：长表格式，所有样本一行一条
- `combined_wide.csv`：重采样到统一时间网格（默认 15Hz，可用 `--resample-hz` 改），HR、EDA 各一列，方便直接用 Excel 或 pandas 分析

## 项目结构

```
src/dual_emotibit_viewer/
  lsl_receiver.py             # 发现+订阅LSL流(HR/EDA), time_correction对齐
  buffers.py                   # 线程安全的滚动缓冲区
  recorder.py                  # 实时录制对齐后的CSV
  app.py                        # pyqtgraph GUI 主程序
  offline/combine_csv.py        # 离线合并 DataParser 导出的HR/EDA CSV
  offline/view_recording.py     # 把实时录制的长表CSV转成宽表
tools/
  mock_emotibit_lsl.py          # 模拟一台设备的LSL数据，无需硬件测试
  test_receiver_headless.py      # receiver的无界面冒烟测试
```

## 已知限制

- 本软件假设网络上只有一台 EmotiBit 的 LSL 流；如果检测到同一信号有多个来源，会用最先发现的那个并打印警告
- EmotiBit 的 WiFi 只支持 2.4GHz 频段（设备本身的限制，与本软件无关）
- 离线合并工具假设输入 CSV 里有 `EpochTimestamp`（找不到则退回 `EmotiBitTimestamp`/`LocalTimestamp`），具体列名以你所用 DataParser 版本实际导出的为准
