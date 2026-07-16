---
name: douyin-reader
description: 读取抖音视频内容并提取文字版本。当用户提供抖音视频链接（douyin.com、v.douyin.com）并要求阅读、学习、总结、提取文字、获取字幕、转录内容时，必须使用此 skill。也适用于用户提到"抖音视频""抖音链接""这个视频""看看这个抖音"等场景。采用 iesdouyin SSR 解析（无需 Cookie/Key，实测可用）+ openai-whisper 本地转写，三层降级策略确保可靠获取视频内容和文字转写。
---

# 抖音视频内容提取器

专门解决抖音视频的程序化内容提取问题。抖音对自动化访问极不友好——视频地址使用复杂加密算法且频繁更新，直接请求几乎必定失败。此 skill 提供三层降级策略，确保在各种情况下都能尽可能获取视频内容。

## 核心策略：三层降级（2026-07-11 实测升级版）

**重要升级：** 经实测发现 iesdouyin SSR 解析方案无需 Cookie、无需 API Key 即可拿到无水印视频直链，比 yt-dlp（已失效）和 agent-browser（只能拿页面文字）都更强，提升为首选。

```
Layer 1: douyin_reader.py SSR 解析（首选，实测可用，无需 Cookie/Key）
    ↓ 失败
Layer 2: agent-browser 提取页面信息（降级，只能拿文字不能下载视频）
    ↓ 失败
Layer 3: WebSearch 搜索视频相关信息（最后手段）
```

## Layer 1: douyin_reader.py SSR 解析（首选）

**实测结论（2026-07-11）：** 通过 iesdouyin.com 分享页的 SSR 数据直接解析无水印视频直链，无需 Cookie、无需 API Key、无需浏览器。实测完整跑通解析→下载→音频抽取→whisper 转写全链路。

**原理：**
1. 短链跟随重定向拿到 video_id
2. 请求 `iesdouyin.com/share/video/{id}` 分享页
3. 正则抓 `window._ROUTER_DATA` 的 SSR JSON
4. 取 `play_addr.url_list[0]`，`playwm` 替换为 `play` 去水印
5. requests 下载 + ffmpeg 抽音频 + openai-whisper 转写

**依赖：**
```bash
pip install requests openai-whisper
# ffmpeg 系统安装：apt install ffmpeg / brew install ffmpeg
```

**执行命令：**
```bash
python3 /workspace/skills/douyin-reader/scripts/douyin_reader.py "<URL>" --json
```

**可选参数：**
- `--model small` — Whisper 模型（tiny/base/small/medium/large），默认 small
- `--language zh` — 音频语言，默认中文
- `--max-duration 300` — 转写最大时长（秒），默认 300（5 分钟）。长视频分段避免爆内存
- `--skip-transcribe` — 跳过语音转写，仅解析+下载
- `--output-dir DIR` — 指定输出目录

**输出格式（JSON）：**
- `title` / `author` — 元数据
- `like_count` / `comment_count` / `share_count` — 统计
- `transcription.full_text` — 完整转写文字
- `transcription.model` — 使用的模型

**Whisper 模型选择（实测对比，2026-07-11 沙箱 CPU）：**

| 模型 | 大小 | 速度 | 质量 | 备注 |
|------|------|------|------|------|
| tiny | 72MB | 3分钟音频/10.5s | 差，简繁混杂，错字多 | 快速预览 |
| small | 461MB | 1分钟音频/21.9s | 良，语义清晰，专有名词需校对 | **默认推荐** |
| medium | 1.5GB | - | - | OOM Killed，沙箱不可用 |

**专有名词校正：** whisper 对专有名词（如 GStack、Agent）识别有误，转写后建议用 LLM 做上下文校对：
```
请校对以下抖音视频转写文字，修正专有名词和明显错字，保持原意不变：
<转写文字>
```

**判断成功/失败：**
- 成功：获取到视频标题、作者、无水印下载链，且（如未 --skip-transcribe）转写出文字
- 失败：_ROUTER_DATA 未匹配（可能抖音改版）、下载非视频内容、转写报错

## Layer 2: agent-browser 提取页面信息（降级）

**使用场景：** Layer 1 的 SSR 解析失败（如抖音改版导致 _ROUTER_DATA 结构变更），但仍需获取页面可见文字信息。

**操作步骤：**
1. 使用 agent-browser 导航到视频 URL（浏览器能正确处理短链重定向）
2. 等待 3-5 秒让页面完全加载
3. 获取页面快照，提取标题、描述、作者、评论等

**限制：** 此方案**无法获取视频本身的语音转写**，只能获取页面上的文字信息。

## Layer 3: WebSearch 搜索相关信息（最后手段）

当以上两层全部失败时，通过搜索引擎查找视频相关信息。

**操作步骤：**
1. 从 URL 或上下文中提取视频标题关键词、作者名
2. 使用 WebSearch 搜索：`"<视频标题>" <作者名> 抖音`
3. 查找是否有文字版转载、截图、或他人整理的文字内容
4. 标注信息来源，提醒用户核对

## 完整工作流

收到抖音视频阅读需求时，按以下流程执行：

### Step 1: 识别输入

判断用户提供的链接是否为抖音视频：
- 域名包含 `douyin.com` 或 `v.douyin.com` 或 `iesdouyin.com`
- 或用户明确提到"抖音视频""抖音链接"

从用户输入中提取纯 URL（可能夹杂"复制此链接"等文字，脚本会自动正则提取）。

### Step 2: 执行 Layer 1（SSR 解析 + 下载 + 转写）

```bash
python3 /workspace/skills/douyin-reader/scripts/douyin_reader.py "<URL>" --json
```

如果需要快速预览（低质量转写）：加 `--model tiny --max-duration 120`
如果只需元数据不转写：加 `--skip-transcribe`

如果成功获取到视频标题和转写文字，跳到 Step 5。

### Step 3: 执行 Layer 2（agent-browser）

如果 Layer 1 失败：
1. 使用 agent-browser 导航到视频 URL
2. 等待 3-5 秒让页面完全加载
3. 获取页面快照，提取标题、描述、评论等

### Step 4: 执行 Layer 3（WebSearch）

如果 Layer 1 和 Layer 2 都失败，搜索相关信息。

### Step 5: 输出结果

向用户呈现视频内容，包含：
- **标题** / **作者**
- **统计数据**（点赞/评论/分享）
- **语音转写文字**（如通过 Layer 1 获取）
- **热门评论**（如通过 Layer 2 获取）
- **内容来源标注**（SSR 解析+转写 / 页面提取 / 搜索结果）

如果用户要求"学习""总结""提取知识点"，在输出内容后进一步：
- 提炼核心观点（3-5 个要点）
- 识别视频结构（开头钩子 → 主体内容 → 结尾行动号召）
- 标注可行动的信息

## 内容沉淀指导

当用户要求"内容沉淀"时，将提取的内容整理为结构化文档：

```
# [视频标题]

## 基本信息
- 作者：xxx
- 链接：xxx
- 数据：点赞 xx | 评论 xx | 分享 xx

## 核心内容
[页面描述或语音转写的精华提炼]

## 关键要点
1. [要点1]
2. [要点2]
3. [要点3]

## 可行动信息
- [具体可执行的建议或步骤]

## 来源标注
- 内容来源：[Layer 1 SSR 解析+转写 / Layer 2 页面提取 / Layer 3 搜索结果]
- 获取时间：[日期]
- ⚠️ 如仅获取页面信息未获取语音转写，标注"内容来源于页面文字，非视频语音转写"
- ⚠️ 如转写文字含专有名词错误，标注"已 LLM 校对"或"未校对，可能有错字"
```

## 失败处理

如果三层全部失败：

1. 明确告知用户："抖音视频内容获取失败，可能是反爬限制或视频不可用"
2. 提供替代方案：
   - "请在抖音 APP 中打开视频，手动复制文案内容给我"
   - "如果视频有文字版描述，请直接粘贴"
3. 不要静默返回空内容或伪造结果

## 常见问题

**Q: 为什么 SSR 解析是首选而不是 yt-dlp？**
A: 2026-07-11 实测，yt-dlp 对抖音短链接解析失败（重定向到首页），长链接需要 Cookie。而 iesdouyin SSR 解析无需 Cookie/Key，直接从分享页的 SSR JSON 拿到无水印直链，实测可用。SSR 方案借鉴自 yzfly/douyin-mcp-server v1.2.1（Apache 2.0）。

**Q: 能获取视频语音转写吗？**
A: 能。Layer 1 的 SSR 解析下载视频后，用 ffmpeg 抽音频 + openai-whisper 转写。实测 small 模型 1 分钟音频 21.9s 出 393 字文案，语义清晰。

**Q: 长视频怎么处理？**
A: 用 `--max-duration` 限制转写时长（默认 300 秒）。118 分钟的视频完整转写在 CPU 上不现实，默认只转写前 5 分钟。如需完整转写，建议配置 GPU 或使用云端 ASR（如配置 DASHSCOPE_API_KEY 用阿里云 paraformer-v2）。

**Q: 转写准确率如何？**
A: small 模型语义清晰，但专有名词有误（如"GStack"识别为"JSTARC"、"Agent"识别为"AZ"）。建议转写后用 LLM 做上下文校对。tiny 模型错字多不推荐生产使用。

**Q: 如何只获取元数据不做语音转写？**
A: 使用 `--skip-transcribe` 参数，仅解析+下载，不抽音频不转写。

**Q: 抖音改版导致 SSR 解析失效怎么办？**
A: 降级到 Layer 2（agent-browser 提取页面文字）。同时可关注 yzfly/douyin-mcp-server 的更新（解析逻辑相同，会跟进适配）。
