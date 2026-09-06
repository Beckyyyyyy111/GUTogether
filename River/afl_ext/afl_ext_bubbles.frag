// afl_ext_bubbles.frag —— 肠鸣音气泡可视化
// 这是一路完全独立的 GLSL TOP 着色器，不叠加在河流水面（afl_ext_td.frag /
// river_ocean）上面，输出到自己单独的 gut_bubbles / bubbles_out 节点。
//
// 固定就是 10 个气泡（不是之前那种"无限格子"随机生成一大片的做法），每个
// 气泡有自己明确写死的基础大小——特意选得大小差异很明显，有很小的、也有
// 很大的，不是差不多大的一堆。10个气泡各自独立地从画面底部往上飘、飘出
// 顶部之后再从底部重新出现，循环不息；水平位置、上升速度、起始相位都是
// 各自独立的，所以不会像同一个模子刻出来的一样整齐划一。
// 整体尺度还会跟着 uGutActivity（跟河流水面用的是同一路 activity_visual）
// 实时缩放——肠鸣音振幅越大，10个气泡一起等比例变大。

uniform float uTime;        // 时间，绑定的是 absTime.seconds，跟河流水面用的是同一个
uniform vec2 uResolution;   // 这一路输出自己的分辨率
uniform float uGutActivity; // 0~1，跟河流水面用的是同一路 activity_visual（见 setup_river_td.py）

out vec4 fragColor;

#define NUM_BUBBLES 10

// 简单的hash函数，用一个数字种子生成"看起来随机"但其实是确定性的数值，
// 用来给每个气泡分配各自固定不变的水平位置/速度/相位
float hash1(float p) {
  p = fract(p * 0.1031);
  p *= p + 33.33;
  p *= p + p;
  return fract(p);
}

void main() {
  float aspect = uResolution.x / uResolution.y;
  vec2 uv = gl_FragCoord.xy / uResolution;
  uv.x *= aspect; // 按宽高比修正，保证气泡是正圆，不是被拉扁的椭圆

  // 振幅越大，10个气泡整体越大；activity=0时也保留基础尺寸，平时没有肠鸣音
  // 也能看到气泡稳定地飘，只是响的时候明显变大
  float sizeScale = mix(0.6, 1.7, clamp(uGutActivity, 0.0, 1.0));

  // 10个气泡各自的基础半径（相对屏幕高度的比例），故意拉开差距——
  // 最小的和最大的差了十几倍，不是大小相近的一堆
  float baseSizes[NUM_BUBBLES] = float[](
    0.012, 0.02, 0.03, 0.045, 0.06, 0.08, 0.10, 0.13, 0.16, 0.20
  );

  float bestAlpha = 0.0;
  float bestInside = 1.0;   // 0=气泡正中心，1=边缘，用来做菲涅尔式的边缘发亮
  vec2 bestLocal = vec2(0.0);

  for (int idx = 0; idx < NUM_BUBBLES; idx++) {
    float fi = float(idx);

    // 每个气泡自己固定的水平位置/上升速度/起始相位，用不同的种子数字
    // 分别hash出来，保证每次运行、每一帧都是同一组值（不会到处乱跳）
    float xPos = mix(0.10, 0.90, hash1(fi * 12.9898 + 3.7)) * aspect;
    float speed = mix(0.045, 0.11, hash1(fi * 78.233 + 1.3));
    float phase = hash1(fi * 39.346 + 5.1);
    float wobbleAmt = mix(0.01, 0.035, hash1(fi * 4.7 + 2.2));
    float wobbleSpeed = mix(0.4, 0.9, hash1(fi * 9.1 + 0.6));

    // riseT 0~1循环：0=气泡刚从底部以下出现，1=飘到顶部以上、即将消失
    float riseT = fract(uTime * speed + phase);
    // 让气泡在真正进入/离开可视区域之前就已经在屏幕上下边界之外，
    // 这样进出画面才是连续的、不会在边界处突然蹦出来/消失
    float baseY = mix(-0.18, 1.18, riseT);

    // 不要让气泡走一条笔直的竖线：水平方向叠加两个不同频率/相位的正弦波
    // 而不是只有一个，摆动轨迹看起来就不那么规律、更像真实气泡那样乱飘；
    // 竖直方向也叠加一点小幅度的扰动，让上升速度显得有快有慢，不是匀速
    // 直线上升——扰动幅度刻意控制得比总上升距离（1.36）小得多，所以整体
    // 方向依然是稳稳地往上走，只是路径不是一条直线。
    float wobble = sin(uTime * wobbleSpeed + fi * 6.28) * wobbleAmt
                 + sin(uTime * wobbleSpeed * 2.3 + fi * 11.1) * wobbleAmt * 0.45;
    float vertWobble = sin(uTime * wobbleSpeed * 0.55 + fi * 3.3) * wobbleAmt * 0.5;

    vec2 center = vec2(xPos + wobble, baseY + vertWobble);
    float size = baseSizes[idx] * sizeScale;

    vec2 local = (uv - center) / size; // 归一化到"以气泡半径为1"的局部坐标，方便后面算高光/边缘
    float d = length(local);
    float edge = smoothstep(1.0, 0.85, d); // 软边圆形遮罩，0=在气泡外，1=在气泡内部

    if (edge > bestAlpha) {
      bestAlpha = edge;
      bestInside = d;
      bestLocal = local;
    }
  }

  if (bestAlpha <= 0.001) {
    fragColor = vec4(0.0); // 没有气泡覆盖的地方完全透明——这一路输出是独立的，
    return;                 // 之后想叠加到别的画面上就靠这个alpha通道
  }

  // 简单的"玻璃气泡"质感：中心偏暗透明、边缘（菲涅尔式）发亮，
  // 再加一个偏左上角的小高光点模拟反光
  vec3 bubbleTint = vec3(0.65, 0.85, 0.95);
  float rim = smoothstep(0.55, 1.0, bestInside);
  vec3 color = bubbleTint * mix(0.15, 0.9, rim);

  vec2 highlightPos = vec2(-0.35, 0.35);
  float highlight = smoothstep(0.32, 0.0, length(bestLocal - highlightPos));
  color += vec3(1.0) * highlight * 0.8;

  float alpha = bestAlpha * mix(0.35, 0.75, rim); // 玻璃感：整体半透明，边缘比中心更不透明一些

  fragColor = vec4(color * alpha, alpha); // 预乘alpha，方便以后合成到别的画面上不会有黑边
}
