"""
TouchDesigner River Ocean Setup Script
======================================
在 TouchDesigner 中:
1. 创建一个 Text DAT，把这个脚本粘贴进去
2. 右键 Text DAT → Run Script
3. 网络会自动搭建完成

信号链:
  Audio File In (Gut Sounds/*.wav) → Script CHOP（自定义振幅包络提取+自动校准+静音计时器） → Null
                                                                                              ↓
                                                            ┌──────────────┴──────────────┐
                                                gut_history_tex (Script TOP，滚动历史带)   uStillness (全局)
                                                            ↓
                                                  GLSL TOP river_ocean（按屏幕横向位置采样历史带）

关于振幅提取为什么不用 TD 自带的 Analyze(RMS) + Math(增益) + Lag(平滑) 组合：
  - Analyze CHOP 的 RMS 是对每次 cook 拿到的一整段音频样本做"整窗平均"，没有
    攻击/释放（attack/release）区分，肠鸣音这种短促的爆发音容易被平均糊掉。
  - 固定 Gain 对不同录音的音量差异极其敏感，换一个 wav 文件基本都要重新调。
  - Lag CHOP 的平滑是逐帧（跟着 timeline/cook rate 走）而不是逐音频采样点，
    比一帧还短的瞬态响应会被打折扣。
  这里改成 Script CHOP，自己写逐采样点的整流 + 非对称指数包络跟随（attack/
  release 各自独立时间常数），见下方 gut_envelope_script 里的 Python 代码。

⚠️ 关于一个已修复的坑：Script CHOP 的自定义参数（Attacksec/Releasesec/...）
   是由回调代码里的 onSetupParameters 建立的，而它只在这个 CHOP 真正 cook
   过一次之后才会出现在 scriptOp.par 上。如果本脚本创建完 Script CHOP 后
   紧接着同步赋值 env_chop.par.Attacksec = ...，此时参数往往还不存在，会直接
   抛 AttributeError 把整个建网脚本中断在半路（这也是之前"网络只搭了一半、
   看不到水面/冰川"的原因）。现在改成把默认值直接写死进生成的回调脚本文本
   里，onCook 只在自定义参数确实存在时才读它、读不到就用写死的默认值兜底，
   不再依赖外层脚本能同步设置成功。

⚠️ 关于噪声门限/参考电平从"手动写死两个固定数字"改成"自动校准"：
   最早用固定的两个数字把响度线性映射到 0~1 的 activity。问题是同一份
   Gut Sounds 录音，不同片段的响度差异可以差出很多倍——写死的数字不可能同时
   适配这么大的动态范围，一会儿 activity 卡在0，一会儿又卡在1，得靠人工
   反复读数、改代码、重新运行脚本才能勉强凑对某一段。
   现在改成让 Script CHOP 自己在播放过程中持续跟踪"最近观察到的最安静振幅"
   （floor，作为动态噪声门限）和"最近观察到的最响振幅"（peak，作为动态参考
   振幅），两者都做成非对称的跟随器：floor 一旦观察到更安静的片段就立刻跟
   着降下去，持续偏响的话又会缓慢地把它抬高；peak 一旦观察到更响的片段就
   立刻跟着升上去，安静下来之后缓慢回落。activity 用这两个实时跟踪到的值
   做归一化，不再需要手动指定固定数字。

⚠️ 关于自动校准为什么改成在"线性振幅域"而不是"dB域"里算：
   上一版把线性包络先转成 dB（对数域，对应人耳感知的"音量/响度"）再做自动
   校准和归一化——这表达的其实是"听起来有多响"，不是"振幅本身有多大"。
   我们想表达的是"振幅大小 -> 波浪振幅"，不是"音量大小 -> 波浪振幅"，这两者
   不是一回事：dB 域会把响度差异压缩/拉伸成更符合人耳感知的曲线，跟原始
   振幅并不成正比。之前选 dB 域是因为固定 Gain + 线性域时，安静段的振幅
   差异小到几乎被钳位吃掉、分辨不出来；但现在有了自动校准（floor/peak
   实时跟踪，且都是相对当前录音动态范围的比例关系），这个顾虑已经不存在了，
   所以改成直接在线性振幅上做 floor/peak 跟踪和 activity 归一化，不再经过
   dB 转换。dB 只保留成一个纯调试/显示用的旁路通道（env_db，图表上看更
   直观），不参与 activity 的计算。

⚠️ 关于新增的"视觉平滑"（activity_visual）：
   activity 本身的起音/释音时间常数（ENV_ATTACK_SEC=0.15s、ENV_RELEASE_SEC=
   0.06s）设得很快，是为了准确跟踪肠鸣音一阵一阵的爆发；但这个值原来是
   直接、逐帧喂给 shader 去改变波浪振幅的，没有额外平滑，肠鸣音一阵阵地响，
   水面也跟着一阵阵地"抽搐"（平静/波动来回快切），看起来很难受。
   现在加一层单独的、慢得多的平滑，套在 activity 上面得到 activity_visual，
   真正喂给 shader（uGutActivity）的是这个更从容的版本；"有没有声音"的判断
   （静音计时器、噪声门限）仍然用未经平滑的原始 activity，保持灵敏，不受这层
   视觉平滑影响。这层平滑起落用两个独立时间常数（VISUAL_ATTACK_SEC=2.4s、
   VISUAL_RELEASE_SEC=1.0s），两个方向反复实测调出来的：波动->平静1秒效果
   最好，太慢的话（比如2秒）赶上肠鸣音爆发间隔短于2秒时会落不完就被顶上去，
   平静水面几乎不出现；平静->波动这边依次试过0.6s/1.0s/1.8s/3.0s，1.8s以下
   偏快、3.0s又偏长，最后落在2.4s。两个方向的诉求不一样，所以拆开、不共用
   一个数字。

⚠️ 关于"历史带"流动效果（最新加的，取代了"全屏统一淡入淡出"）：
   前面那套"视觉平滑"解决的是时间上的抽搐/来回切换，但本质上还是全屏共用
   一个数值——不管画面哪个位置，同一时刻水面振幅都一样，所以再怎么调平滑
   时长，观感上还是"整块画面同时变"，而不是真正的"流动"，反馈是这样看起来
   不自然、很别扭。
   现在换一种做法：不再让 uGutActivity 是一个全局标量，而是把最近
   HISTORY_SECONDS 秒（默认8秒）的 activity_visual 存成一条随时间持续滚动
   的"历史带"，接回 river_ocean 的输入0。shader 里不再读一个全局数值，而是
   按这个像素在屏幕上的横向位置去这条历史带上采样"当地"该有的活跃度——
   这样画面里能同时看到"刚安静下来的一段"和"更早之前有声音的一段"依次
   排开，历史带自己持续滚动，画面看起来就是自然的流动，而不是全屏同步
   切换。HISTORY_FLOW_RIGHT_TO_LEFT 控制新的声音从屏幕哪一侧进来（True=
   从右边进来往左流，False=从左边进来往右流）。

   ⚠️ 已修复的坑：一开始历史带是直接把 activity_visual 原样写进缓冲区，没
   做任何横向平滑——结果一段很短暂的安静会在画面上变成一道边缘锋利、笔直
   竖穿整个画面的"平静走廊"，跟旁边波浪毫无过渡，很不自然。加了
   HISTORY_BLUR_TEXELS 做横向滑动平均模糊之后好了很多，但肠鸣音单次爆发
   通常只有1~2秒，摊到当时12秒的窗口里还是太窄，模糊完还是会显得像一根
   "孤岛"夹在两侧安静中间，很突兀。后来把 HISTORY_SECONDS 从12秒缩短到
   8秒（让同样长度的爆发占到更大的画面比例），BLUR_TEXELS 也从30格加到
   55格（配合更宽的过渡），两个一起调之后，短促的爆发也能呈现成宽阔缓和
   的过渡区，而不是突兀的窄柱子。

   ⚠️ 已尝试又放弃的方案：加过一个"释放保持"（activity 掉下去之后先原地
   不动等 VISUAL_RELEASE_HOLD_SEC 秒才开始 release 衰减，想用来盖住两次
   爆发之间的短暂间隙），结果"波动->平静"这个方向反而变得明显比"平静->
   波动"难看——平静->波动是一条连续变化斜率的指数曲线，平滑爬升；而加了
   保持之后，波动->平静变成先有一段"原地不动的平台"，平台结束才开始衰减，
   形成一个"平台突然接上下降曲线"的折角，历史带模糊也盖不住，看起来是道
   硬边。试过把 BLUR_TEXELS 加大到140格去盖住这个折角，效果有改善但还是
   不如直接不产生折角。最后决定把"释放保持"整个撤掉，activity_visual 的
   下降沿改回最早、最简单的样子：activity 一低于当前值就直接按
   VISUAL_RELEASE_SEC 开始指数衰减，不再有平台，曲线连续光滑，跟上升沿
   对称。BLUR_TEXELS 也跟着改回55——加到140是专门为了盖那个折角，折角
   源头没了，就不需要那么宽的模糊了（模糊太宽会让平静->波动这边也变得
   过于拖沓，属于不必要的副作用）。

   ⚠️ 关于新增的"状态锁"（保证任意时刻画面里最多只有一次转折）：
   前面几轮修复让单次转折看起来顺滑了，但历史带毕竟是"如实记录"——肠鸣音
   只要在 HISTORY_SECONDS 窗口内响了两次以上，画面上就会同时出现两次以上
   的转折（比如"平静夹一段wave又夹平静"或者"wave越来越碎的多段"），看起来
   很乱，反馈是希望任何时刻画面上最多只有一次转折（纯平静/纯wave/单次
   平静->wave/单次wave->平静之一）。
   这靠调平滑参数解决不了——只要还是逐帧记录连续值，两次真实的声音突发
   就必然对应两次转折。改成往历史带里写的不再是连续的 activity_visual，
   而是 gut_history_tex 回调里自己维护的一个"平静/wave"二值状态：
   activity_visual 超过 STATE_THRESHOLD 才提议切到 wave，低于才提议切回
   平静，但提议不会立刻生效——必须离上一次真正切换至少过了
   STATE_MIN_DWELL_SEC 秒才允许再切。只要 STATE_MIN_DWELL_SEC >=
   HISTORY_SECONDS，两次切换的间隔就天然不会短于画面能同时看到的时间跨度，
   数学上保证了任意时刻最多一条转折带。默认让 STATE_MIN_DWELL_SEC 直接等于
   HISTORY_SECONDS（6秒）。代价是刻意的：状态切换之后的这段时间里，画面
   不会实时跟着每一次声音起伏抖动了（比如刚变wave后面马上安静了，画面还是
   会继续wave一段时间），用响应的实时性换画面的干净。

   ⚠️ 已修复的坑：切到平静这个方向一开始跟切到wave用的是同一条逻辑——
   activity_visual 一低于 STATE_THRESHOLD 就立刻提议切回平静（只要过了
   STATE_MIN_DWELL_SEC 就真的切）。问题是声音只要短暂停顿一下（哪怕零点几
   秒的间隙），只要正好卡在允许再切的那一刻，就会被判定成"该平静了"——
   结果水面平静下来的时候，实际上旁边的声音根本没停，很难看，像是水面
   "自说自话"跟真实声音对不上。现在给"切到平静"单独加一道确认：
   activity_visual 必须连续低于阈值满 STATE_CALM_CONFIRM_SEC 秒（默认2秒），
   才会真的提议切回平静；"切到wave"这个方向不受影响，还是一超过阈值就立刻
   提议（水面变热闹应该快，变平静才需要多确认一下"是不是真的没声音了"）。

   ⚠️ 已放弃的方案："Script CHOP（滚动缓冲区）→ CHOP to TOP（转成纹理）"
   两步走的做法改了三轮都没调通——连线创建不生效、显式设CHOP引用参数也
   不报错但纹理还是空白，没有真实TD环境没法再继续猜它的具体接口。
   改成一个 gut_history_tex（Script TOP）直接搞定：在回调里维护同样的滚动
   缓冲区，再用 numpy 拼出一张 1 x HISTORY_TEXELS 的图像，调
   scriptOp.copyNumpyArray() 直接写成纹理——这是 TD 官方示例里很标准的
   Script TOP 写法，不再依赖 CHOP↔TOP 之间那层不确定的转换。

   ⚠️ 已修复的坑（改了三次才搞定）：gut_envelope 的输入是实时播放的音频
   （gut_audio_file），TD 会把整条下游链自动锁进 Time Slice 模式，这个模式下
   不允许脚本自己改 numSamples/rate，Textport 会一直刷 "tdWarning: Editing
   numSamples is not supported in Time Slice mode"。
   前两次分别试了 .par.timeslice = False 和 CHOP.isTimeSlice = False 想关掉
   这个模式，都没用——Python 允许给对象挂一个不存在的属性名而不报错，所以
   "看起来"设置成功了，其实根本没改变 TD 内部状态，警告一直没消失。
   后来想明白：Time Slice 是 TD 根据"这条链有没有接实时音频源"自动强制的，
   不是靠某个属性能单独开关的，跟它较劲没有意义。真正的修法是干脆不去设
   scriptOp.numSamples/rate 了——这两行本来就是被拒绝的操作，删掉不影响
   功能，因为 TD 在 Time Slice 模式下每次 cook 本来就会自动给出正确的采样
   点数（跟音频输入的 n 一致），直接把数据赋给 .vals 就行，长度自动对齐。
   gut_history_tex（现在是 Script TOP，不是 CHOP 了）本来就不涉及 numSamples
   这回事，这个坑跟它无关。

⚠️ 关于新增的"持续静音"效果（uStillness）：
   水面本身已经把 activity=0 时的振幅/湍流下限压得很低（见 afl_ext_td.frag），
   平时接近静止，但河流一直在缓慢流动，短暂的安静和真的很长一段时间没有
   肠鸣音，画面表现是一样的。现在加一个"静音计时器"：activity 连续低于
   SILENCE_THRESHOLD 超过 SILENCE_HOLD_SEC（默认5秒）之后，才开始让
   uStillness 从0缓慢爬升到1（再花 SILENCE_RAMP_SEC 秒），uStillness>0 时
   shader 里会额外做三件事：河流流速进一步放慢、画面轻微降饱和压暗、叠加
   一点雾气。只要中途 activity 重新超过阈值，静音计时器立刻清零、
   uStillness 也跟着掉回0——所以两次肠鸣音之间正常的短暂间隙不会触发这个
   效果，只有真的一大段时间都没有声音才会触发。
"""

# ============================================================
# 配置 — 根据你的环境修改这里
# ============================================================
SHADER_PATH = r'd:\AAAAAAAA\River\afl_ext\afl_ext_td.frag'
AUDIO_FOLDER = r'd:\AAAAAAAA\River\Gut Sounds'
RESOLUTION_W = 1280
RESOLUTION_H = 720

# 气泡可视化——独立于河流水面的另一路输出，不叠加在水面上面（见文件末尾
# 新增的第9步）。用的是同一份 gut_activity['activity_visual']，跟水面共享
# 同一个"振幅"语义，但渲染在自己单独的 gut_bubbles / bubbles_out 节点上。
BUBBLE_SHADER_PATH = r'd:\AAAAAAAA\River\afl_ext\afl_ext_bubbles.frag'
BUBBLE_RESOLUTION_W = 1280
BUBBLE_RESOLUTION_H = 720

# 自定义振幅包络参数（会被直接写死进 gut_envelope_script 回调代码里，见下方）
ENV_ATTACK_SEC = 0.15       # 起音时间常数（秒）— 声音变响时包络追上去的速度，越小反应越快
ENV_RELEASE_SEC = 0.06      # 释音时间常数（秒）— 声音变轻时包络落下去的速度。之前设成0会导致
                            # 包络在下降沿完全不平滑、瞬间跳到原始采样值，产生锯齿状抖动；
                            # 现在给一个很短但非零的时间常数（60毫秒），听感上仍接近"立刻平静"，
                            # 但不再是瞬间硬跳。

# 自动校准参数（线性振幅域，见文件顶部说明）：不再需要手动指定固定的dB数字，
# 也不再经过dB转换——floor/peak/activity 全部直接用线性振幅算。
ENV_FLOOR_RISE_SEC = 4.0     # 安静基线回升的时间常数（秒）——持续偏响的话，缓慢把"安静基线"的
                             # 估计抬高，避免它永远卡在很久以前某个特别安静的瞬间
ENV_PEAK_DECAY_SEC = 10.0    # 响亮基准回落的时间常数（秒）——安静下来之后，缓慢把"响亮基准"降
                             # 回来，这样下一次没那么响的爆发也能顶到接近1，而不是永远拿最响的
                             # 一次当基准
ENV_FLOOR_MARGIN_MULT = 2.0  # noise floor = 追踪到的安静基线 × 这个倍数，留一点余量避免安静基线
                             # 附近的小波动被误判成"活跃"（2倍 ≈ 之前dB版本里+6dB的余量）
ENV_MIN_RANGE_MULT = 4.0     # 参考振幅至少要是 noise floor 的多少倍，防止两者太接近时 activity
                             # 除法分母过小、抖动过猛（4倍 ≈ 之前dB版本里+12dB的最小间隔）

# 视觉平滑参数：见文件顶部说明。只影响喂给shader的值，不影响静音判断。
# 拆成两个方向，不再共用同一个数字：波动->平静（release）目前1秒实测效果
# 很好，保持不变；平静->波动（attack）之前也是1秒，实测反而是这个方向切得
# 太快、太生硬，改慢一点。
VISUAL_ATTACK_SEC = 2.4      # activity 变大（平静->波动）时 activity_visual 追上去的时间常数（秒）——
                             # 1秒/1.8秒都还太快，3秒又太长，调到2.4秒
VISUAL_RELEASE_SEC = 1.0     # activity 变小（波动->平静）时 activity_visual 落下来的时间常数（秒）。
                             # 之前release=2秒时，如果肠鸣音爆发间隔比2秒短，落不完就被下一次
                             # 爆发顶上去，导致平静水面几乎不出现——不是attack的问题，是release
                             # 追不上真实的爆发节奏。1秒实测效果很好，保持不变。
                             # （曾经加过一个"释放保持"参数，想用来盖住两次爆发之间的短暂间隙，
                             # 但它会在下降沿制造一个"平台接衰减"的折角，让波动->平静的过渡明显
                             # 比平静->波动难看，已撤掉，见文件顶部说明）

# 持续静音计时器参数：见文件顶部说明。
SILENCE_HOLD_SEC = 5.0      # activity 连续低于阈值多少秒后，才开始触发"持续无声"的额外效果
SILENCE_RAMP_SEC = 3.0      # 触发之后，额外效果再花多久从0缓慢加到最强（避免卡满阈值那一下产生生硬跳变）
SILENCE_THRESHOLD = 0.05    # activity 低于这个值才计入"安静"，跟 afl_ext_td.frag 里
                            # smoothstep(0.05, 0.15, localActivity) 的下限保持一致

# "历史带"流动效果参数：见文件顶部说明。
HISTORY_SECONDS = 6.0       # 屏幕从一侧流到另一侧，大概代表最近多少秒的声音变化。原来是12秒，
                            # 实测下来肠鸣音单次爆发通常只有1~2秒，摊到12秒的窗口里占的横向宽度
                            # 太窄，哪怕模糊过也会显得像一根"孤零零的柱子"夹在两侧安静中间，很
                            # 突兀（不像图2那种"一边平静一边波动"的宽阔过渡）。缩短到8秒，同样
                            # 长度的爆发会占到更大的画面比例，看起来更像一片区域而不是一条缝——
                            # 代价是画面里能同时看到的"时间跨度"变短了一点。加上"状态锁"之后，
                            # 这个值同时也是 STATE_MIN_DWELL_SEC 的默认值（两个切换之间最短间隔），
                            # 8秒实测下来切换稍微有点慢，改成6秒——反应更快一点，仍然 >=
                            # HISTORY_SECONDS 本身，"最多一次转折"的保证不受影响。
HISTORY_TEXELS = 512        # 历史带纹理的横向分辨率，越大越细腻（512对1280宽的输出基本够用）
HISTORY_FLOW_RIGHT_TO_LEFT = True  # True=新的声音从屏幕右边进来、往左流走；False=从左边进来往右流
HISTORY_BLUR_TEXELS = 55    # 历史带做一次横向滑动平均模糊，把陡峭的边缘抹平（55格约0.86秒）。
                            # 曾经因为 activity_visual 下降沿多了个"释放保持"平台、产生折角，
                            # 把这个值一度加到140格去盖住那个折角；现在"释放保持"已经撤掉，
                            # activity_visual 上升/下降沿都是连续光滑的指数曲线，不再需要额外
                            # 加宽模糊来盖折角，改回55格（模糊太宽反而会让过渡显得拖沓）。
                            # 设成1或0关掉模糊。

# "状态锁"参数（保证任意时刻画面里最多只有一次转折）：见文件顶部说明。
# 历史带原来是逐帧如实记录 activity_visual 的连续值——如果肠鸣音在
# HISTORY_SECONDS 这个窗口内响了两次以上，画面上就会同时出现两次以上的
# 转折（平静/wave来回好几段，比如"wave夹平静夹wave"），很乱。现在改成往
# 历史带里写的不是连续值，而是一个"平静/wave"二值状态：这个状态一旦切换，
# 必须至少保持 STATE_MIN_DWELL_SEC 秒才允许再切换。只要这个值 >=
# HISTORY_SECONDS，数学上就能保证任意时刻画面里最多只有一条转折带——因为
# 两次切换的间隔天然不会短于画面能同时看到的时间跨度。代价是状态切换之后
# 的这段时间里，画面不会实时跟着每一次声音起伏抖动（比如刚变wave后面马上
# 安静了，画面还是会继续wave一段时间，等这次转折走出画面才会看要不要切
# 回平静）——这是刻意的取舍，用来换画面干净、每次只有一个转折。
STATE_MIN_DWELL_SEC = HISTORY_SECONDS  # 必须 >= HISTORY_SECONDS，否则"最多一次转折"的保证会失效，
                                        # 默认直接等于 HISTORY_SECONDS（改 HISTORY_SECONDS 时它跟着变，
                                        # 除非你有意把它单独调大留更多余量）
STATE_THRESHOLD = 0.15      # activity_visual 高于这个值才算"该进入wave状态"，低于才算"该回到平静"，
                            # 跟 afl_ext_td.frag 里 smoothstep(0.05, 0.15, localActivity) 的上限保持一致
STATE_CALM_CONFIRM_SEC = 2.0  # 只影响"切到平静"这个方向：activity_visual 必须连续低于
                            # STATE_THRESHOLD 满这么多秒，才会真的提议切回平静；切到wave这边不受
                            # 影响，一超过阈值立刻提议（仍然还要过 STATE_MIN_DWELL_SEC 那道最短
                            # 间隔）。原因：如果没有这道确认，声音只是短暂停顿一下（哪怕零点几秒），
                            # 只要正好卡在两次切换之间允许再切的那一刻，就可能被判定成"该平静了"，
                            # 结果水面平静下来的时候旁边其实还在响，很不搭。

# ============================================================
# 创建网络
# ============================================================
p = parent()


def new_op(op_type, name):
	# 先删掉同名旧节点再新建，让这个脚本可以安全地重复运行（比如上次跑到一半
	# 报错中断了，或者改了参数想重新生成一遍），不会因为名字冲突报错，也不会
	# 每次运行都在网络里堆一堆 name1 / name2 的重复节点。
	existing = p.op(name)
	if existing is not None:
		existing.destroy()
	return p.create(op_type, name)


# 如果之前跑过更老的版本（用 Analyze/Math/Lag CHOP 做包络提取，或者带冰川
# 背景图的版本），把那批节点也清掉
for old_name in ('gut_analyze', 'gut_math', 'gut_smooth', 'glacier_bg'):
	old_op = p.op(old_name)
	if old_op is not None:
		old_op.destroy()

# --- 1. 像素着色器 Text DAT ---
pixel_dat = new_op(textDAT, 'river_pixel_shader')
try:
    with open(SHADER_PATH, 'r', encoding='utf-8') as f:
        pixel_dat.text = f.read()
    print(f'[OK] Shader loaded from {SHADER_PATH}')
except FileNotFoundError:
    pixel_dat.text = '// ERROR: shader file not found at ' + SHADER_PATH
    print(f'[WARN] Shader file not found: {SHADER_PATH}')

# --- 2. GLSL Multi TOP ---
glsl = new_op(glslmultiTOP, 'river_ocean')
glsl.par.resolutionw = RESOLUTION_W
glsl.par.resolutionh = RESOLUTION_H
glsl.par.outputresolution = 9   # Custom Resolution（自定义分辨率）
glsl.par.pixeldat = pixel_dat

# Uniform变量（占用0~7号槽位）
glsl.par.uniname0 = 'uTime'
glsl.par.value0x.expr = "absTime.seconds"

glsl.par.uniname1 = 'uResolution'
glsl.par.value1x.expr = "me.par.resolutionw.eval()"
glsl.par.value1y.expr = "me.par.resolutionh.eval()"

glsl.par.uniname2 = 'uRiverSpeed'
glsl.par.value2x = 1.0

glsl.par.uniname3 = 'uWaveAmplitude'
glsl.par.value3x = 1.0

glsl.par.uniname4 = 'uTurbulence'
glsl.par.value4x = 1.0

# uGutActivity（全局标量）已经不用了，slot 5 改接 uFlowRightToLeft——
# river_ocean 现在从输入0号槽位的历史带纹理里按屏幕位置采样"当地"活跃度，
# 不再需要一个全局数值（gut_bubbles 那一路气泡是独立的，仍然用全局的
# activity_visual，不受这个影响）
glsl.par.uniname5 = 'uFlowRightToLeft'
glsl.par.value5x = 1.0 if HISTORY_FLOW_RIGHT_TO_LEFT else 0.0

glsl.par.uniname6 = 'uStillness'
glsl.par.value6x = 0.0

# --- 3. "历史带"流动效果：一个 Script TOP 直接生成纹理，接回 river_ocean 输入0 ---
# 原来是"Script CHOP（滚动缓冲区）→ CHOP to TOP（转成纹理）"两步，CHOP to TOP
# 这个跨类型转换操作符的接口试了三轮都没搞定（连线不生效、显式设CHOP引用
# 参数也不报错但还是空白——具体哪里不对，没有真实TD环境没法再往下猜了）。
# 换成更可靠的路子：用一个 Script TOP，在回调里直接维护同样的滚动缓冲区，
# 再用 numpy 拼出一张 1 x HISTORY_TEXELS 的图像，调 scriptOp.copyNumpyArray()
# 直接写成纹理——这是 TD 官方示例里很标准的 Script TOP 写法，不用再依赖
# CHOP↔TOP 之间那层不确定的转换。
history_tex_script_dat = new_op(textDAT, 'gut_history_tex_script')
history_tex_script_dat.text = '''"""
Gut Sounds 活跃度历史带（Script TOP 回调）
按 TD 的帧率（不是音频采样率）持续读取 gut_activity 里 activity_visual 的
当前值，维护一条固定长度（HISTORY_TEXELS个格子）的滚动缓冲区，代表最近
HISTORY_SECONDS 秒的活跃度变化，再直接拼成一张 1 x HISTORY_TEXELS 的图像
写出去，不经过 CHOP。缓冲区自己每帧往前滚动一点，滚动速度由
HISTORY_SECONDS/HISTORY_TEXELS 换算出来，shader 那边不需要再关心时间，只要
把屏幕横坐标固定映射到这条带子上的某个位置，画面看起来就会自然地流动。
"""

import numpy as np

_DEFAULT_HISTORY_SECONDS = ''' + repr(float(HISTORY_SECONDS)) + '''
_HISTORY_TEXELS = ''' + repr(int(HISTORY_TEXELS)) + '''
_DEFAULT_BLUR_TEXELS = ''' + repr(int(HISTORY_BLUR_TEXELS)) + '''
_DEFAULT_STATE_MIN_DWELL_SEC = ''' + repr(float(STATE_MIN_DWELL_SEC)) + '''
_DEFAULT_STATE_THRESHOLD = ''' + repr(float(STATE_THRESHOLD)) + '''
_DEFAULT_STATE_CALM_CONFIRM_SEC = ''' + repr(float(STATE_CALM_CONFIRM_SEC)) + '''

_buf = np.zeros(_HISTORY_TEXELS, dtype=np.float32)
_shift_accum = 0.0
_last_time = None

# "状态锁"：往历史带里写的不是连续的 activity_visual，而是这个二值状态——
# 保证只要 Statemindwellsec >= 历史带窗口长度，任意时刻画面里就最多只有
# 一条转折带，不会出现"wave夹平静夹wave"这种。详见文件顶部说明。
_state = 0.0            # 当前状态：0=平静，1=wave
_last_flip_time = None  # 上一次真正切换状态的时间（absTime.seconds），None=还没切换过
_quiet_confirm_dur = 0.0  # activity_visual 连续低于阈值累计了多长时间（秒）——切到平静之前
                          # 要求这个值攒够 Calmconfirmsec，切到wave不看这个


def onSetupParameters(scriptOp):
	page = scriptOp.appendCustomPage('Gut History')
	p1 = page.appendFloat('Historyseconds', label='History (s)')
	p1[0].default = _DEFAULT_HISTORY_SECONDS
	p1[0].val = _DEFAULT_HISTORY_SECONDS
	p2 = page.appendInt('Blurtexels', label='Blur (texels)')
	p2[0].default = _DEFAULT_BLUR_TEXELS
	p2[0].val = _DEFAULT_BLUR_TEXELS
	p3 = page.appendFloat('Statemindwellsec', label='State Min Dwell (s)')
	p3[0].default = _DEFAULT_STATE_MIN_DWELL_SEC
	p3[0].val = _DEFAULT_STATE_MIN_DWELL_SEC
	p4 = page.appendFloat('Statethreshold', label='State Threshold (activity)')
	p4[0].default = _DEFAULT_STATE_THRESHOLD
	p4[0].val = _DEFAULT_STATE_THRESHOLD
	p5 = page.appendFloat('Calmconfirmsec', label='Calm Confirm (s)')
	p5[0].default = _DEFAULT_STATE_CALM_CONFIRM_SEC
	p5[0].val = _DEFAULT_STATE_CALM_CONFIRM_SEC
	return


def onPulse(par):
	return


def onCook(scriptOp):
	global _buf, _shift_accum, _last_time, _state, _last_flip_time, _quiet_confirm_dur

	try:
		history_seconds = scriptOp.par.Historyseconds.eval()
	except Exception:
		history_seconds = _DEFAULT_HISTORY_SECONDS

	try:
		blur_texels = int(scriptOp.par.Blurtexels.eval())
	except Exception:
		blur_texels = _DEFAULT_BLUR_TEXELS

	try:
		state_min_dwell_sec = scriptOp.par.Statemindwellsec.eval()
	except Exception:
		state_min_dwell_sec = _DEFAULT_STATE_MIN_DWELL_SEC

	try:
		state_threshold = scriptOp.par.Statethreshold.eval()
	except Exception:
		state_threshold = _DEFAULT_STATE_THRESHOLD

	try:
		calm_confirm_sec = scriptOp.par.Calmconfirmsec.eval()
	except Exception:
		calm_confirm_sec = _DEFAULT_STATE_CALM_CONFIRM_SEC

	now = absTime.seconds
	dt = 0.0 if _last_time is None else max(0.0, now - _last_time)
	_last_time = now

	activity_visual_now = 0.0
	activity_op = op('gut_activity')
	if activity_op is not None:
		try:
			activity_visual_now = float(activity_op['activity_visual'].eval())
		except Exception:
			try:
				activity_visual_now = float(activity_op['activity_visual'][0])
			except Exception:
				activity_visual_now = 0.0

	# 状态锁：切到wave一超过阈值就立刻提议；切到平静必须先连续低于阈值攒够
	# calm_confirm_sec 秒才提议（不然声音只是短暂停顿一下也会被判定成"该
	# 平静了"，水面平静下来时旁边其实还在响，很难看）。提议之后还要再过一道
	# state_min_dwell_sec 的最短间隔才真的切换。第一次 cook（还没有
	# _last_flip_time）直接按当前活跃度初始化，不用等确认也不用等间隔。
	if activity_visual_now > state_threshold:
		_quiet_confirm_dur = 0.0
		desired_state = 1.0
	else:
		_quiet_confirm_dur += dt
		desired_state = 0.0 if _quiet_confirm_dur >= calm_confirm_sec else _state

	if _last_flip_time is None:
		_state = 1.0 if activity_visual_now > state_threshold else 0.0
		_last_flip_time = now
	elif desired_state != _state and (now - _last_flip_time) >= state_min_dwell_sec:
		_state = desired_state
		_last_flip_time = now

	current_val = _state

	# 每秒该滚多少格：总格数 / 总秒数
	texels_per_sec = _HISTORY_TEXELS / max(history_seconds, 1e-3)
	_shift_accum += dt * texels_per_sec
	shift = int(_shift_accum)
	if shift > 0:
		shift = min(shift, _HISTORY_TEXELS)
		_buf = np.roll(_buf, -shift)      # 整体往前挪 shift 格（丢弃最旧的）
		_buf[_HISTORY_TEXELS - shift:] = current_val  # 空出来的位置填最新值
		_shift_accum -= shift

	# 横向滑动平均模糊：不然一段很短暂的安静会在画面上变成一道边缘锋利的
	# "平静走廊"，很不自然（细长竖直、跟旁边波浪没有过渡）。用边缘延展的
	# padding，避免最新/最旧两端因为卷积边界效应被不该有地拉平。
	if blur_texels > 1:
		k = min(blur_texels, _HISTORY_TEXELS)
		kernel = np.ones(k, dtype=np.float32) / float(k)
		pad = k // 2
		padded = np.pad(_buf, (pad, k - 1 - pad), mode='edge')
		row = np.convolve(padded, kernel, mode='valid')[:_HISTORY_TEXELS].astype(np.float32)
	else:
		row = _buf.astype(np.float32)

	# 拼成 1 行 x HISTORY_TEXELS 列的 RGBA 图像：R/G/B 都存活跃度值（shader
	# 只用 .r），A 固定为1（不透明）。形状是 (高, 宽, 通道数)，float32、0~1。
	img = np.empty((1, _HISTORY_TEXELS, 4), dtype=np.float32)
	img[0, :, 0] = row
	img[0, :, 1] = row
	img[0, :, 2] = row
	img[0, :, 3] = 1.0
	scriptOp.copyNumpyArray(img)
	return
'''
history_tex_script_dat.nodeX = 250; history_tex_script_dat.nodeY = -550

gut_history_tex = new_op(scriptTOP, 'gut_history_tex')
gut_history_tex.par.callbacks = history_tex_script_dat
gut_history_tex.par.resolutionw = HISTORY_TEXELS
gut_history_tex.par.resolutionh = 1
gut_history_tex.par.outputresolution = 9   # Custom Resolution（自定义分辨率）
gut_history_tex.nodeX = 500; gut_history_tex.nodeY = -550

glsl.inputConnectors[0].connect(gut_history_tex)

# --- 4. 音频文件输入链 ---
audio_file = new_op(audiofileinCHOP, 'gut_audio_file')
audio_file.par.file = AUDIO_FOLDER  # 脚本运行后手动在节点里选择具体的 .wav 文件
audio_file.par.playmode = 0      # 0 = Locked to Timeline（跟随时间线播放和循环）

# 音频输出 — 同步从扬声器播放肠道声音
audio_out = new_op(audiodeviceoutCHOP, 'gut_audio_out')
audio_out.inputConnectors[0].connect(audio_file)

# --- 5. 自定义振幅包络提取 + 自动校准 + 静音计时器（Script CHOP + 回调代码 Text DAT） ---
# Script CHOP 本身不带代码，需要一个单独的 Text DAT 作为它的 Callbacks DAT。
# 下面这些默认值直接拼进代码文本里，onCook 不会在自定义参数还没建好时被迫
# 依赖它们（见文件顶部说明）。
env_script_dat = new_op(textDAT, 'gut_envelope_script')
env_script_dat.text = '''"""
Gut Sounds 振幅包络提取 + 自动校准 + 静音计时器（Script CHOP 回调）
自定义实现，不使用 TD 自带的 Analyze(RMS)/Math(增益)/Lag(平滑)：
逐音频采样点整流 + 非对称指数包络跟随（attack/release 独立时间常数）得到
线性振幅包络，再用两个自动跟踪的振幅（安静基线 floor / 响亮基准 peak，
都是线性振幅，不经过dB转换）把包络归一化到 0~1，得到 activity——表达的是
"振幅大小"而不是"听感上的音量大小"。再用一个"静音计时器"跟踪 activity
连续低于阈值多久，超过一段时间后才让 stillness 从0缓慢爬升到1。
"""

import numpy as np

# 下面这些默认值由外层 setup_river_td.py 在生成这段代码时写死进来。
# 之所以不完全依赖下面 onSetupParameters 建出来的同名自定义参数，是因为那些
# 参数只有在这个 Script CHOP 真正 cook 过一次之后才会出现，onCook 用
# _par_or_default() 优先读自定义参数、读不到就退回这里的默认值，两边都能用。
_DEFAULT_ATTACK_SEC = ''' + repr(float(ENV_ATTACK_SEC)) + '''
_DEFAULT_RELEASE_SEC = ''' + repr(float(ENV_RELEASE_SEC)) + '''
_DEFAULT_FLOOR_RISE_SEC = ''' + repr(float(ENV_FLOOR_RISE_SEC)) + '''
_DEFAULT_PEAK_DECAY_SEC = ''' + repr(float(ENV_PEAK_DECAY_SEC)) + '''
_DEFAULT_FLOOR_MARGIN_MULT = ''' + repr(float(ENV_FLOOR_MARGIN_MULT)) + '''
_DEFAULT_MIN_RANGE_MULT = ''' + repr(float(ENV_MIN_RANGE_MULT)) + '''
_DEFAULT_VISUAL_ATTACK_SEC = ''' + repr(float(VISUAL_ATTACK_SEC)) + '''
_DEFAULT_VISUAL_RELEASE_SEC = ''' + repr(float(VISUAL_RELEASE_SEC)) + '''
_DEFAULT_SILENCE_HOLD_SEC = ''' + repr(float(SILENCE_HOLD_SEC)) + '''
_DEFAULT_SILENCE_RAMP_SEC = ''' + repr(float(SILENCE_RAMP_SEC)) + '''
_DEFAULT_SILENCE_THRESHOLD = ''' + repr(float(SILENCE_THRESHOLD)) + '''

# 包络的线性幅值、自动校准跟踪到的 floor/peak（线性振幅单位）、静音计时器
# 累计的连续安静时长（单位秒），全部跨 cook 持续存在（这个模块在 TD 里常驻，
# 不会每帧重新 import，所以可以放心用模块级全局变量保存状态，让这些状态在
# 多次 cook 之间连续、不跳变）
_env_lin = 1e-8
_floor_lin = None   # 自动跟踪的"安静基线"（线性振幅），None 表示还没有任何数据
_peak_lin = None    # 自动跟踪的"响亮基准"（线性振幅），None 表示还没有任何数据
_quiet_dur = 0.0    # 连续处于"安静"状态累计了多长时间（秒），一旦不安静就清零
_visual_activity = 0.0  # activity 套一层慢平滑之后、真正喂给 shader 的值


def onSetupParameters(scriptOp):
	page = scriptOp.appendCustomPage('Gut Envelope')
	p1 = page.appendFloat('Attacksec', label='Attack (s)')
	p1[0].default = _DEFAULT_ATTACK_SEC
	p1[0].val = _DEFAULT_ATTACK_SEC
	p2 = page.appendFloat('Releasesec', label='Release (s)')
	p2[0].default = _DEFAULT_RELEASE_SEC
	p2[0].val = _DEFAULT_RELEASE_SEC
	p3 = page.appendFloat('Floorrisesec', label='Floor Rise (s)')
	p3[0].default = _DEFAULT_FLOOR_RISE_SEC
	p3[0].val = _DEFAULT_FLOOR_RISE_SEC
	p4 = page.appendFloat('Peakdecaysec', label='Peak Decay (s)')
	p4[0].default = _DEFAULT_PEAK_DECAY_SEC
	p4[0].val = _DEFAULT_PEAK_DECAY_SEC
	p5 = page.appendFloat('Floormarginmult', label='Floor Margin (x)')
	p5[0].default = _DEFAULT_FLOOR_MARGIN_MULT
	p5[0].val = _DEFAULT_FLOOR_MARGIN_MULT
	p6 = page.appendFloat('Minrangemult', label='Min Range (x)')
	p6[0].default = _DEFAULT_MIN_RANGE_MULT
	p6[0].val = _DEFAULT_MIN_RANGE_MULT
	p6b = page.appendFloat('Visualattacksec', label='Visual Attack (s)')
	p6b[0].default = _DEFAULT_VISUAL_ATTACK_SEC
	p6b[0].val = _DEFAULT_VISUAL_ATTACK_SEC
	p6c = page.appendFloat('Visualreleasesec', label='Visual Release (s)')
	p6c[0].default = _DEFAULT_VISUAL_RELEASE_SEC
	p6c[0].val = _DEFAULT_VISUAL_RELEASE_SEC
	p7 = page.appendFloat('Silenceholdsec', label='Silence Hold (s)')
	p7[0].default = _DEFAULT_SILENCE_HOLD_SEC
	p7[0].val = _DEFAULT_SILENCE_HOLD_SEC
	p8 = page.appendFloat('Silencerampsec', label='Silence Ramp (s)')
	p8[0].default = _DEFAULT_SILENCE_RAMP_SEC
	p8[0].val = _DEFAULT_SILENCE_RAMP_SEC
	p9 = page.appendFloat('Silencethreshold', label='Silence Threshold (activity)')
	p9[0].default = _DEFAULT_SILENCE_THRESHOLD
	p9[0].val = _DEFAULT_SILENCE_THRESHOLD
	return


def onPulse(par):
	return


def _par_or_default(scriptOp, name, default):
	# 自定义参数要等 onSetupParameters 真正跑过一次才会出现在 scriptOp.par 上；
	# 万一还没建好，就退回用上面写死的默认值，不会像直接访问
	# scriptOp.par.Attacksec 那样在参数不存在时直接抛异常。
	try:
		return scriptOp.par[name].eval()
	except Exception:
		return default


def onCook(scriptOp):
	global _env_lin, _floor_lin, _peak_lin, _quiet_dur, _visual_activity
	scriptOp.clear()

	attack_sec = _par_or_default(scriptOp, 'Attacksec', _DEFAULT_ATTACK_SEC)
	release_sec = _par_or_default(scriptOp, 'Releasesec', _DEFAULT_RELEASE_SEC)
	floor_rise_sec = _par_or_default(scriptOp, 'Floorrisesec', _DEFAULT_FLOOR_RISE_SEC)
	peak_decay_sec = _par_or_default(scriptOp, 'Peakdecaysec', _DEFAULT_PEAK_DECAY_SEC)
	floor_margin_mult = _par_or_default(scriptOp, 'Floormarginmult', _DEFAULT_FLOOR_MARGIN_MULT)
	min_range_mult = _par_or_default(scriptOp, 'Minrangemult', _DEFAULT_MIN_RANGE_MULT)
	visual_attack_sec = _par_or_default(scriptOp, 'Visualattacksec', _DEFAULT_VISUAL_ATTACK_SEC)
	visual_release_sec = _par_or_default(scriptOp, 'Visualreleasesec', _DEFAULT_VISUAL_RELEASE_SEC)
	silence_hold_sec = _par_or_default(scriptOp, 'Silenceholdsec', _DEFAULT_SILENCE_HOLD_SEC)
	silence_ramp_sec = _par_or_default(scriptOp, 'Silencerampsec', _DEFAULT_SILENCE_RAMP_SEC)
	silence_threshold = _par_or_default(scriptOp, 'Silencethreshold', _DEFAULT_SILENCE_THRESHOLD)

	def _stillness_from_quiet_dur(quiet_dur):
		return float(np.clip((quiet_dur - silence_hold_sec) / max(silence_ramp_sec, 1e-6), 0.0, 1.0))

	audio_in = scriptOp.inputs[0] if scriptOp.inputs else None
	if audio_in is None or audio_in.numSamples == 0 or audio_in.numChans == 0:
		# 还没有音频数据（比如时间线还没开始播放）：沿用上一次的包络/校准/静音
		# 计时器状态，不要直接归零或累加（这里拿不到真实的时长），避免画面在
		# 播放/暂停切换时跳变
		env_lin_now = max(_env_lin, 1e-8)
		floor_lin = _floor_lin if _floor_lin is not None else env_lin_now
		noise_floor_lin = floor_lin * floor_margin_mult
		ref_lin = max(_peak_lin if _peak_lin is not None else env_lin_now, noise_floor_lin * min_range_mult)
		activity_now = float(np.clip((env_lin_now - noise_floor_lin) / (ref_lin - noise_floor_lin), 0.0, 1.0))
		stillness_now = _stillness_from_quiet_dur(_quiet_dur)
		act = scriptOp.appendChan('activity')
		vis = scriptOp.appendChan('activity_visual')
		lin = scriptOp.appendChan('env_lin')
		dbg = scriptOp.appendChan('env_db')
		flr = scriptOp.appendChan('floor_lin')
		pk = scriptOp.appendChan('ref_lin')
		stl = scriptOp.appendChan('stillness')
		# 同样不手动设 numSamples（原因见下方主分支的注释）
		act[0] = activity_now
		vis[0] = _visual_activity   # 拿不到真实时长，沿用上一次平滑后的值，不重新计算
		lin[0] = env_lin_now
		dbg[0] = 20.0 * np.log10(env_lin_now)   # 纯调试显示用，不参与 activity 计算
		flr[0] = noise_floor_lin
		pk[0] = ref_lin
		stl[0] = stillness_now
		return

	sr = audio_in.rate
	samples = audio_in.numpyArray()          # shape: (numChans, numSamples)
	mono = np.mean(samples, axis=0)          # 多声道取平均，代表整体响度

	# exp(-1/(tau*sr)) 是标准的一阶指数包络跟随器系数，tau 是时间常数（秒）。
	# 声音变大用 attack 系数、变小用 release 系数，做出跟真实包络检波器一样的
	# 非对称响应，而不是 Lag CHOP 那种单一、逐帧的对称平滑。
	a_att = float(np.exp(-1.0 / max(attack_sec * sr, 1e-6)))
	a_rel = float(np.exp(-1.0 / max(release_sec * sr, 1e-6)))

	abs_samples = np.abs(mono)
	n = abs_samples.shape[0]
	env = np.empty(n, dtype=np.float64)

	e = _env_lin
	for i in range(n):
		x = abs_samples[i]
		if x > e:
			e = a_att * e + (1.0 - a_att) * x   # 声音变大：按 attack 时间常数追上去
		else:
			e = a_rel * e + (1.0 - a_rel) * x   # 声音变小：按 release 时间常数落下来
		env[i] = e
	_env_lin = e   # 保存到下一次 cook 继续用，保证包络跨帧连续

	# --- 自动校准：跟踪这个 cook 块里的最低/最高线性振幅，更新安静基线/响亮基准 ---
	# 全程都在线性振幅域里算，不转 dB——表达的是"振幅大小"，不是"听感响度"。
	block_min_lin = float(np.min(env))
	block_max_lin = float(np.max(env))
	block_dur = n / float(sr)   # 这个 cook 块对应的真实时长（秒），用来算跟随系数/累计静音时长

	if _floor_lin is None:
		_floor_lin = block_min_lin
	elif block_min_lin < _floor_lin:
		_floor_lin = block_min_lin   # 观察到更安静的片段：立刻跟着降下去
	else:
		rise_coef = float(np.exp(-block_dur / max(floor_rise_sec, 1e-6)))
		_floor_lin = rise_coef * _floor_lin + (1.0 - rise_coef) * block_min_lin   # 持续偏响：缓慢抬高

	if _peak_lin is None:
		_peak_lin = block_max_lin
	elif block_max_lin > _peak_lin:
		_peak_lin = block_max_lin   # 观察到更响的片段：立刻跟着升上去
	else:
		decay_coef = float(np.exp(-block_dur / max(peak_decay_sec, 1e-6)))
		_peak_lin = decay_coef * _peak_lin + (1.0 - decay_coef) * block_max_lin   # 安静下来：缓慢回落

	noise_floor_lin = _floor_lin * floor_margin_mult
	ref_lin = max(_peak_lin, noise_floor_lin * min_range_mult)   # 保证分母恒正，不会除零/抖动过猛

	activity = np.clip((env - noise_floor_lin) / (ref_lin - noise_floor_lin), 0.0, 1.0)

	# --- 视觉平滑：在 activity 之上再套一层慢得多的低通，得到真正喂给 shader
	# 的 activity_visual，避免肠鸣音一阵阵地响导致水面跟着一阵阵地抽搐。
	# 起落分开两个时间常数（跟下面的 attack/release 包络同一个思路）：
	# 平静->波动用 visual_attack_sec（想要更快有响应），波动->平静用
	# visual_release_sec（想要慢慢从容地落回去）。这一步不影响上面已经算好
	# 的 activity，静音计时器仍然用未经平滑的 activity 判断，保持灵敏。
	# （曾经在这里加过一个"释放保持"——activity 低于 v 时先原地不动攒一段
	# 时间才开始 release 衰减，想借此盖住两次爆发间的短暂间隙——但它会在
	# 下降沿制造一个"平台接衰减"的折角，让历史带里波动->平静的过渡明显比
	# 平静->波动难看，已撤掉。现在跟最早的版本一样，单纯的非对称指数平滑，
	# 上升/下降沿都是连续光滑的曲线，两个方向对称。）
	a_vis_att = float(np.exp(-1.0 / max(visual_attack_sec * sr, 1e-6)))
	a_vis_rel = float(np.exp(-1.0 / max(visual_release_sec * sr, 1e-6)))
	activity_visual = np.empty(n, dtype=np.float64)
	v = _visual_activity
	for i in range(n):
		x = activity[i]
		if x > v:
			v = a_vis_att * v + (1.0 - a_vis_att) * x   # 平静->波动：按 visual_attack_sec 追上去
		else:
			v = a_vis_rel * v + (1.0 - a_vis_rel) * x   # 波动->平静：按 visual_release_sec 落下来
		activity_visual[i] = v
	_visual_activity = v

	# --- 静音计时器：这个 cook 块里只要有一个采样点的 activity 超过阈值，
	# 就算作"不安静"，立刻把累计时长清零；整块都在阈值以下，才累加时长 ---
	block_activity_max = float(np.max(activity))
	if block_activity_max > silence_threshold:
		_quiet_dur = 0.0
	else:
		_quiet_dur += block_dur
	stillness_val = _stillness_from_quiet_dur(_quiet_dur)

	act = scriptOp.appendChan('activity')
	vis = scriptOp.appendChan('activity_visual')  # 平滑过的版本，真正送去 shader 的是这个
	lin = scriptOp.appendChan('env_lin')    # 调试用：原始线性振幅包络（activity 就是从这个算出来的）
	dbg = scriptOp.appendChan('env_db')     # 调试用：换算成dB纯粹方便看图，不参与 activity 计算
	flr = scriptOp.appendChan('floor_lin')  # 调试用：当前生效的安静基线（含margin，线性振幅）
	pk = scriptOp.appendChan('ref_lin')     # 调试用：当前生效的响亮基准（线性振幅）
	stl = scriptOp.appendChan('stillness')  # 送去 shader 的"持续无声"强度，0~1
	# 不再手动设 scriptOp.numSamples/rate——这个 CHOP 的输入是实时音频，TD会
	# 强制整条链进 Time Slice 模式，这两行会被拒绝并一直刷警告。直接把数据
	# 赋给 .vals 就行，长度会跟着这次 cook 该有的采样点数（也就是 n）自动对齐，
	# 不需要我们显式声明。
	act.vals = activity.tolist()
	vis.vals = activity_visual.tolist()
	lin.vals = env.tolist()
	dbg.vals = (20.0 * np.log10(np.maximum(env, 1e-8))).tolist()
	flr.vals = [noise_floor_lin] * n
	pk.vals = [ref_lin] * n
	stl.vals = [stillness_val] * n
	return
'''
env_script_dat.nodeX = 250; env_script_dat.nodeY = -150

env_chop = new_op(scriptCHOP, 'gut_envelope')
env_chop.par.callbacks = env_script_dat
env_chop.inputConnectors[0].connect(audio_file)
# 不再尝试关闭 Time Slice 模式了——试过 .par.timeslice 和 .isTimeSlice 两种
# 写法都没用（Time Slice 是 TD 根据"接了实时音频源"自动强制的，不是靠属性
# 能关掉的）。真正的修法在 gut_envelope_script 回调代码里：不再手动设
# scriptOp.numSamples/rate，直接把数据赋给 .vals，长度自动跟音频对齐，
# 详见文件顶部说明。
# 不在这里同步设置 env_chop.par.Attacksec 等自定义参数——它们由回调脚本里的
# onSetupParameters 建立，此刻这个 CHOP 可能还没 cook 过、参数还不存在，
# 强行赋值会抛 AttributeError 把脚本中断在这里（历史教训）。默认值已经写死
# 进 gut_envelope_script 的文本里了，之后想调也可以直接在 gut_envelope 的
# 参数面板里改（存在的话）。

# Null — 干净的输出引用点
null_out = new_op(nullCHOP, 'gut_activity')
null_out.inputConnectors[0].connect(env_chop)

# --- 6. 将音频连接到 GLSL uniform ---
# 注意：river_ocean 已经不用全局的 activity_visual 了（slot 5 现在是
# uFlowRightToLeft，第2步里已经赋过值，这里不要再覆盖成 activity_visual 的
# 表达式——历史带纹理才是驱动水面活跃度的东西，见输入0号槽位的接线）。
# uStillness 仍然是全局值，正常接。
glsl.par.value6x.expr = "op('gut_activity')['stillness']"

# --- 7. 布局节点位置 ---
audio_file.nodeX = 0;     audio_file.nodeY = -300
audio_out.nodeX  = 0;     audio_out.nodeY  = -450
env_chop.nodeX   = 250;   env_chop.nodeY   = -300
null_out.nodeX   = 500;   null_out.nodeY   = -300

pixel_dat.nodeX = 0;      pixel_dat.nodeY = 0
glsl.nodeX      = 350;    glsl.nodeY      = 0

# --- 8. 创建输出预览 ---
out_top = new_op(outTOP, 'river_out')
out_top.inputConnectors[0].connect(glsl)
out_top.nodeX = 600;      out_top.nodeY = 0

# --- 9. 气泡可视化（独立于河流水面，单独一路输出，不叠加在水面上面） ---
# 不改动上面第1~8步的任何东西，只是新加一条完全独立的信号链：
#   gut_activity['activity_visual'] --> gut_bubbles (GLSL TOP) --> bubbles_out
# 跟河流水面共用同一路"平滑后的活跃度"，语义一致（振幅越大气泡越大），
# 但渲染在自己单独的节点上，输出带alpha透明通道，方便你之后想怎么用就怎么用
# （单独显示、或者自己再手动合成到别的画面上），不会影响 river_ocean/river_out。
bubble_pixel_dat = new_op(textDAT, 'bubble_pixel_shader')
try:
    with open(BUBBLE_SHADER_PATH, 'r', encoding='utf-8') as f:
        bubble_pixel_dat.text = f.read()
    print(f'[OK] Bubble shader loaded from {BUBBLE_SHADER_PATH}')
except FileNotFoundError:
    bubble_pixel_dat.text = '// ERROR: shader file not found at ' + BUBBLE_SHADER_PATH
    print(f'[WARN] Bubble shader file not found: {BUBBLE_SHADER_PATH}')

bubble_glsl = new_op(glslmultiTOP, 'gut_bubbles')
bubble_glsl.par.resolutionw = BUBBLE_RESOLUTION_W
bubble_glsl.par.resolutionh = BUBBLE_RESOLUTION_H
bubble_glsl.par.outputresolution = 9   # Custom Resolution（自定义分辨率）
bubble_glsl.par.pixeldat = bubble_pixel_dat

bubble_glsl.par.uniname0 = 'uTime'
bubble_glsl.par.value0x.expr = "absTime.seconds"

bubble_glsl.par.uniname1 = 'uResolution'
bubble_glsl.par.value1x.expr = "me.par.resolutionw.eval()"
bubble_glsl.par.value1y.expr = "me.par.resolutionh.eval()"

bubble_glsl.par.uniname2 = 'uGutActivity'
bubble_glsl.par.value2x.expr = "op('gut_activity')['activity_visual']"

bubbles_out = new_op(outTOP, 'bubbles_out')
bubbles_out.inputConnectors[0].connect(bubble_glsl)

# 布局节点位置——特意放在河流水面网络的下方，隔开一段距离，视觉上明确是
# 独立的一条链，不会跟第1~8步的节点挤在一起
bubble_pixel_dat.nodeX = 0;    bubble_pixel_dat.nodeY = -700
bubble_glsl.nodeX      = 350;  bubble_glsl.nodeY      = -700
bubbles_out.nodeX      = 600;  bubbles_out.nodeY      = -700

print('')
print('============================================')
print('  River Ocean network created!')
print('============================================')
print('')
print(f'Audio folder: {AUDIO_FOLDER}')
print('Put your .wav files there, then click gut_audio_file to select the file.')
print('')
print('Next steps:')
print('  1. Click gut_audio_file — set the correct .wav file path')
print('  2. Press Play in timeline — audio should start playing')
print("  3. Watch gut_envelope CHOP's 'activity' channel — driven by linear amplitude now")
print("     (not dB/loudness), auto-calibrated 0~1, no manual tuning needed")
print("  4. 'floor_lin'/'ref_lin' show the auto-tracked quiet/loud linear amplitude levels;")
print("     'env_db' is just a dB-scaled copy of 'env_lin' for easier reading on the chart")
print(f"     'activity_visual' (Visual Attack = {VISUAL_ATTACK_SEC}s, Visual Release = {VISUAL_RELEASE_SEC}s)")
print(f"     feeds gut_history_tex, which scrolls it into a {HISTORY_SECONDS}s-long history strip")
print("     texture that river_ocean samples per-pixel")
print("     by screen position — quiet/loud moments now flow across the water instead of the")
print("     whole screen switching at once. Check gut_history_tex looks like a scrolling strip.")
print(f"  5. 'stillness' channel stays 0 during normal gaps, and only ramps up to 1 after")
print(f'     {SILENCE_HOLD_SEC}s of continuous silence (over {SILENCE_RAMP_SEC}s) — drives the')
print('     extra slow-down/desaturate/fog look in the shader when nothing has happened for a while')
print(f'  6. If it reacts too fast/slow, tune Floor Rise (currently {ENV_FLOOR_RISE_SEC}s) /')
print(f'     Peak Decay (currently {ENV_PEAK_DECAY_SEC}s) / Silence Hold / Silence Ramp on gut_envelope')
print('  7. Click river_ocean to see the ocean!')
print('  8. Click bubbles_out to see the standalone bubble visualization — bubbles rise')
print('     continuously and scale up with activity_visual, independent from the water')
