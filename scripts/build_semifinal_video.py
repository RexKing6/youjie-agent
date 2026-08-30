from __future__ import annotations

import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
RAW_VIDEO = ROOT / "artifacts/semifinal_video_erpnext/youjie_semifinal_demo_erpnext_raw.webm"
WORK_DIR = ROOT / "artifacts/semifinal_video_erpnext/subtitled_build"
FINAL_VIDEO = ROOT / "docs/youjie_semifinal_demo.mp4"
FINAL_SRT = ROOT / "docs/youjie_semifinal_demo.zh-CN.srt"
NARRATION_TEXT = ROOT / "artifacts/semifinal_video_erpnext/narration_zh_slow.txt"
FFMPEG = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"
SAY = "/usr/bin/say"
FONT = "/System/Library/Fonts/STHeiti Medium.ttc"
SPEECH_RATE = "190"

SEGMENTS = [
    "这是有界，一个制造供应链异常研判与恢复计划智能体。现在看到的不是幻灯片，而是本机实际运行的产品工作台。",
    "我们输入一句供应商消息：座椅未来四十八小时无法发运。在线模型只负责理解事故、识别实体和提取原文事实。",
    "LangGraph 继续规划查询并调用工具。订单影响和 BOM 传播由确定性代码计算，排程交给 OR-Tools CP-SAT。",
    "系统给出保交付、平衡和少变更三种方案。每个成本、延期数量和逐单完成时间，都能由独立验证器重新计算。",
    "流程在人工审批处暂停。批准记录绑定场景哈希和计划哈希；没有人的确认，系统不会生成外部业务命令。",
    "批准后，系统通过认证 REST 写入真实开源 ERPNext 测试实例，创建一张物料申请和三张生产工单草稿，并逐条回读编号和状态。",
    "随后，三张工单以同一业务编号同步到真实 OpenMES 测试实例。页面回读待接单状态和已产数量，证明跨系统下发确实发生。",
    "如果现场人员改变工单状态，MES revision 会变化，旧批准立即失效。当前演示保留人工操作边界，不在脚本里冒充现场人员。",
    "商业系统合同沙箱继续验证异常语义：HTTP 已接收不等于业务成功。ERP 已应用而 MES 拒绝时，结果必须标为部分应用。",
    "最后用六步证据链复盘异常传播、三方案比较、人工批准和失效重算。输入可以不确定，计划必须可复算、可追溯。",
    "ERPNext 和 OpenMES 都是本机测试实例，不代表生产租户或物理设备执行。能力有界，方案可证，最终决策仍由人承担。",
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


def wrap_subtitle(text: str, width: int = 24) -> str:
    if len(text) <= width:
        return text
    split = min(range(max(1, len(text) // 2 - 8), min(len(text), len(text) // 2 + 9)), key=lambda i: abs(i - len(text) / 2))
    return text[:split] + "\n" + text[split:]


def render_subtitle(text: str, path: Path) -> None:
    canvas = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype(FONT, 31)
    wrapped = wrap_subtitle(text)
    bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=8, align="center")
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    box_width = min(1160, text_width + 72)
    box_height = text_height + 38
    left = (1280 - box_width) // 2
    top = 720 - box_height - 22
    draw.rounded_rectangle((left, top, left + box_width, top + box_height), radius=16, fill=(5, 22, 32, 205))
    draw.multiline_text(
        (640, top + 15),
        wrapped,
        font=font,
        fill=(255, 255, 255, 255),
        spacing=8,
        anchor="ma",
        align="center",
    )
    canvas.save(path)


def main() -> None:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    NARRATION_TEXT.write_text("\n\n".join(SEGMENTS) + "\n", encoding="utf-8")

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
    concat_list.write_text("".join(f"file '{path.as_posix()}'\n" for path in audio_files), encoding="utf-8")
    narration = WORK_DIR / "narration_slow.aiff"
    run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(narration)])

    srt_lines: list[str] = []
    for index, (start, end, text) in enumerate(timings, start=1):
        srt_lines.extend([str(index), f"{srt_time(start)} --> {srt_time(end)}", wrap_subtitle(text), ""])
    FINAL_SRT.write_text("\n".join(srt_lines), encoding="utf-8")

    subtitle_images: list[Path] = []
    for index, (_, _, text) in enumerate(timings, start=1):
        subtitle_image = WORK_DIR / f"subtitle_{index:02d}.png"
        render_subtitle(text, subtitle_image)
        subtitle_images.append(subtitle_image)

    raw_duration = duration(RAW_VIDEO)
    audio_duration = duration(narration)
    target_duration = audio_duration + 1.0
    speed_factor = target_duration / raw_duration
    command = [FFMPEG, "-y", "-i", str(RAW_VIDEO), "-i", str(narration)]
    for subtitle_image in subtitle_images:
        command.extend(["-loop", "1", "-framerate", "25", "-i", str(subtitle_image)])
    filters = [f"[0:v]setpts={speed_factor:.8f}*PTS[v0]"]
    for index, (start, end, _) in enumerate(timings):
        filters.append(
            f"[v{index}][{index + 2}:v]overlay=0:0:enable='between(t,{start:.3f},{end:.3f})'[v{index + 1}]"
        )
    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            f"[v{len(timings)}]",
            "-map",
            "1:a:0",
            "-af",
            "apad=pad_dur=1",
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
    print(FINAL_VIDEO)
    print(f"raw={raw_duration:.2f}s narration={audio_duration:.2f}s final={duration(FINAL_VIDEO):.2f}s rate={SPEECH_RATE}")


if __name__ == "__main__":
    main()
