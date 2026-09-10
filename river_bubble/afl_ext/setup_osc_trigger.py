"""
TouchDesigner OSC Start-Trigger Setup Script (Stage 2)
=======================================================
在 TouchDesigner 里(要先跑过 setup_river_td.py,这个脚本假设 gut_audio_file /
river_ocean 这些节点已经存在):
0. 如果之前跑过旧版本的这个脚本、已经生成了 gut_osc_in / gut_osc_callbacks /
   gut_osc_exec 这几个节点,先把它们删掉,再跑这一版(避免重名冲突)。
1. 创建一个 Text DAT,把这个脚本粘贴进去
2. 右键 Text DAT → Run Script
3. 会新增 2 个节点,让 GutSound-HR-EDA-Sync 网站能通过 OSC 远程触发这里的音频播放

信号链(新增部分):
  网站后端 (server.py, stage=2 时) --OSC/UDP--> gut_osc_in (OSC In DAT)
                                                      ↓ (table 变化)
                                              gut_osc_exec (DAT Execute)
                                                      ↓ 触发
                                              gut_audio_file 从头播放
                                     (它自己已经在驱动 river_ocean 的 uGutActivity,不用改)

⚠️ 注意:这个脚本没有在真实 TouchDesigner 里跑过验证(开发环境里没有 TD 可用),
   已知第一版有个 bug 改掉了(DAT Execute 没有 `.par.callbacks` 这个参数——它自己
   就是个 DAT,回调代码要直接写进它自己的 text 里,而不是指向另一个 Text DAT)。
   如果再跑出来别的报错,把 Textport 里的红字发过来,照着改。
"""

# ============================================================
# 配置 — 要跟 GutSound-HR-EDA-Sync/website/backend/server.py 里的
# OSC_PORT / OSC_START_ADDRESS 保持一致
# ============================================================
OSC_PORT = 9000
OSC_START_ADDRESS = '/gutsound/start'
AUDIO_FILE_OP = 'gut_audio_file'  # setup_river_td.py 创建的音频节点名字

# ============================================================
# 创建网络
# ============================================================
p = parent()

# --- 1. OSC In DAT：监听网站后端发来的开始信号 ---
osc_in = p.create(oscinDAT, 'gut_osc_in')
osc_in.par.port = OSC_PORT
osc_in.par.active = True
osc_in.nodeX = 0; osc_in.nodeY = 300

# --- 2. DAT Execute：表格一有新行（收到新 OSC 消息）就触发回调。
#     DAT Execute 节点本身就是一段脚本（跟 Text DAT 一样可以直接写 .text），
#     不需要另外一个 Text DAT 来存回调代码。
osc_exec = p.create(datexecuteDAT, 'gut_osc_exec')
osc_exec.par.dat = osc_in
osc_exec.par.tablechange = True
osc_exec.text = '''"""Triggered whenever gut_osc_in's table changes (i.e. a new OSC message
arrived). Only reacts to the start address the website sends; everything
else is ignored.

gut_osc_in has "Split Message into Columns" off, so each row is a single
"message" column containing "<address> <arg0> <arg1> ..." as one
space-joined string (e.g. "/gutsound/start 1") -- not a separate
address/args columns table. So we split on whitespace and compare just
the first token, not the whole cell value."""

def onTableChange(dat):
	audio = op(\'''' + AUDIO_FILE_OP + '''\')
	if audio is None:
		return
	if dat.numRows < 2:
		return
	message = dat[dat.numRows - 1, 0].val
	parts = message.split()
	if not parts or parts[0] != \'''' + OSC_START_ADDRESS + '''\':
		return
	# 跳转到文件开头并播放一次。gut_audio_file 必须处于
	# "Sequential"（顺序）播放模式，而不是"Locked to Timeline"（锁定时间线），
	# 这样 Play/Cue 才能被独立触发 —— 下面这段脚本会负责把它设成这个模式。
	audio.par.cuepulse.pulse()
	audio.par.play = 1
	return

def onRowChange(dat, rows):
	return

def onColChange(dat, cols):
	return

def onCellChange(dat, cells, prev):
	return

def onSizeChange(dat):
	return
'''
osc_exec.nodeX = 250; osc_exec.nodeY = 300

# --- 3. 把音频节点切到 Sequential 模式,这样才能被 Play/Cue 独立触发 ---
# （setup_river_td.py 里原来设成 0 = Locked to Timeline，跟随时间线循环播放；
#   Stage 2 每次实验只播一次、由 OSC 触发，所以改成 Sequential。）
audio_file = op(AUDIO_FILE_OP)
if audio_file is not None:
	audio_file.par.playmode = 1  # 1 = Sequential（如果对不上，改成你 TD 里实际的下拉选项）
else:
	print(f'[WARN] {AUDIO_FILE_OP} not found -- run setup_river_td.py first')

print('')
print('============================================')
print('  OSC start-trigger network created!')
print('============================================')
print('')
print(f'Listening for OSC on port {OSC_PORT}, address {OSC_START_ADDRESS}')
print('Test it: on the same machine, send a UDP OSC message to that port/address')
print('(e.g. from the website, click Play with Stage 2 selected) and check that')
print(f'{AUDIO_FILE_OP} starts playing from the beginning.')
