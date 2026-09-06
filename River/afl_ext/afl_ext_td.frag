// afl_ext 2017-2024 — "Very fast procedural ocean"
// MIT License
// Converted to TouchDesigner GLSL Multi TOP
// 本文件是 afl_ext.frag（原版程序化海洋 shader）移植到 TouchDesigner 的 GLSL Multi TOP 版本
// 主要改动：参数从宏定义/固定值改为可从TD外部传入的uniform；接入音频响度驱动波浪强度
// （原来这里还叠加了一张静态冰川背景图，应要求已经去掉；后来又把"全局统一的活跃度"
// 换成了"按屏幕位置采样历史带纹理"，让水面呈现真正的流动效果，而不是全屏同步切换，
// 见下方 uFlowRightToLeft 和 main() 里采样 sTD2DInputs[0] 的部分）

// All uniforms passed from TouchDesigner via Python setup
// 以下uniform变量都是由 setup_river_td.py 在TD里创建并赋值/绑定表达式的
uniform float uTime;          // 时间，绑定的是 absTime.seconds
uniform vec2 uResolution;     // 输出分辨率
uniform float uRiverSpeed;    // 河流整体流动速度
uniform float uWaveAmplitude; // 波浪振幅（波高）
uniform float uTurbulence;    // 湍流强度，控制波浪的扭曲/拖拽程度
uniform float uFlowRightToLeft; // 1.0=历史带新的声音从屏幕右边进来往左流，0.0=从左边进来往右流
uniform float uStillness;     // "持续无声"程度（0~1，由CPU侧的静音计时器算出）：activity 连续低于阈值
                               // 超过一段时间后才开始从0缓慢爬升到1，用来叠加额外的静谧感（减速+压暗，见main末尾）

// 输入0号槽位 = "活跃度历史带"纹理（由 gut_history 这个 Script CHOP 持续滚动
// 更新、经 CHOP to TOP 转换而来），横向代表"最近 HISTORY_SECONDS 秒"的活跃度
// 变化，R通道存的就是0~1的活跃度值。不再是全局的 uGutActivity 标量——每个
// 像素按自己在屏幕上的横向位置采样这条带子上对应的值，画面才会呈现真正的
// 流动，而不是全屏同一时刻统一变化。sTD2DInputs 由TD自动声明，这里不用重复声明。

out vec4 fragColor;

// Performance: 0 = fast (laptop), 1 = normal, 2 = high
// 画质档位：0=低配（笔记本电脑）流畅优先，1=正常，2=高画质（更多波浪叠加层数、更多光线步进步数）
#define QUALITY 1

#if QUALITY == 0
  #define ITERATIONS_RAYMARCH 6
  #define ITERATIONS_NORMAL 12
  #define RAYMARCH_STEPS 24
#elif QUALITY == 1
  #define ITERATIONS_RAYMARCH 10
  #define ITERATIONS_NORMAL 20
  #define RAYMARCH_STEPS 40
#else
  #define ITERATIONS_RAYMARCH 12
  #define ITERATIONS_NORMAL 36
  #define RAYMARCH_STEPS 64
#endif

#define CAMERA_HEIGHT 1.5 // 摄像机离水面的高度

// 计算单层波浪的高度值及其导数（与原版 afl_ext.frag 中的同名函数逻辑一致）
vec2 wavedx(vec2 position, vec2 direction, float frequency, float timeshift) {
  float x = dot(direction, position) * frequency + timeshift;
  float wave = exp(sin(x) - 1.0);
  float dx = wave * cos(x);
  return vec2(wave, -dx);
}

// 叠加多层波浪得到复合水面高度
// 相比原版增加了 speed（速度）、dragMult（拖拽强度）、freqGain（频率增益）三个可调参数，
// 这些参数最终都会受当地采样到的肠鸣音活跃度（历史带纹理）影响，让水面随声音变化
float getwaves(vec2 position, int iterations, float speed, float dragMult, float freqGain) {
  float wavePhaseShift = length(position) * 0.1;
  float iter = 0.0;
  float frequency = 1.0;
  float timeMultiplier = 2.0;
  float weight = 1.0;
  float sumOfValues = 0.0;
  float sumOfWeights = 0.0;
  float t = uTime * speed; // 用速度参数缩放时间，speed越大水面动得越快
  for(int i = 0; i < iterations; i++) {
    vec2 p = vec2(sin(iter), cos(iter));
    vec2 res = wavedx(position, p, frequency, t * timeMultiplier + wavePhaseShift);
    position += p * res.y * weight * dragMult; // dragMult越大，波浪扭曲/挤压效果越强（湍流感）
    sumOfValues += res.x * weight;
    sumOfWeights += weight;
    weight = mix(weight, 0.0, 0.2);
    frequency *= freqGain; // freqGain越大，高频细节波浪比例越高，水面看起来更"碎"更活跃
    timeMultiplier *= 1.07;
    iter += 1232.399963;
  }
  return sumOfValues / sumOfWeights;
}

// 光线步进求水面命中点，逻辑同原版，额外传入speed/dragMult/freqGain供getwaves使用
float raymarchwater(vec3 camera, vec3 start, vec3 end, float depth,
                    float speed, float dragMult, float freqGain) {
  vec3 pos = start;
  vec3 dir = normalize(end - start);
  for(int i = 0; i < RAYMARCH_STEPS; i++) {
    float height = getwaves(pos.xz, ITERATIONS_RAYMARCH, speed, dragMult, freqGain) * depth - depth;
    if(height + 0.01 > pos.y) {
      return distance(pos, camera);
    }
    pos += dir * (pos.y - height);
  }
  return distance(start, camera);
}

// 计算水面法线，逻辑同原版，额外传入speed/dragMult/freqGain
vec3 normal(vec2 pos, float e, float depth,
            float speed, float dragMult, float freqGain) {
  vec2 ex = vec2(e, 0);
  float H = getwaves(pos.xy, ITERATIONS_NORMAL, speed, dragMult, freqGain) * depth;
  vec3 a = vec3(pos.x, H, pos.y);
  return normalize(
    cross(
      a - vec3(pos.x - e, getwaves(pos.xy - ex.xy, ITERATIONS_NORMAL, speed, dragMult, freqGain) * depth, pos.y),
      a - vec3(pos.x, getwaves(pos.xy + ex.yx, ITERATIONS_NORMAL, speed, dragMult, freqGain) * depth, pos.y + e)
    )
  );
}

// 生成绕任意轴旋转的3x3旋转矩阵（罗德里格斯公式），逻辑同原版
mat3 createRotationMatrixAxisAngle(vec3 axis, float angle) {
  float s = sin(angle);
  float c = cos(angle);
  float oc = 1.0 - c;
  return mat3(
    oc * axis.x * axis.x + c,           oc * axis.x * axis.y - axis.z * s,  oc * axis.z * axis.x + axis.y * s,
    oc * axis.x * axis.y + axis.z * s,  oc * axis.y * axis.y + c,           oc * axis.y * axis.z - axis.x * s,
    oc * axis.z * axis.x - axis.y * s,  oc * axis.y * axis.z + axis.x * s,  oc * axis.z * axis.z + c
  );
}

// 根据屏幕UV计算摄像机射线方向
// 与原版不同：这里去掉了鼠标交互，改成固定的俯仰角（0.27是固定的"抬头/低头"参数），
// 因为这是自动播放的背景动画，不需要用户用鼠标控制视角
vec3 getRay(vec2 uv) {
  vec3 proj = normalize(vec3(uv.x, uv.y, 1.5));
  return createRotationMatrixAxisAngle(vec3(1.0, 0.0, 0.0), 0.5 + 1.5 * (0.27 * 2.0 - 1.0))
    * proj;
}

// 已去掉冰川背景：原来这里有个 getGlacierUV() 函数，专门把反射光线方向反推回
// 屏幕UV去采样冰川贴图、伪造水面倒影，现在冰川贴图整个不用了，这个函数也一并删掉。

// 射线与平面求交，逻辑同原版
float intersectPlane(vec3 origin, vec3 direction, vec3 point, vec3 normal) {
  return clamp(dot(point - origin, normal) / dot(direction, normal), -1.0, 9991999.0);
}

// 简化版大气散射近似，用来生成天空颜色，逻辑同原版
vec3 extra_cheap_atmosphere(vec3 raydir, vec3 sundir) {
  float special_trick = 1.0 / (raydir.y * 1.0 + 0.1);
  float special_trick2 = 1.0 / (sundir.y * 11.0 + 1.0);
  float raysundt = pow(abs(dot(sundir, raydir)), 2.0);
  float sundt = pow(max(0.0, dot(sundir, raydir)), 8.0);
  float mymie = sundt * special_trick * 0.2;
  vec3 suncolor = mix(vec3(1.0), max(vec3(0.0), vec3(1.0) - vec3(5.5, 13.0, 22.4) / 22.4), special_trick2);
  vec3 bluesky = vec3(5.5, 13.0, 22.4) / 22.4 * suncolor;
  vec3 bluesky2 = max(vec3(0.0), bluesky - vec3(5.5, 13.0, 22.4) * 0.002 * (special_trick + -6.0 * sundir.y * sundir.y));
  bluesky2 *= special_trick * (0.24 + raysundt * 0.24);
  return bluesky2 * (1.0 + 1.0 * pow(1.0 - raydir.y, 3.0));
}

// 太阳方向：与原版不同，这里固定了太阳高度（不再随时间上下移动），
// 因为背景动画需要长时间保持稳定的光照氛围，不需要模拟太阳升落
vec3 getSunDirection(float time) {
  return normalize(vec3(-0.0773502691896258, 0.5, 0.5773502691896258)); // fixed elevation, no longer animates up/down
}

// 获取指定方向的天空颜色
vec3 getAtmosphere(vec3 dir, float time) {
  return extra_cheap_atmosphere(dir, getSunDirection(time)) * 0.5;
}

// 太阳光斑：这里直接返回0，即不绘制太阳圆盘（画面里去掉了原版的太阳高光效果）
float getSun(vec3 dir, float time) {
  return 0.0; // sun disc removed
}

// ACES色调映射，逻辑同原版，把HDR颜色压缩到可显示范围并做gamma校正
vec3 aces_tonemap(vec3 color) {
  mat3 m1 = mat3(
    0.59719, 0.07600, 0.02840,
    0.35458, 0.90834, 0.13383,
    0.04823, 0.01566, 0.83777
  );
  mat3 m2 = mat3(
     1.60475, -0.10208, -0.00327,
    -0.53108,  1.10813, -0.07276,
    -0.07367, -0.00605,  1.07602
  );
  vec3 v = m1 * color;
  vec3 a = v * (v + 0.0245786) - 0.000090537;
  vec3 b = v * (0.983729 * v + 0.4329510) + 0.238081;
  return pow(clamp(m2 * (a / b), 0.0, 1.0), vec3(1.0 / 2.2));
}

// TouchDesigner GLSL Multi TOP 的主函数入口（相当于Shadertoy的mainImage）
void main()
{
  // "历史带"采样：按这个像素在屏幕上的横向位置，去输入0号槽位的历史带纹理上
  // 取出"当地"该有的活跃度，而不是用一个全局标量。uFlowRightToLeft 决定
  // 新的声音从哪一侧进来——纹理本身在CPU侧(gut_history)持续滚动更新，这里只
  // 是把屏幕位置固定映射到纹理坐标，不需要在shader里再算时间，画面自然流动。
  float screenX01 = gl_FragCoord.x / uResolution.x;
  float historyU = uFlowRightToLeft > 0.5 ? screenX01 : (1.0 - screenX01);
  float localActivity = texture(sTD2DInputs[0], vec2(historyU, 0.5)).r;

  // soft noise floor only — preserve proportional response above it
  // (previously 0.35-0.65 hard-gated activity into a near-binary switch)
  // 这里用平滑阶跃过滤掉很低的底噪（0.05~0.15之间平滑过渡），
  // 高于这个范围之后，activity 跟历史带采样值保持成比例响应
  // （旧版本用0.35~0.65做硬阈值，导致活跃度几乎变成"开/关"二值切换，效果生硬，现已改为线性响应）
  float activity = smoothstep(0.05, 0.15, localActivity);

  // speed decoupled from gut activity: constant background flow
  // (loudness -> flow speed is not the claim we make; loudness -> wave amplitude is)
  // 河流的流动速度不跟着瞬时音量变化，改为恒定的背景流速
  // （因为我们想表达的是"音量大小 -> 波浪振幅"，而不是"音量大小 -> 流动速度"，语义上更准确）
  // 但"持续很久没有肠鸣音"是另一回事——不是瞬时响度，而是一段时间尺度上的状态，
  // 用 uStillness 单独把流速也压低一些，作为"很久没有声音了"的额外视觉提示，
  // 跟上面那条决定并不矛盾（一个管瞬时响度，一个管长时间的静默状态）
  float speed    = uRiverSpeed * mix(1.0, 0.3, uStillness);
  // depth 下限：原来用2%，是为了不让水面"死板"，特意留一点残留的小起伏；
  // 但接入"历史带流动"之后，这点残留在安静区域里会变成一层若隐若现的波浪
  // 纹路，看起来像是叠在wave上面的鬼影，很难看。现在按要求改成彻底没有
  // 波纹——下限压到0.0008（视觉上完全平的镜面），不能设成真正的0，因为下面
  // scattering 项里有 (waterHitPos.y + depth) / depth 这样以 depth 作分母的
  // 除法，depth=0 会除零；0.0008 已经小到不会产生任何看得见的波纹几何。
  // ⚠️ 关于把"平静/波动"两端参数差距缩小、freqGain/dragMult上限调低：
  // 历史带流动起来之后发现一个新问题——即便activity数值本身在屏幕横向上是
  // 平滑过渡的（经过CPU侧的box blur），水面的"长相"却完全不是平滑过渡：
  // depth/dragMult/freqGain这几个参数会喂进getwaves()里一个带位置反馈的
  // 多层叠加公式（position += ... * dragMult，逐层累积），对这几个参数的
  // 变化是高度非线性的——哪怕活跃度只是渐变，水面的相位分布/细节疏密也会
  // 剧烈改变，画面上看起来就是硬邦邦的竖直分界线，不是真正的融合过渡。
  // 加上活跃度高的时候freqGain顶到1.24，经过ITERATIONS_NORMAL=20层累积
  // （1.24^20≈74倍基础频率），细节频率已经超出raymarch步数/法线采样能分辨
  // 的极限，视觉上就是那种规律的棋盘状碎纹（走样/aliasing），不是自然浪花。
  // 现在两处一起收紧：depth下限从几乎为0抬到0.06（平静时留一点极轻微的
  // 起伏，不再是纹丝不动的镜面——用来缩小两端反差，减轻分界线的突兀感；
  // 如果这点起伏又变成之前反馈过的"鬼影叠加感"，再往下调这个数字即可）；
  // freqGain上限从1.24压到1.15（大幅减少高频细节，是棋盘纹路的主因）；
  // dragMult下限抬一点、上限从0.42收到0.30，两头都往中间靠，让转折不那么剧烈。
  float depth    = uWaveAmplitude * mix(0.06, 1.0,  activity);
  float dragMult = 0.38 * uTurbulence * mix(0.05, 0.30, activity);
  float freqGain = mix(1.06, 1.15, activity);

  // 把TD传入的像素坐标转换成中心化、按宽高比修正过的uv（-1~1范围左右）
  vec2 uv = ((gl_FragCoord.xy / uResolution) * 2.0 - 1.0) * vec2(uResolution.x / uResolution.y, 1.0);

  vec3 ray = getRay(uv);

  vec3 C;
  if(ray.y >= 0.0) {
    // 射线朝上，看向天空：只渲染大气颜色（太阳光斑已被禁用，恒为0）
    C = getAtmosphere(ray, uTime * speed) + getSun(ray, uTime * speed);
  } else {
    // 射线朝下，会打到水面
    vec3 waterPlaneHigh = vec3(0.0, 0.0, 0.0);
    vec3 waterPlaneLow  = vec3(0.0, -depth, 0.0);

    // 摄像机位置随时间沿x轴平移，模拟持续向前流动的视角（0.2是原版遗留的平移速度系数）
    vec3 origin = vec3(uTime * speed * 0.2, CAMERA_HEIGHT, 1.0);

    // 求射线与水面上下边界的交点
    float highPlaneHit = intersectPlane(origin, ray, waterPlaneHigh, vec3(0.0, 1.0, 0.0));
    float lowPlaneHit  = intersectPlane(origin, ray, waterPlaneLow,  vec3(0.0, 1.0, 0.0));
    vec3 highHitPos = origin + ray * highPlaneHit;
    vec3 lowHitPos  = origin + ray * lowPlaneHit;

    // 光线步进求出真实水面命中点
    float dist = raymarchwater(origin, highHitPos, lowHitPos, depth, speed, dragMult, freqGain);
    vec3 waterHitPos = origin + ray * dist;

    // 计算命中点法线，并按距离平滑，避免远处闪烁噪点
    vec3 N = normal(waterHitPos.xz, 0.01, depth, speed, dragMult, freqGain);
    N = mix(N, vec3(0.0, 1.0, 0.0), 0.8 * min(1.0, sqrt(dist * 0.01) * 1.1));

    // 菲涅尔系数：视角越贴近水平，反射越强。原来这里没有上限——贴近地平线的
    // 掠射角，或者水面完全平静、没有波浪把反射方向打散时，反射率会冲到接近1，
    // 几乎变成一面纯镜子，把水本身那点深色"散射"颜色完全盖掉，看起来是一大片
    // 发白的雾/镜面而不是水（就是画面中间那片白色的真正成因）。上限先从0.6
    // 再压到0.4——0.6试完实测还是偏白，因为反射的天空本身亮度就很高，就算只占
    // 六成也压不住，所以进一步收紧，把更多比重让给水自己的深色。
    float fresnel = clamp(0.04 + (1.0 - 0.04) * (pow(1.0 - max(0.0, dot(-N, ray)), 5.0)), 0.0, 0.4);

    // 计算反射光线方向，并强制朝上（避免反射到不合理的方向）
    vec3 R = normalize(reflect(ray, N));
    R.y = abs(R.y);

    // 已去掉冰川背景：原来这里会把反射光线投影回冰川贴图UV、采样出一个
    // "伪造倒影"跟天空颜色按距离/边缘羽化混合，现在冰川贴图不用了，反射颜色
    // 直接就是反射方向上的天空颜色。
    // 天空在近地平线处本来就偏亮偏白，直接反射出来会是一条发白的带子，跟近处
    // 深蓝色的水面脱节、像换了个颜色。这里把反射颜色往水的固有色上带一部分，
    // 让远处的反射也带上水该有的蓝色，不是纯粹反射天空的样子。
    vec3 reflection = getAtmosphere(R, uTime * speed) + getSun(R, uTime * speed);
    vec3 waterTint = vec3(0.02, 0.09, 0.20);
    reflection = mix(reflection, waterTint, 0.45);
    // 次表面散射颜色：模拟水体本身在浅水处呈现的颜色。系数从0.1一路提到0.4，
    // 配合上面菲涅尔封顶一起，让水自身的深色在画面里更站得住、更容易被看见，
    // 不会不管哪个角度都被反射盖过去
    vec3 scattering = vec3(0.0293, 0.0698, 0.1717) * 0.4 * (0.2 + (waterHitPos.y + depth) / depth);

    // 按菲涅尔系数把反射和散射混合成最终水面颜色。反射的天空/冰川本身亮度较高，
    // 这里对水面额外乘一个0.8的整体压暗，避免反射部分在后面 * 2.0 做HDR提亮再
    // tonemap之后还是显得发白——只压暗水面这条支路，不影响上方天空的直接渲染
    C = (fresnel * reflection + scattering) * 0.8;
  }

  vec3 sceneColor = aces_tonemap(C * 2.0);

  // 已去掉冰川背景：原来这里会在地平线以上叠加一层静态冰川贴图，现在直接
  // 用程序化渲染出来的天空/水面颜色作为最终画面，不再叠加任何贴图。
  vec3 finalColor = sceneColor;

  // "持续很久没有肠鸣音"的额外视觉提示：原来这里还会整体降饱和度+压暗+混入
  // 一层浅灰白雾色，实测下来会把整个画面（连同天空、冰川）都拉向灰白色调，
  // 跟正常状态的深蓝色水看起来像换了个场景，颜色不统一。改成只保留河流流速
  // 变慢这一个信号（见上面 speed 那一行），不再改变颜色——安静的水面和有
  // 波浪的水面应该是同一套颜色，只是"动"的程度不同，不应该看起来判若两地。
  // uStillness 目前只被 speed 那一行用到；这里先留空，以后如果想再加别的
  // "持续无声"提示，从这里接。

  fragColor = vec4(finalColor, 1.0);
}
