# 用户操作指南

> 本指南面向直接使用 DeLector 的学习者，按真实界面入口讲清"从哪进、点什么、得到什么"。
> 功能口径来自 [FEATURES.md](FEATURES.md)（v5.22.1 冻结快照），逐版变化以 [CHANGELOG.md](../CHANGELOG.md) 为准。
> 本文所引数字均逐字取自 FEATURES.md，并在括号内标注出处，不另造统计值。

## 一分钟认识 DeLector

DeLector 是一套本地优先的德语精读与备考工作台：把一篇德语短文拆成可点的词、可展开的句法树与可复习的卡片，服务于歌德（A1–C1）、德福（TestDaF）与 DSH 备考。三个入口能力：

- **读得懂**：正文自动标注 CEFR 词阶，点词出释义、冠词与复数；长难句一键展开拓扑五场域与从句语法树。
- **记得住**：生词与语法点进 FSRS 卡盒，按遗忘曲线安排复习；写作台、备考工坊与影子跟读分别覆盖输出、应试与听读。
- **数据在自己手里**：桌面/便携版默认把词库与进度放在本地用户目录，Android 版单机运行，不依赖账号。

<img src="docs/images/readme-home-hero.jpg" alt="首页首屏：长句五场域拆解与实时拓扑演示" />

## 安装与启动

普通用户无需安装 Python：

- **Windows**：从 [Releases](https://github.com/ROM4n2/DeLector/releases) 下载 ZIP，解压后双击 `DeLector.exe`；Win11 自带 WebView2，Win10 需先装 WebView2 运行时。也提供安装版（免管理员 per-user 安装，未做代码签名，SmartScreen 可能提示"未知发布者"）。
- **macOS / Linux**：下载 TAR.GZ，解压后运行目录内的 `./DeLector`（若提示无执行权限先 `chmod +x DeLector`）。
- **Android**：下载 APK 安装，内嵌 Python 与 spaCy 离线模型；含界面改动的版本必须**覆盖安装**才生效。

开发者从源码运行：创建 Python 3.11 虚拟环境、按 `requirements.lock.txt` 安装依赖、下载德语模型 `de_core_news_sm`，再执行 `python start.py`，浏览器打开 `http://localhost:8000`。完整命令与打包细节见 [README.md](../README.md) 与 [docs/agents/ops.md](agents/ops.md)。

首次启动若要用 AI 深度解析，在右上角"设置"中填写 DeepSeek API Key 并做连通性测试；不填也能正常使用词库、句法、卡盒与跟读，只是 AI 相关能力返回精简提示（见"常见问题与限制"）。

## 核心功能操作

### 精读台

入口：首页"文章列表"选一篇文稿进入阅读页（`static/views/home.html` → `static/views/reader.html`）。

1. 打开文章后，顶部词阶热力条按 A1–C1 显示占比与预计耗时；点某个级别即可只高亮该级词汇、滤掉其余干扰。
2. 点正文中的词，弹出中文释义、冠词（der/die/das）与复数；内置离线词库约 4300+ 歌德核心词（来源：FEATURES.md），无需联网。
3. 选中句子片段可上黄/绿/蓝/粉四色荧光并写便签；需要纸质材料时用"精读指南导出"生成打印级 HTML。
4. 遇到长难句，点句末"句法"展开五场域与从句树（下一节）。

<img src="docs/images/readme-reader-b2.jpg" alt="沉浸阅读器：CEFR 难度光谱与考点高亮" />

### 五场域句法

入口：阅读页句末"句法"抽屉，或首页"句法实验室"（`static/views/reader.html` 的 `satz-lab`、`static/views/home.html`）。

1. 展开后，句子按**前场 VF / 左框 LK / 中场 MF / 右框 RK / 后场 NF** 五场域分色切分，直观看出德语动词二位（V2）与动词置后（VL）语序（五场域名来自 FEATURES.md）。
2. 抽屉列出 **5 大从句 AST**（状语从句、关系从句、带 zu 不定式、被动与虚拟式框形、主句核心干，来源：FEATURES.md）；点某个节点，正文对应从句出现光圈高亮。
3. 需要积累语法点时用"一键制 Anki 语法卡"，把从句类型、引导词与句式公式存进卡盒。

### 影子跟读

入口：阅读页播放条（`static/views/reader.html` 的 `btn-reader-play`）。

1. 点播放，按句定位朗读；可单句循环、调速并看波形动效，用于德福听力与口语的影子跟读（Shadowing）。
2. 发音走 Edge 神经网络语音；无网络时自动降级到浏览器内置 TTS，保证离线仍能跟读。
3. 生成过的音频分句缓存在本地，再次播放零延迟。

### FSRS 卡盒

入口：卡盒页（`static/views/cards.html`），进度台账见 `static/views/progress.html`。

1. 卡盒区分词汇卡与语法卡，3D 翻牌显示冠词、复数、例句或语法公式；"待学 / 待复习 / 已掌握"分段切换。
2. 复习用 FSRS（DSR）自适应排程，按 90% 目标留存率算下一轮天数，四个按钮显示"重来 / 困难 / 良好 / 简单"各自的排程天数（来源：FEATURES.md）。
3. 可在卡盒批量制卡、做测验，或一键导出 `.apkg` 导入 Anki Desktop / AnkiMobile / AnkiDroid。
4. 在台账页看 A1–C1 掌握度阶梯、30 天留存折线，用"一键备份与还原"迁移数据（还原为整体覆盖，请先导出备份）。

### 备考工坊

入口：备考页（`static/views/exam.html`）与写作工作台（`static/views/writer.html`）。

1. 备考页按歌德 A1 的听说读写、词汇与长难句分模块；用到约 702 个官方考纲词（来源：FEATURES.md），可按 15 大生活主题切片筛选。
2. 口语部分提供 Theil 2 主题抽词与 Theil 3 情景卡，翻卡对照提问与应答；另有德福 C-Test 与完形填空实战。
3. 写作工作台是内联 IDE：行内实时语法诊断、Inlay Hints 与句子级 AI 润色并排审查，适合打磨应试作文。

## 常见问题与限制

- **AI 解析没反应**：右上角"设置"未配置 API Key 时，`/api/ai/note-assist` 会返回精简提示而非深度解析——内容为"精读重点：<所选文本>"加一条"请在设置中配置 API Key"的提示（`delector/routes/articles.py` 的实际行为）。填入有效 Key 后即走真实模型，费用由所用服务计。
- **Win10 启动报错退出**：多为缺 WebView2 运行时（Win11 自带）；安装系统 WebView2 后再启动。
- **Windows 安装版被 SmartScreen 拦**：安装包未做代码签名，选"更多信息 → 仍要运行"；安装版与便携版数据同在 `%LOCALAPPDATA%\DeLector`，卸载不会删除。
- **Android 升级后界面没变**：含界面改动的版本必须覆盖安装，顶栏 `System · vX.Y.Z` 可判断前端资源是否刷新。
- **应用内更新未端到端验证**：Windows / Android / Linux 四条路径只有构建与单测覆盖，未在真实旧机上跑通完整链路；失败时到 Releases 页手动下载。macOS 不参与应用内更新。
- **生词卡出现重复**：写入已改为幂等，但未建唯一索引、存量重复未合并，读侧按"共 N 张"去重显示。
- **真机与低端机未覆盖**：Android x86_64 模拟器做过覆盖安装与版本检查，arm64 真机点检、低端机内存与 iOS Safari 未验证，不要把模拟器结果当真机结论。
- 其他平台与版本细节见 [README.md](../README.md) 的"已知限制"，逐版变化见 [CHANGELOG.md](../CHANGELOG.md)。
