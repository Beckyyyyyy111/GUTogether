# 更新日志

记录跨项目的代码改动,方便后续追溯迭代历史。

## 2026-08-19

### OpenGut-Cuda：肠道声音回放片段偏移量调整

- **项目**: `OpenGut-Cuda/OpenGUT-main/OpenGUT-main/Software`
- **改动文件**:
  - [audio_moments.py](OpenGut-Cuda/OpenGUT-main/OpenGUT-main/Software/audio_moments.py)
  - [scripts/build_playback_clip.py](OpenGut-Cuda/OpenGUT-main/OpenGUT-main/Software/scripts/build_playback_clip.py)
- **改动内容**: 三个回放片段(moment)中,第三个片段(`eating_end`,"near end of eating")原本是从录音结尾往前推 **3 分钟(180 秒)** 开始截取 60 秒(即倒数第3分钟到倒数第2分钟)。现改为从录音结尾往前推 **6 分钟(360 秒)** 开始截取 60 秒(即倒数第6分钟到倒数第5分钟)。
- **具体修改**: `DEFAULT_EATING_END_OFFSET` 常量由 `180.0` 改为 `360.0`,并同步更新了相关注释和 CLI 帮助文本。

### GutSound-HR-EDA-Sync：网站 Stage 2 实时波形可视化放大

- **项目**: `GutSound-HR-EDA-Sync/website/frontend`
- **改动文件**: [app.js](GutSound-HR-EDA-Sync/website/frontend/app.js)(`drawAmplitude()` 函数,约第 74-83 行)
- **背景**: Stage 2("listen + watch live amplitude")页面给 participant 展示的实时波形几乎是一条贴着画布顶部的平线,肠道声音较安静时波动看不清楚。原因是原代码把 Web Audio API 返回的字节值(以 128 为静音中心)直接按画布高度线性映射,没有以中线为基准,也没有增益放大。
- **改动内容**: 波形改为以画布中线为基准上下摆动,并乘以增益系数 `gain = 4` 放大波动幅度,同时对超出画布范围的值做裁剪。该值是纯前端渲染逻辑,刷新页面即可生效,无需重启后端。
- **后续可调**: 如果 4 倍增益效果不够明显或过于夸张,可以调整 `app.js` 里的 `gain` 数值。
