# 伴读角色 SVG 规格（v3.7.1）

> 适用：预置角色设计、用户自定义 SVG 上传。本文档对照 `static/js/companion.js` 与 `static/style.css`
> 已实现代码实测提取。不满足硬性技术要求的 SVG 要么没动画、要么被消毒白名单剥掉。

## 1. 硬性技术要求（不满足 = 无法正常工作）

| 项 | 要求 | 原因 |
|---|---|---|
| 根元素 | `<svg class="companion-svg" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">` | 消毒器强制加 `companion-svg` 类、补 `viewBox`（缺则取 width/height 或 100）；CSS 用类名定位 |
| 尺寸基准 | viewBox 100×100 | 与 4 个预设统一；容器固定宽高缩放 |
| 主体色 | 填充用 CSS 变量 `var(--c-primary)` | 主题色功能只覆盖 `--c-primary`；不用变量则不响应换色 |
| 点缀色 | `var(--c-accent)` | 嘴/领结/天线/发光等细节 |
| 自包含 | 纯内联，无外部引用 | 渲染走 `innerHTML` 注入双挂载点（全局浮层 `#companion-char` + 研习工坊 `#mascot-stage-char`），外部资源加载不到 |
| 标签白名单 | 仅 `svg g circle rect path ellipse line polygon polyline text tspan defs linearGradient radialGradient stop clipPath mask` | 白名单外标签（`script`/`foreignObject`/`iframe`/`image`/`style`…）上传时被递归删除 |

## 2. 动画钩子（5 套预置 CSS 动画）

**SVG 部件级（唯一需要画师配合的）——眨眼：**

- 每只眼睛 = 一个 `<g class="char-eye">`，且**必须设置 `transform-origin` 为眼睛中心**：

```html
<g class="char-eye" style="transform-origin: 37px 40px;">
  <circle cx="37" cy="40" r="8" fill="#222"/>
  <circle cx="39.5" cy="37.5" r="3" fill="#fff"/>   <!-- 高光 -->
</g>
```

- CSS（style.css:6497）对 `.char-eye` 施加 `charBlink 4.2s`（scaleY 96%→0.1 闭合），配合 `transform-box: fill-box`。
- 不带 `transform-origin` → 眨眼轴心错位（眼睛会歪着闭）。

**容器级（画师无需配合）：**

| 动画 | 选择器 | 效果 |
|---|---|---|
| `companionIdle` 4s 常开 | `.companion-char` / `.mascot-stage-char` | 整角色 translateY ±4px 呼吸 |
| `companionJump` | 容器 `.is-happy` | 弹跳（制卡成功/复习 Good/测验完成/完形≥80%） |
| `companionWiggle` | 容器 `.is-wiggle` | 摇摆（复习 Hard） |
| `companionDroop` | 容器 `.is-sad` | 下沉（预留，当前未触发） |

## 3. 图层约定（只需两类结构性钩子）

```html
<g class="char-body">            <!-- 身体：耳/躯干/翅/爪/腿全部塞这里 -->
  …
</g>
<g class="char-eyes-wrap">       <!-- 眼睛外层 -->
  <g class="char-eye" style="transform-origin: …">…</g>
  <g class="char-eye" style="transform-origin: …">…</g>
</g>
```

- `.char-body`、`.char-eyes-wrap` 是结构性分组（供后续交互/动作控制扩展），当前无独立 CSS 规则。
- **头/四肢/配件不必单独分层**——预设里分了只是绘图组织，不参与动画。
- 自定义 SVG 缺 `.char-eye` 类 → 只保留容器级浮动/跳跳，眨眼降级跳过。

## 4. 风格参考（房子风格，软性偏好）

预设 4 角色（Eule 猫头鹰 / Katze 猫 / Fuchs 狐 / Roboter 机甲）统一：

- **扁平几何**：circle / ellipse / polygon / path 构成，除 owl 腹部一个低透明度 radialGradient 外无渐变
- **粗墨线描边**：`stroke="#222"`，width 1.5–2.5，`stroke-linejoin="round"`
- **双色 + 白肚**：`var(--c-primary)` 主体 + `var(--c-accent)` 点缀 + `#faf8f5` 白肚/白颊 + `#222` 深色细节
- 风格不一致也能跑，但与预设站一起视觉突兀；建议贴合

## 5. 可复制骨架模板

```html
<svg class="companion-svg" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
  <g class="char-body">
    <!-- 耳朵/触角/翅膀等 -->
    <!-- 躯干：fill 用 var(--c-primary) -->
    <!-- 白肚/白颊：fill #faf8f5 -->
    <!-- 细节点缀：fill / stroke 用 var(--c-accent) 与 #222 -->
  </g>
  <g class="char-eyes-wrap">
    <g class="char-eye" style="transform-origin: 36px 44px;"><!-- 左眼 --></g>
    <g class="char-eye" style="transform-origin: 64px 44px;"><!-- 右眼 --></g>
  </g>
  <!-- 嘴/鼻子：var(--c-accent) 或 #222 -->
</svg>
```

## 6. 上传合法性（自定义 SVG 上传，companion.js `sanitizeSvg` / `handleSvgUpload`）

- 扩展名 `.svg`（或 mime `image/svg+xml` / `text/xml`），大小 **≤ 64KB**
- 解析：`DOMParser` 以 `image/svg+xml` 解析，非合法 XML 直接拒绝
- **属性剥除**：`on*` 事件属性；`javascript:` / `vbscript:` / `data:text/html` / `expression(` 协议；非 `#` 开头的 `href` / `xlink:href`（只允许本地渐变 ID 引用）；style 属性含 `url(` / `expression` / `javascript` / `@import` / `-moz-binding`
- 根 `<svg>`：`on*` 与危险协议剥除，强制补 `companion-svg` 类与 `viewBox`
- 存储：消毒后文本存 `localStorage.delector_companion_custom_svg`；刷新时再次过 `sanitizeSvg` 恢复
- **配色限制**：自定义角色 primary 固定 `#15140f`、accent 固定 `#ed6f5c`——只有 SVG 里用了 `var(--c-primary)` / `var(--c-accent)` 的地方会随主题色变

## 参考实现
- 角色定义：`static/js/companion.js` `CHARACTERS`（4 预设模板）
- 消毒器：`static/js/companion.js` `sanitizeSvg`（companion.js:272）
- 动画：`static/style.css` 6497–6545（keyframes）与 6025+（companion 段）
