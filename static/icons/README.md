# static/icons —— 图标来源与用法

## 来源与版本

| 项 | 值 |
| --- | --- |
| 图标库 | [Lucide](https://lucide.dev) |
| 发行包 | `lucide-static` **v0.468.0** |
| 获取地址 | `https://unpkg.com/lucide-static@0.468.0/icons/<name>.svg` |
| 许可 | **ISC**，全文见 [LICENSE-lucide.txt](./LICENSE-lucide.txt) |
| 修改 | 无。仅取 path 数据，未改坐标、未改描边参数 |

本目录只收录 DeLector 实际用到的图标，**不复制整套图标库、不引入 npm 依赖、不使用 CDN**。

## 收录清单（12 个）

| symbol id | 图标名 | 用途 |
| --- | --- | --- |
| `ui-ico-volume-2` | volume-2 | 朗读 / 发声开启 |
| `ui-ico-volume-x` | volume-x | 伴读发声静音态 |
| `ui-ico-play` | play | 播放 |
| `ui-ico-pause` | pause | 暂停 |
| `ui-ico-skip-back` | skip-back | 上一句 |
| `ui-ico-skip-forward` | skip-forward | 下一句 |
| `ui-ico-rotate-ccw` | rotate-ccw | 重听 / 重播当前句 |
| `ui-ico-trash-2` | trash-2 | 删除文章 / 作文 / 快照 |
| `ui-ico-upload` | upload | 上传自定义角色 SVG |
| `ui-ico-sparkles` | sparkles | 自定义角色 |
| `ui-ico-chevron-left` | chevron-left | 伴读面板「上一句」步进 |
| `ui-ico-chevron-right` | chevron-right | 伴读面板「下一句」步进 |

## 用法

`lucide-sprite.svg` 是**同文档引用**的 sprite：构建时由 `tools/build_index_html.py`
通过 `<!-- @include: icons/lucide-sprite.svg -->` 内联进 `static/index.html`，
`static/german/workbench.html` 内联同一份 symbol 定义。

```html
<svg class="ui-ico" aria-hidden="true" focusable="false">
  <use href="#ui-ico-volume-2"></use>
</svg>
```

- 尺寸走 `.ui-ico { width:1em; height:1em }`，随按钮 `font-size` 缩放；
- 颜色走 `currentColor`，不需要为图标单独声明颜色；
- 图标一律 `aria-hidden="true"`，可访问名由宿主按钮的可见文字或 `aria-label` 提供
  —— 遵循不变量 I1「任何字形都不得是意义的唯一载体」：图标只做冗余通道，
  不承担唯一表意。

**注意**：不要改成 `<use href="/static/icons/lucide-sprite.svg#id">` 外链形式。
Android 端以 `file:///android_asset/` 加载页面，跨文档 `<use>` 在 file:// 下不可靠；
同文档引用是唯一在 Web / Android 两端都成立的形式。

## 新增图标

1. 从 `lucide-static@<版本>/icons/<name>.svg` 取 path；
2. 追加到 `lucide-sprite.svg`，id 用 `ui-ico-<name>`；
3. 同步更新上表与 [LICENSE-lucide.txt](./LICENSE-lucide.txt) 里的文件清单；
4. 升级版本时整份替换并在此记录新版本号。
