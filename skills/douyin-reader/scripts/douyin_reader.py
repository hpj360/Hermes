#!/usr/bin/env python3
"""
抖音视频内容提取器（SSR 解析版）

核心改动（2026-07-11 实测升级）：
- 下载：yt-dlp（已失效，需 Cookie）→ iesdouyin SSR 解析（无需 Cookie/Key，实测可用）
- 转写：faster-whisper → openai-whisper（tiny/small 实测通过，medium+ 会 OOM）
- 长视频：增加 --max-duration 限制转写时长，避免爆内存

原理：iesdouyin.com/share/video/{id} 的 SSR 页面含 window._ROUTER_DATA JSON，
直接取 play_addr.url_list[0] 并把 playwm 替换为 play 即得无水印直链。
借鉴 yzfly/douyin-mcp-server v1.2.1 的解析逻辑（Apache 2.0）。

用法：
  python3 douyin_reader.py "<URL>" [--output-dir DIR] [--model MODEL] [--json]
  python3 douyin_reader.py "<URL>" --skip-transcribe  # 只下载+元数据
  python3 douyin_reader.py "<URL>" --max-duration 300  # 只转写前 5 分钟
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

import requests


# 移动端 UA（iesdouyin 对 UA 不严格，但移动端更稳定）
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) EdgiOS/121.0.2277.107 "
        "Version/17.0 Mobile/15E148 Safari/604.1"
    )
}


def run_cmd(cmd, timeout=120):
    """执行命令并返回输出"""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", "命令超时", 1
    except Exception as e:
        return "", str(e), 1


def resolve_share_url(share_text: str) -> dict:
    """解析抖音分享链接，返回无水印视频信息。

    核心逻辑（借鉴 yzfly/douyin-mcp-server，实测 2026-07-11 可用）：
    1. 正则提取分享文本中的 URL
    2. 跟随重定向拿到 video_id
    3. 请求 iesdouyin.com/share/video/{id} 分享页
    4. 正则抓 window._ROUTER_DATA 的 SSR JSON
    5. 取 play_addr.url_list[0]，playwm → play 去水印
    """
    urls = re.findall(
        r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+",
        share_text,
    )
    if not urls:
        raise ValueError("未找到有效的分享链接")

    share_url = urls[0]
    share_response = requests.get(share_url, headers=HEADERS, allow_redirects=True, timeout=30)
    video_id = share_response.url.split("?")[0].strip("/").split("/")[-1]

    detail_url = f"https://www.iesdouyin.com/share/video/{video_id}"
    response = requests.get(detail_url, headers=HEADERS, timeout=30)
    response.raise_for_status()

    pattern = re.compile(r"window\._ROUTER_DATA\s*=\s*(.*?)</script>", re.DOTALL)
    find_res = pattern.search(response.text)
    if not find_res or not find_res.group(1):
        raise ValueError("从 HTML 中解析视频信息失败（_ROUTER_DATA 未匹配）")

    json_data = json.loads(find_res.group(1).strip())
    VIDEO_KEY = "video_(id)/page"
    NOTE_KEY = "note_(id)/page"
    if VIDEO_KEY in json_data["loaderData"]:
        info = json_data["loaderData"][VIDEO_KEY]["videoInfoRes"]
    elif NOTE_KEY in json_data["loaderData"]:
        info = json_data["loaderData"][NOTE_KEY]["videoInfoRes"]
    else:
        raise Exception(f"无法从 JSON 中解析视频或图集信息，loaderData 键: {list(json_data['loaderData'].keys())}")

    data = info["item_list"][0]
    video_url = data["video"]["play_addr"]["url_list"][0].replace("playwm", "play")
    desc = data.get("desc", "").strip() or f"douyin_{video_id}"
    desc = re.sub(r'[\\/:*?"<>|]', "_", desc)

    author = data.get("author", {}).get("nickname", "")
    stats = data.get("statistics", {})

    return {
        "video_id": video_id,
        "title": desc,
        "download_url": video_url,
        "author": author,
        "like_count": stats.get("digg_count", 0),
        "comment_count": stats.get("comment_count", 0),
        "share_count": stats.get("share_count", 0),
    }


def download_video(video_url: str, output_dir: str, max_bytes: int = 600 * 1024 * 1024) -> str:
    """下载无水印视频，返回文件路径。max_bytes 默认 600MB。"""
    video_path = os.path.join(output_dir, "video.mp4")
    response = requests.get(video_url, headers=HEADERS, stream=True, allow_redirects=True, timeout=60)
    response.raise_for_status()

    content_type = response.headers.get("Content-Type", "")
    if response.status_code != 200 or "video" not in content_type:
        raise Exception(f"下载失败：状态码 {response.status_code}，Content-Type {content_type}")

    total = 0
    with open(video_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=65536):
            if chunk:
                f.write(chunk)
                total += len(chunk)
                if total > max_bytes:
                    raise Exception(f"视频超过 {max_bytes // 1024 // 1024}MB 限制")
    return video_path


def extract_audio(video_path: str, output_dir: str, max_duration: int | None = None) -> str:
    """用 ffmpeg 抽音频（16kHz 单声道 WAV，whisper 推荐格式）。

    max_duration 限制音频时长（秒），用于长视频分段转写避免爆内存。
    """
    audio_path = os.path.join(output_dir, "audio.wav")
    cmd = ["ffmpeg", "-y", "-i", video_path]
    if max_duration:
        cmd += ["-t", str(max_duration)]
    cmd += ["-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", audio_path]

    stdout, stderr, code = run_cmd(cmd, timeout=300)
    if code != 0:
        raise Exception(f"ffmpeg 音频提取失败: {stderr}")
    return audio_path


def transcribe_audio(audio_path: str, model_size: str = "small", language: str = "zh") -> dict:
    """用 openai-whisper 转写音频。

    实测（2026-07-11，沙箱 CPU）：
    - tiny (72MB)：3 分钟 10.5s，错字多，简繁混杂
    - small (461MB)：1 分钟 21.9s，语义清晰，专有名词需 LLM 校对
    - medium (1.5GB)：OOM Killed
    """
    try:
        import whisper
    except ImportError:
        return {"error": "openai-whisper 未安装，请运行: pip install openai-whisper"}

    try:
        model = whisper.load_model(model_size)
    except Exception as e:
        return {"error": f"模型加载失败: {e}"}

    # initial_prompt 强制简体中文输出（否则 tiny 会简繁混杂）
    initial_prompt = "以下是普通话的句子。" if language == "zh" else None

    try:
        result = model.transcribe(audio_path, language=language, verbose=False, initial_prompt=initial_prompt)
        return {
            "full_text": result["text"],
            "language": result.get("language", language),
            "model": model_size,
        }
    except Exception as e:
        return {"error": f"语音转写失败: {e}"}


def main():
    parser = argparse.ArgumentParser(description="抖音视频内容提取器（SSR 解析版）")
    parser.add_argument("url", help="抖音视频链接或分享文本")
    parser.add_argument("--output-dir", help="输出目录（默认临时目录）")
    parser.add_argument("--model", default="small", help="Whisper 模型 (tiny/base/small/medium/large)，默认 small")
    parser.add_argument("--language", default="zh", help="音频语言 (zh/en/ja/ko 等)")
    parser.add_argument("--max-duration", type=int, default=300,
                        help="转写最大时长（秒），默认 300（5 分钟）。长视频分段避免爆内存")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    parser.add_argument("--skip-transcribe", action="store_true", help="跳过语音转写（仅解析+下载）")
    args = parser.parse_args()

    output_dir = args.output_dir or tempfile.mkdtemp(prefix="douyin_")
    os.makedirs(output_dir, exist_ok=True)

    # Step 1: SSR 解析
    if not args.json:
        print(f"[1/3] SSR 解析分享链接...")
    try:
        info = resolve_share_url(args.url)
    except Exception as e:
        error_msg = f"解析失败: {e}"
        if args.json:
            print(json.dumps({"success": False, "error": error_msg}, ensure_ascii=False, indent=2))
        else:
            print(f"  {error_msg}")
        sys.exit(1)

    if not args.json:
        print(f"  标题: {info['title'][:60]}")
        print(f"  作者: {info['author']}")
        print(f"  点赞: {info['like_count']} 评论: {info['comment_count']} 分享: {info['share_count']}")

    # Step 2: 下载视频
    if not args.json:
        print(f"[2/3] 下载无水印视频...")
    try:
        video_path = download_video(info["download_url"], output_dir)
        size_mb = os.path.getsize(video_path) / 1024 / 1024
        if not args.json:
            print(f"  下载完成: {size_mb:.1f}MB -> {video_path}")
    except Exception as e:
        error_msg = f"下载失败: {e}"
        if args.json:
            print(json.dumps({"success": False, "error": error_msg, **info}, ensure_ascii=False, indent=2))
        else:
            print(f"  {error_msg}")
        sys.exit(1)

    # Step 3: 抽音频 + 转写
    transcription = None
    if not args.skip_transcribe:
        if not args.json:
            print(f"[3/3] 抽音频 + 转写 (model={args.model}, max_duration={args.max_duration}s)...")
        try:
            audio_path = extract_audio(video_path, output_dir, max_duration=args.max_duration)
            transcription = transcribe_audio(audio_path, model_size=args.model, language=args.language)
            if "error" in transcription:
                if not args.json:
                    print(f"  转写失败: {transcription['error']}")
            else:
                if not args.json:
                    print(f"  转写完成: {len(transcription['full_text'])} 字符")
        except Exception as e:
            transcription = {"error": str(e)}
            if not args.json:
                print(f"  音频处理失败: {e}")

    # 输出结果
    result = {
        "success": True,
        "video_id": info["video_id"],
        "title": info["title"],
        "author": info["author"],
        "like_count": info["like_count"],
        "comment_count": info["comment_count"],
        "share_count": info["share_count"],
        "video_file": video_path,
        "transcription": transcription,
    }

    if args.json:
        output = {k: v for k, v in result.items() if k != "video_file"}
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(f"\n{'='*50}")
        print(f"标题: {result['title']}")
        print(f"作者: {result['author']}")
        print(f"点赞: {result['like_count']} | 评论: {result['comment_count']} | 分享: {result['share_count']}")
        if transcription and "full_text" in transcription:
            print(f"\n--- 转写文字（{transcription['model']} 模型）---")
            print(transcription["full_text"])
        elif transcription and "error" in transcription:
            print(f"\n--- 转写失败: {transcription['error']} ---")
        print(f"{'='*50}")


if __name__ == "__main__":
    main()
