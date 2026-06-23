#!/usr/bin/env python3
"""
抖音视频内容提取器

功能：
1. 通过 yt-dlp 下载抖音视频（支持短链接解析）
2. 通过 ffmpeg 提取音频
3. 通过 faster-whisper 进行语音转文字
4. 输出结构化 JSON（标题、描述、字幕、统计等）

用法：
  python3 douyin_reader.py "<URL>" [--output-dir DIR] [--model MODEL] [--json]
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlparse


def run_cmd(cmd, timeout=120):
    """执行命令并返回输出"""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"}
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", "命令超时", 1
    except Exception as e:
        return "", str(e), 1


def resolve_url(url):
    """解析抖音短链接，返回真实 URL"""
    # 如果是分享文本（如 "https://v.douyin.com/xxxxx/ 复制此链接..."），提取 URL 部分
    url_match = re.search(r'(https?://[^\s]+)', url)
    if url_match:
        url = url_match.group(1)
    # 去掉末尾的斜杠和多余字符
    url = url.rstrip('/').rstrip('复制此链接').strip()
    return url


def download_video(url, output_dir):
    """使用 yt-dlp 下载视频，返回视频文件路径和元数据"""
    video_path = os.path.join(output_dir, "video.mp4")
    
    # yt-dlp 下载命令
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--max-filesize", "500M",  # 限制 500MB
        "-o", video_path,
        "--write-info-json",
        "--skip-download",  # 先只获取元数据
        "--print", "title",
        url
    ]
    
    stdout, stderr, code = run_cmd(cmd, timeout=60)
    
    if code != 0:
        return None, None, f"yt-dlp 元数据获取失败: {stderr}"
    
    title = stdout.strip() if stdout else "未知标题"
    
    # 下载视频
    cmd_download = [
        "yt-dlp",
        "--no-playlist",
        "--max-filesize", "500M",
        "-o", video_path,
        "--merge-output-format", "mp4",
        url
    ]
    
    stdout, stderr, code = run_cmd(cmd_download, timeout=300)
    
    if code != 0:
        return None, None, f"yt-dlp 下载失败: {stderr}"
    
    if not os.path.exists(video_path):
        return None, None, "视频文件未生成"
    
    # 读取 info.json
    info_path = video_path + ".info.json"
    info = {}
    if os.path.exists(info_path):
        try:
            with open(info_path, 'r', encoding='utf-8') as f:
                info = json.load(f)
        except:
            pass
    
    return video_path, info, None


def extract_audio(video_path, output_dir):
    """使用 ffmpeg 提取音频"""
    audio_path = os.path.join(output_dir, "audio.wav")
    
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vn",           # 去掉视频轨道
        "-acodec", "pcm_s16le",  # WAV 格式
        "-ar", "16000",  # 16kHz 采样率（whisper 推荐）
        "-ac", "1",       # 单声道
        audio_path
    ]
    
    stdout, stderr, code = run_cmd(cmd, timeout=120)
    
    if code != 0:
        return None, f"ffmpeg 音频提取失败: {stderr}"
    
    if not os.path.exists(audio_path):
        return None, "音频文件未生成"
    
    return audio_path, None


def transcribe_audio(audio_path, model_size="tiny", language="zh"):
    """使用 faster-whisper 进行语音转文字"""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None, "faster-whisper 未安装，请运行: pip install faster-whisper"
    
    # 使用 CPU + int8 量化（内存友好）
    try:
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
    except Exception as e:
        return None, f"模型加载失败: {e}"
    
    try:
        segments, info = model.transcribe(audio_path, language=language, beam_size=5)
        
        full_text = []
        timed_segments = []
        for segment in segments:
            text = segment.text.strip()
            if text:
                full_text.append(text)
                timed_segments.append({
                    "start": round(segment.start, 2),
                    "end": round(segment.end, 2),
                    "text": text
                })
        
        return {
            "full_text": "\n".join(full_text),
            "segments": timed_segments,
            "language": info.language,
            "language_probability": round(info.language_probability, 3)
        }, None
    except Exception as e:
        return None, f"语音转写失败: {e}"


def main():
    parser = argparse.ArgumentParser(description="抖音视频内容提取器")
    parser.add_argument("url", help="抖音视频链接（支持短链接）")
    parser.add_argument("--output-dir", help="输出目录（默认临时目录）")
    parser.add_argument("--model", default="tiny", help="Whisper 模型大小 (tiny/base/small/medium/large)")
    parser.add_argument("--language", default="zh", help="音频语言 (zh/en/ja/ko 等)")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    parser.add_argument("--skip-transcribe", action="store_true", help="跳过语音转写（仅下载+元数据）")
    args = parser.parse_args()
    
    # 解析 URL
    url = resolve_url(args.url)
    print(f"正在处理: {url}")
    
    # 创建输出目录
    output_dir = args.output_dir or tempfile.mkdtemp(prefix="douyin_")
    os.makedirs(output_dir, exist_ok=True)
    
    # Step 1: 下载视频
    print("  [1/3] 下载视频...")
    video_path, info, error = download_video(url, output_dir)
    if error:
        print(f"  下载失败: {error}")
        if args.json:
            print(json.dumps({"success": False, "error": error, "url": url}, ensure_ascii=False, indent=2))
        sys.exit(1)
    
    print(f"  下载成功: {video_path}")
    
    # Step 2: 提取音频
    print("  [2/3] 提取音频...")
    audio_path, error = extract_audio(video_path, output_dir)
    if error:
        print(f"  音频提取失败: {error}")
        if args.json:
            print(json.dumps({"success": False, "error": error, "url": url}, ensure_ascii=False, indent=2))
        sys.exit(1)
    
    # Step 3: 语音转文字
    transcription = None
    if not args.skip_transcribe:
        print(f"  [3/3] 语音转文字 (model={args.model})...")
        transcription, error = transcribe_audio(audio_path, model_size=args.model, language=args.language)
        if error:
            print(f"  语音转写失败: {error}")
            # 不退出，继续输出已获取的信息
    else:
        print("  [3/3] 跳过语音转写")
    
    # 组装结果
    result = {
        "success": True,
        "url": url,
        "title": info.get("title", "未知标题"),
        "description": info.get("description", ""),
        "uploader": info.get("uploader", ""),
        "duration": info.get("duration", 0),
        "view_count": info.get("view_count", 0),
        "like_count": info.get("like_count", 0),
        "comment_count": info.get("comment_count", 0),
        "tags": info.get("tags", []),
        "transcription": transcription,
        "video_file": video_path,
        "audio_file": audio_path,
    }
    
    if args.json:
        # 移除文件路径字段（JSON 输出不需要）
        output = {k: v for k, v in result.items() if k not in ("video_file", "audio_file")}
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(f"\n{'='*50}")
        print(f"标题: {result['title']}")
        print(f"作者: {result['uploader']}")
        print(f"时长: {result['duration']}秒")
        print(f"播放: {result['view_count']} | 点赞: {result['like_count']} | 评论: {result['comment_count']}")
        if result.get('tags'):
            print(f"标签: {', '.join(result['tags'])}")
        if result.get('description'):
            print(f"描述: {result['description'][:200]}")
        if transcription:
            print(f"\n--- 转写文字 ---")
            print(transcription['full_text'])
        print(f"{'='*50}")


if __name__ == "__main__":
    main()
