#!/usr/bin/env python3
import os
import sys
import argparse
import whisper
import urllib.request
from tqdm import tqdm

# 进度条下载器
def download_with_progress(url, output_path):
    def reporthook(block_num, block_size, total_size):
        readsofar = block_num * block_size
        if total_size > 0:
            percent = readsofar * 1e2 / total_size
            s = f"\r{percent:5.1f}% {readsofar / 1024 / 1024:.1f} MB / {total_size / 1024 / 1024:.1f} MB"
            sys.stdout.write(s)
            if readsofar >= total_size:
                sys.stdout.write("\n")
        else:
            sys.stdout.write(f"\r{readsofar / 1024 / 1024:.1f} MB")
    urllib.request.urlretrieve(url, output_path, reporthook)

def main():
    parser = argparse.ArgumentParser(description="Download Whisper .pt models manually")
    parser.add_argument(
        "--model",
        default="base",
        choices=[
            "tiny","tiny.en","base","base.en",
            "small","small.en","medium","medium.en",
            "large","large-v2","large-v3"
        ],
        help="model size to download"
    )
    parser.add_argument(
        "--out",
        default=os.path.expanduser("~/.local/share/voice_ai_core/models"),
        help="download directory (default: ~/.local/share/voice_ai_core/models)"
    )
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)

    # 从 whisper 内部取 URL
    url_map = whisper._MODELS
    if args.model not in url_map:
        print(f"[ERROR] 模型 {args.model} 不在 whisper 内置列表中")
        sys.exit(1)

    url = url_map[args.model]
    output_path = os.path.join(args.out, f"{args.model}.pt")
    print(f"→ 开始下载 {args.model} 模型：{url}")
    download_with_progress(url, output_path)
    print(f"✅ 下载完成：{output_path}")

if __name__ == "__main__":
    main()
