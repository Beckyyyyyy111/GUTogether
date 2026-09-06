# Gut Sound + HR/EDA Sync Recorder

网页工具:点击 Play,倒计时 3 秒后播放 `OpenGut/Participant_Gut_Sounds/Selected_Sounds` 里选中的肠道声音文件,同时从真实 EmotiBit 设备的 LSL `HR`/`EDA` 流实时采集数据,并把采集到的时间戳校正到"播放开始"那一刻(t=0)。播放结束后,三路数据(肠道声音波形、HR、EDA)按同一条时间轴保存到 `Final/` 下的一个新文件夹里。

实验分两个 Stage,网页上用单选按钮切换:

- **Stage 1(只听)**:浏览器播放音频(`<audio>` 标签),流程就是上面说的这套。
- **Stage 2(听 + 看实时振幅)**:浏览器同样播放音频,同时用 Web Audio API(`AnalyserNode` 接在播放的 `<audio>` 元素上)把当前播放位置的波形实时画到页面上的一个 canvas 里,跟随播放同步滚动显示振幅,不需要任何外部程序。

## 原理 / 时间对齐怎么做的

- 复用了 `HR-EDA-Time-Alignment` 项目里的 `lsl_receiver.py`(`pylsl` 的 `StreamInlet.time_correction()` 校正每个样本时间戳到本机统一时钟)、`buffers.py`、`cleaning.py`,原样拷贝到 `website/backend/`。
- 点击 Play 后,后端先倒计时 3 秒,倒计时结束的瞬间记录 `pylsl.local_clock()` 作为 `t=0` 锚点,然后才通知前端真正开始播放音频 —— 这样"音频开始播放"和"HR/EDA 记录起点"是同一个时间点,而不是靠浏览器/服务器两边时钟去凑。
- 之后每个 LSL 样本到达时的校正时间戳减去这个锚点,就是这份录音里的"相对时间(秒)",与音频文件的 `Time (s)` 轴直接对应。
- 播放时长由服务器直接读取 wav 文件本身的时长决定(而不是等浏览器上报),所以录制窗口精确覆盖整段音频。

## 目录结构

```
website/
  backend/
    server.py           FastAPI 应用:声音列表、音频/结果静态文件服务、/ws 会话控制、保存逻辑
    lsl_receiver.py       (从 HR-EDA-Time-Alignment 拷贝) LSL 发现 + time_correction
    buffers.py             (拷贝) 线程安全滚动缓冲区
    cleaning.py            (拷贝) HR/EDA 异常值剔除 + 平滑
    session.py              一次录制会话的样本收集器
    plotting.py              生成四联图 PNG(波形 + 频谱图 + HR + EDA,共用时间轴;频谱图算法和 OpenGut 自己的 "Processed Output" 一致,librosa STFT -> dB)
    requirements.txt
  frontend/
    index.html, app.js, styles.css   纯静态页面,无需构建
Final/
  <时间戳>_<声音文件名>_stage<1|2>/
    combined_long.csv       长表:relative_time_s, signal(HR/EDA), raw_value, cleaned_value
    combined_summary.png    四联图(波形+频谱图+HR+EDA)
    audio.wav                当时播放的那份音频副本
    session_meta.json        起止时间、stage、样本数等元信息
```

## 运行

```powershell
cd website\backend
..\..\.venv\Scripts\python.exe -m uvicorn server:app --port 8000
```

然后浏览器打开 `http://localhost:8000/`。

**前提**:EmotiBit Oscilloscope 要打开并把 "Send data via" 切成 "LSL"(参考 `HR-EDA-Time-Alignment` 项目的说明),否则右上角 HR/EDA 状态会一直是 "not found"。声音文件下拉列表读的是 `D:\AAAAAAAA\OpenGut\Participant_Gut_Sounds\Selected_Sounds` 里的 `.wav` 文件,往那个文件夹加文件不用重启服务,刷新页面即可。

## 已验证

用 `HR-EDA-Time-Alignment/tools/mock_emotibit_lsl.py` + 一个真实 EmotiBit 的 LSL 流跑通过完整流程:倒计时 → 播放 → 实时 tick 显示 → 结束后 CSV/PNG/audio.wav/meta 正确写入 `Final/`。测试时设备未实际佩戴,所以 EDA 原始值在生理范围之外被 `cleaning.py` 判定无效(HR 同理长期无锁定)—— 这属于既有清洗逻辑的正常行为("宁可留空也不编造"),真实佩戴时会正常出现在图上。

## 已知限制

- 和 `HR-EDA-Time-Alignment` 一样,假设网络上只有一台 EmotiBit 的 LSL 流;发现多个同名流时用最先发现的那个。
- 同一时间只支持一个录制会话(单实验者、单设备场景),第二个浏览器标签页点 Play 会收到"已经在录制"的提示。
- `combined_summary.png` 里的 HR/EDA 曲线画的是 cleaned_value(剔除异常值后的),CSV 里 raw_value 全部保留,不会丢数据。
- Stage 2 的振幅可视化依赖 Web Audio API 的 `AudioContext`,首次使用需要浏览器已经有过一次用户交互(点 Play 本身就算),否则部分浏览器会把它挂起;代码里已经在点击 Play 时同步创建/恢复 `AudioContext` 来规避这个限制。
