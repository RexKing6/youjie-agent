from __future__ import annotations

import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
RAW_VIDEO = ROOT / "artifacts/semifinal_video_erpnext/youjie_semifinal_demo_erpnext_raw.webm"
WORK_DIR = ROOT / "artifacts/defense_video_58s"
FINAL_VIDEO = ROOT / "docs/youjie_semifinal_demo_58s.mp4"
FINAL_SRT = ROOT / "docs/youjie_semifinal_demo_58s.zh-CN.srt"
FFMPEG = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"
SAY = "/usr/bin/say"
FONT = "/System/Library/Fonts/STHeiti Medium.ttc"
SPEECH_RATE = "188"

SEGMENTS = [
    "这是本机运行的有界工作台。输入供应商座椅未来四十八小时无法发运。",
    "在线模型提取事故，LangGraph 调用快照、规则、影响分析和 CP-SAT 求解工具。",
    "系统给出三套可验证方案，并在人工审批前暂停；这里选择平衡方案。",
    "批准后才通过认证 REST，在真实 ERPNext 测试实例创建一张物料申请和三张生产工单草稿。",
    "同号工单继续同步到真实 OpenMES，并回读生产状态，证明跨系统下发确实发生。",
    "验证回放显示：MES 容量版本变化时，旧审批立即失效；系统重新求解，新工单保持为零。",
    "大模型负责理解，确定性内核负责计算，人负责最终决策；系统不控制设备。",
]

CAPTIONS = [
    "这是本机运行的有界工作台。\n输入供应商座椅未来四十八小时无法发运。",
    "在线模型提取事故，LangGraph 调用\n快照、规则、影响分析和 CP-SAT 求解工具。",
    "系统给出三套可验证方案，\n并在人工审批前暂停；这里选择平衡方案。",
    "批准后才通过认证 REST，\n在真实 ERPNext 测试实例创建一张物料申请和三张生产工单草稿。",
    "同号工单继续同步到真实 OpenMES，\n并回读生产状态，证明跨系统下发确实发生。",
    "验证回放显示：MES 容量版本变化时，\n旧审批立即失效；系统重新求解，新工单保持为零。",
    "大模型负责理解，确定性内核负责计算，\n人负责最终决策；系统不控制设备。",
]

# Source intervals preserve the actual interaction order while removing idle waits.
VISUAL_INTERVALS = [
    (0.0, 7.0),
    (8.5, 16.0),
    (16.0, 23.5),
    (23.5, 34.5),
    (34.5, 48.0),
    (78.0, 90.0),
    (90.0, 96.0),
]


def run(args: list[str]) -> None:
    subprocess.run(args, check=True)


def duration(path: Path) -> float:
    result = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(json.loads(result.stdout)["format"]["duration"])


def srt_time(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def wrap_subtitle(text: str, width: int = 25) -> str:
    if "\n" in text:
        return text
    if len(text) <= width:
        return text
    midpoint = len(text) / 2
    candidates = range(max(1, int(midpoint) - 10), min(len(text), int(midpoint) + 11))
    punctuation = "，。；："
    split = min(candidates, key=lambda index: (0 if text[index - 1] in punctuation else 1, abs(index - midpoint)))
    return text[:split] + "\n" + text[split:]


def render_subtitle(text: str, path: Path) -> None:
    canvas = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype(FONT, 30)
    wrapped = wrap_subtitle(text)
    bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=7, align="center")
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    box_width = min(1160, text_width + 68)
    box_height = text_height + 34
    left = (1280 - box_width) // 2
    top = 720 - box_height - 20
    draw.rounded_rectangle(
        (left, top, left + box_width, top + box_height),
        radius=15,
        fill=(5, 22, 32, 214),
    )
    draw.multiline_text(
        (640, top + 13),
        wrapped,
        font=font,
        fill=(255, 255, 255, 255),
        spacing=7,
        anchor="ma",
        align="center",
    )
    canvas.save(path)


def main() -> None:
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    audio_files: list[Path] = []
    timings: list[tuple[float, float, str]] = []
    cursor = 0.0
    for index, text in enumerate(SEGMENTS, start=1):
        audio = WORK_DIR / f"segment_{index:02d}.aiff"
        run([SAY, "-v", "Tingting", "-r", SPEECH_RATE, "-o", str(audio), text])
        segment_duration = duration(audio)
        audio_files.append(audio)
        timings.append((cursor, cursor + segment_duration, text))
        cursor += segment_duration

    concat_list = WORK_DIR / "audio_concat.txt"
    concat_list.write_text(
        "".join(f"file '{path.as_posix()}'\n" for path in audio_files),
        encoding="utf-8",
    )
    narration = WORK_DIR / "narration.aiff"
    run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(narration)])
    audio_duration = duration(narration)
    target_duration = audio_duration + 0.55
    if target_duration > 59.5:
        raise RuntimeError(f"narration too long for one-minute demo: {target_duration:.2f}s")

    srt_lines: list[str] = []
    subtitle_images: list[Path] = []
    for index, ((start, end, _), caption) in enumerate(zip(timings, CAPTIONS, strict=True), start=1):
        srt_lines.extend([str(index), f"{srt_time(start)} --> {srt_time(end)}", caption, ""])
        subtitle_image = WORK_DIR / f"subtitle_{index:02d}.png"
        render_subtitle(caption, subtitle_image)
        subtitle_images.append(subtitle_image)
    FINAL_SRT.write_text("\n".join(srt_lines), encoding="utf-8")

    visual_duration = sum(end - start for start, end in VISUAL_INTERVALS)
    speed_factor = target_duration / visual_duration
    trim_filters = []
    for index, (start, end) in enumerate(VISUAL_INTERVALS):
        trim_filters.append(f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{index}]")
    concat_inputs = "".join(f"[v{index}]" for index in range(len(VISUAL_INTERVALS)))
    filters = trim_filters + [
        f"{concat_inputs}concat=n={len(VISUAL_INTERVALS)}:v=1:a=0,setpts={speed_factor:.8f}*PTS[base]"
    ]
    for index, (start, end, _) in enumerate(timings):
        source = "base" if index == 0 else f"sub{index}"
        target = f"sub{index + 1}"
        filters.append(
            f"[{source}][{index + 2}:v]overlay=0:0:enable='between(t,{start:.3f},{end:.3f})'[{target}]"
        )

    command = [FFMPEG, "-y", "-i", str(RAW_VIDEO), "-i", str(narration)]
    for subtitle_image in subtitle_images:
        command.extend(["-loop", "1", "-framerate", "25", "-i", str(subtitle_image)])
    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            f"[sub{len(timings)}]",
            "-map",
            "1:a:0",
            "-af",
            "apad=pad_dur=0.55",
            "-t",
            f"{target_duration:.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-movflags",
            "+faststart",
            str(FINAL_VIDEO),
        ]
    )
    run(command)
    final_duration = duration(FINAL_VIDEO)
    print(FINAL_VIDEO)
    print(f"audio={audio_duration:.2f}s final={final_duration:.2f}s visual_speed={1 / speed_factor:.2f}x")


if __name__ == "__main__":
    main()
