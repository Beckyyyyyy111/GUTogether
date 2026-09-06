// afl_ext 2017-2024
// MIT License

// Use your mouse to move the camera around! Press the Left Mouse Button on the image to look around!
// 用鼠标拖动可以旋转视角！在画面上按住鼠标左键即可环顾四周！
// 这是原版 Shadertoy 程序化海洋 shader（未接入 TouchDesigner，独立可运行版本）

#define DRAG_MULT 0.38 // changes how much waves pull on the water | 控制波浪对水面的"拖拽"强度，值越大波形越扭曲夸张
#define WATER_DEPTH 1.0 // how deep is the water | 水的深度（上下两层水面之间的距离）
#define CAMERA_HEIGHT 1.5 // how high the camera should be | 摄像机离水面的高度
#define ITERATIONS_RAYMARCH 12 // waves iterations of raymarching | 光线步进（raymarch）时叠加的波浪层数，越多越精细但越耗性能
#define ITERATIONS_NORMAL 36 // waves iterations when calculating normals | 计算法线时叠加的波浪层数，通常比raymarch用的层数多，法线需要更精细

#define NormalizedMouse (iMouse.xy / iResolution.xy) // normalize mouse coords | 把鼠标坐标归一化到 0~1 范围

// Calculates wave value and its derivative,
// for the wave direction, position in space, wave frequency and time
// 计算某个方向上单个波浪的高度值及其导数（斜率）
// 参数：position=空间位置，direction=波浪传播方向，frequency=频率，timeshift=随时间的相位偏移
vec2 wavedx(vec2 position, vec2 direction, float frequency, float timeshift) {
  float x = dot(direction, position) * frequency + timeshift;
  float wave = exp(sin(x) - 1.0); // 用 exp(sin(x)-1) 让波峰更尖锐、波谷更平缓，模拟真实水波形状
  float dx = wave * cos(x); // 对波形求导，用于后面计算法线和波浪对位置的"拖拽"效果
  return vec2(wave, -dx); // x分量=波高，y分量=负导数
}

// Calculates waves by summing octaves of various waves with various parameters
// 叠加多个不同方向、频率、相位的波浪（类似分形噪声的多倍频叠加），得到最终的复合水面高度
float getwaves(vec2 position, int iterations) {
  float wavePhaseShift = length(position) * 0.1; // this is to avoid every octave having exactly the same phase everywhere | 避免每一层波浪在各处的相位都完全相同，产生更自然的效果
  float iter = 0.0; // this will help generating well distributed wave directions | 用来生成分布均匀、看起来随机的波浪方向
  float frequency = 1.0; // frequency of the wave, this will change every iteration | 波浪频率，每次迭代都会变化
  float timeMultiplier = 2.0; // time multiplier for the wave, this will change every iteration | 时间倍率，每次迭代都会变化，让不同层的波浪运动速度不同
  float weight = 1.0;// weight in final sum for the wave, this will change every iteration | 该层波浪在最终叠加结果中的权重，会逐层衰减
  float sumOfValues = 0.0; // will store final sum of values | 累加所有波浪层的加权高度值
  float sumOfWeights = 0.0; // will store final sum of weights | 累加所有权重，最后用来归一化
  for(int i=0; i < iterations; i++) {
    // generate some wave direction that looks kind of random
    // 用 sin/cos 生成一个看起来随机、实际上是确定性的波浪方向
    vec2 p = vec2(sin(iter), cos(iter));

    // calculate wave data
    // 计算这一层波浪的高度和导数
    vec2 res = wavedx(position, p, frequency, iTime * timeMultiplier + wavePhaseShift);

    // shift position around according to wave drag and derivative of the wave
    // 根据波浪的导数和拖拽系数，扰动采样位置，让水面看起来相互挤压、形成尖锐的波峰（类似Domain Warping技巧）
    position += p * res.y * weight * DRAG_MULT;

    // add the results to sums
    // 把这一层的结果累加到总和里
    sumOfValues += res.x * weight;
    sumOfWeights += weight;

    // modify next octave ;
    // 为下一层波浪调整参数：权重衰减、频率增大、时间倍率增大
    weight = mix(weight, 0.0, 0.2);
    frequency *= 1.18;
    timeMultiplier *= 1.07;

    // add some kind of random value to make next wave look random too
    // 给方向种子加一个较大的数，让下一层波浪方向也显得随机
    iter += 1232.399963;
  }
  // calculate and return
  // 用加权和除以权重和，得到归一化后的最终波高（0~1范围左右）
  return sumOfValues / sumOfWeights;
}

// Raymarches the ray from top water layer boundary to low water layer boundary
// 从水面上边界向下边界做光线步进，找到光线与波浪表面的实际交点
float raymarchwater(vec3 camera, vec3 start, vec3 end, float depth) {
  vec3 pos = start;
  vec3 dir = normalize(end - start);
  for(int i=0; i < 64; i++) {
    // the height is from 0 to -depth
    // 波浪高度范围是从 0 到 -depth
    float height = getwaves(pos.xz, ITERATIONS_RAYMARCH) * depth - depth;
    // if the waves height almost nearly matches the ray height, assume its a hit and return the hit distance
    // 如果波浪高度和光线当前高度足够接近，就认为命中了水面，返回命中距离
    if(height + 0.01 > pos.y) {
      return distance(pos, camera);
    }
    // iterate forwards according to the height mismatch
    // 根据高度差继续沿光线方向前进
    pos += dir * (pos.y - height);
  }
  // if hit was not registered, just assume hit the top layer,
  // this makes the raymarching faster and looks better at higher distances
  // 如果始终没有命中，就直接当作命中了水面最上层，这样处理远处水面时更快、效果也更好
  return distance(start, camera);
}

// Calculate normal at point by calculating the height at the pos and 2 additional points very close to pos
// 通过计算目标点及其附近两个点（沿x、y方向偏移e）的波高，用叉乘求出该点的法线（有限差分法）
vec3 normal(vec2 pos, float e, float depth) {
  vec2 ex = vec2(e, 0);
  float H = getwaves(pos.xy, ITERATIONS_NORMAL) * depth;
  vec3 a = vec3(pos.x, H, pos.y);
  return normalize(
    cross(
      a - vec3(pos.x - e, getwaves(pos.xy - ex.xy, ITERATIONS_NORMAL) * depth, pos.y),
      a - vec3(pos.x, getwaves(pos.xy + ex.yx, ITERATIONS_NORMAL) * depth, pos.y + e)
    )
  );
}

// Helper function generating a rotation matrix around the axis by the angle
// 辅助函数：根据给定的旋转轴和角度，生成一个3x3旋转矩阵（罗德里格斯旋转公式）
mat3 createRotationMatrixAxisAngle(vec3 axis, float angle) {
  float s = sin(angle);
  float c = cos(angle);
  float oc = 1.0 - c;
  return mat3(
    oc * axis.x * axis.x + c, oc * axis.x * axis.y - axis.z * s, oc * axis.z * axis.x + axis.y * s,
    oc * axis.x * axis.y + axis.z * s, oc * axis.y * axis.y + c, oc * axis.y * axis.z - axis.x * s,
    oc * axis.z * axis.x - axis.y * s, oc * axis.y * axis.z + axis.x * s, oc * axis.z * axis.z + c
  );
}

// Helper function that generates camera ray based on UV and mouse
// 辅助函数：根据屏幕UV坐标和鼠标位置，计算出摄像机在该像素方向上发出的射线
vec3 getRay(vec2 fragCoord) {
  vec2 uv = ((fragCoord.xy / iResolution.xy) * 2.0 - 1.0) * vec2(iResolution.x / iResolution.y, 1.0);
  // for fisheye, uncomment following line and comment the next one
  // 如果想要鱼眼效果，取消下面这行的注释，并注释掉再下面那行
  //vec3 proj = normalize(vec3(uv.x, uv.y, 1.0) + vec3(uv.x, uv.y, -1.0) * pow(length(uv), 2.0) * 0.05);
  vec3 proj = normalize(vec3(uv.x, uv.y, 1.5));
  if(iResolution.x < 600.0) {
    // 小屏幕/低分辨率时直接返回投影方向，不做鼠标交互旋转（简化处理）
    return proj;
  }
  // 根据鼠标的水平/垂直位置，分别绕Y轴（左右看）和X轴（上下看）旋转射线方向
  return createRotationMatrixAxisAngle(vec3(0.0, -1.0, 0.0), 3.0 * ((NormalizedMouse.x + 0.5) * 2.0 - 1.0))
    * createRotationMatrixAxisAngle(vec3(1.0, 0.0, 0.0), 0.5 + 1.5 * (((NormalizedMouse.y == 0.0 ? 0.27 : NormalizedMouse.y) * 1.0) * 2.0 - 1.0))
    * proj;
}

// Ray-Plane intersection checker
// 计算射线与平面的交点距离（射线-平面求交）
float intersectPlane(vec3 origin, vec3 direction, vec3 point, vec3 normal) {
  return clamp(dot(point - origin, normal) / dot(direction, normal), -1.0, 9991999.0);
}

// Some very barebones but fast atmosphere approximation
// 一个非常简化但速度很快的大气散射近似算法，用来模拟天空颜色
vec3 extra_cheap_atmosphere(vec3 raydir, vec3 sundir) {
  //sundir.y = max(sundir.y, -0.07);
  float special_trick = 1.0 / (raydir.y * 1.0 + 0.1); // 视线越接近地平线，这个值越大，用来加强地平线附近的散射效果
  float special_trick2 = 1.0 / (sundir.y * 11.0 + 1.0); // 太阳高度相关的系数，太阳越低这个值越大（日落时天空更红）
  float raysundt = pow(abs(dot(sundir, raydir)), 2.0); // 视线方向与太阳方向的夹角相关量
  float sundt = pow(max(0.0, dot(sundir, raydir)), 8.0); // 用于突出太阳周围的"米氏散射"光晕
  float mymie = sundt * special_trick * 0.2; // 米氏散射近似值（当前未直接用到返回值里）
  vec3 suncolor = mix(vec3(1.0), max(vec3(0.0), vec3(1.0) - vec3(5.5, 13.0, 22.4) / 22.4), special_trick2); // 太阳颜色随高度变化（日落变橙红色）
  vec3 bluesky= vec3(5.5, 13.0, 22.4) / 22.4 * suncolor; // 基础蓝天颜色
  vec3 bluesky2 = max(vec3(0.0), bluesky - vec3(5.5, 13.0, 22.4) * 0.002 * (special_trick + -6.0 * sundir.y * sundir.y));
  bluesky2 *= special_trick * (0.24 + raysundt * 0.24);
  return bluesky2 * (1.0 + 1.0 * pow(1.0 - raydir.y, 3.0)); // 地平线附近再额外增强亮度
}

// Calculate where the sun should be, it will be moving around the sky
// 计算太阳当前应该在的方向，太阳会随时间在天空中缓慢移动
vec3 getSunDirection() {
  return normalize(vec3(-0.0773502691896258 , 0.5 + sin(iTime * 0.2 + 2.6) * 0.45 , 0.5773502691896258));
}

// Get atmosphere color for given direction
// 获取指定方向上的天空（大气）颜色
vec3 getAtmosphere(vec3 dir) {
   return extra_cheap_atmosphere(dir, getSunDirection()) * 0.5;
}

// Get sun color for given direction
// 获取指定方向上的太阳亮度（用于绘制太阳光斑）
float getSun(vec3 dir) {
  return pow(max(0.0, dot(dir, getSunDirection())), 720.0) * 210.0;
}

// Great tonemapping function from my other shader: https://www.shadertoy.com/view/XsGfWV
// 色调映射（Tonemapping）函数，来自作者的另一个shader，用ACES算法把高动态范围颜色压缩到可显示范围，并做gamma校正
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

// Main
// 主函数：Shadertoy 的入口，计算每个像素的最终颜色
void mainImage(out vec4 fragColor, in vec2 fragCoord) {
  // get the ray
  // 根据当前像素坐标算出摄像机射线方向
  vec3 ray = getRay(fragCoord);
  if(ray.y >= 0.0) {
    // if ray.y is positive, render the sky
    // 如果射线朝上（y分量为正），说明看向天空，直接渲染天空+太阳
    vec3 C = getAtmosphere(ray) + getSun(ray);
    fragColor = vec4(aces_tonemap(C * 2.0),1.0);
    return;
  }

  // now ray.y must be negative, water must be hit
  // 到这里说明射线朝下，一定会打到水面
  // define water planes
  // 定义水面的上下两层边界平面
  vec3 waterPlaneHigh = vec3(0.0, 0.0, 0.0);
  vec3 waterPlaneLow = vec3(0.0, -WATER_DEPTH, 0.0);

  // define ray origin, moving around
  // 定义射线起点（摄像机位置），会随时间平移，模拟摄像机在水面上方缓慢移动
  vec3 origin = vec3(iTime * 0.2, CAMERA_HEIGHT, 1);

  // calculate intersections and reconstruct positions
  // 计算射线与上下两层水面平面的交点，重建出对应的三维位置
  float highPlaneHit = intersectPlane(origin, ray, waterPlaneHigh, vec3(0.0, 1.0, 0.0));
  float lowPlaneHit = intersectPlane(origin, ray, waterPlaneLow, vec3(0.0, 1.0, 0.0));
  vec3 highHitPos = origin + ray * highPlaneHit;
  vec3 lowHitPos = origin + ray * lowPlaneHit;

  // raymatch water and reconstruct the hit pos
  // 在上下两层平面之间做光线步进，找到真实水面命中点
  float dist = raymarchwater(origin, highHitPos, lowHitPos, WATER_DEPTH);
  vec3 waterHitPos = origin + ray * dist;

  // calculate normal at the hit position
  // 计算命中点处的水面法线
  vec3 N = normal(waterHitPos.xz, 0.01, WATER_DEPTH);

  // smooth the normal with distance to avoid disturbing high frequency noise
  // 距离越远，法线越趋向纯竖直方向，避免远处出现干扰性的高频噪点闪烁
  N = mix(N, vec3(0.0, 1.0, 0.0), 0.8 * min(1.0, sqrt(dist*0.01) * 1.1));

  // calculate fresnel coefficient
  // 计算菲涅尔系数（视角越接近水平，反射越强）
  float fresnel = (0.04 + (1.0-0.04)*(pow(1.0 - max(0.0, dot(-N, ray)), 5.0)));

  // reflect the ray and make sure it bounces up
  // 计算反射光线方向，并确保反射方向朝上（避免反射到水面下方不合理的地方）
  vec3 R = normalize(reflect(ray, N));
  R.y = abs(R.y);

  // calculate the reflection and approximate subsurface scattering
  // 计算反射颜色（天空+太阳），以及近似的次表面散射颜色（水体本身的颜色）
  vec3 reflection = getAtmosphere(R) + getSun(R);
  vec3 scattering = vec3(0.0293, 0.0698, 0.1717) * 0.1 * (0.2 + (waterHitPos.y + WATER_DEPTH) / WATER_DEPTH);

  // return the combined result
  // 把反射和散射按菲涅尔系数混合，得到最终颜色，再做色调映射输出
  vec3 C = fresnel * reflection + scattering;
  fragColor = vec4(aces_tonemap(C * 2.0), 1.0);
}
