"""Build a narrated, captioned cut from real recording timestamps; preserve source."""
import json
import subprocess
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

RAW = Path(sys.argv[1]).resolve()
OUT = RAW.parent.parent / 'video' / RAW.name
OUT.mkdir(parents=True, exist_ok=True)
FF = '/opt/homebrew/bin/ffmpeg'
FP = '/opt/homebrew/bin/ffprobe'
def run(args): subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
def duration(p): return float(subprocess.check_output([FP,'-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(p)]))
def stamp(t):
    m=round(t*1000); return f'{m//3600000:02}:{m//60000%60:02}:{m//1000%60:02},{m%1000:03}'

SEGMENTS = [
 ('intake','mcp','订单X需要六百个连接件，供应商突然通知延期两天。计划员把这条消息交给有界，开始分析影响。'),
 ('mcp','analysis-start','本次会话已经配置企业系统连接器和业务技能。连接器负责访问数据，技能提供核查方法，大模型根据当前情况选择下一步。'),
 ('analysis-start','question','有界先查订单和库存，再检索历史经验。每一步都留下工具调用和返回依据。查到替代件，不等于这笔订单已经获准使用。'),
 ('question','followup','有界主动向人追问：是否有本订单的客户批准和技术确认？计划员只说同事认为可以用，并没有提供证明。'),
 ('followup','evidence','有界继续追问缺失的材料。这不是填完一次表就结束，而是根据新回答，核对还有什么没有解决。'),
 ('evidence','plans','现在补充本订单的技术确认和客户批准，允许使用三百个替代件。有界核验材料的适用范围，再继续制定恢复方案。'),
 ('plans','gantt','剩余一百个连接件，可以应急采购、区域调拨，或者等待原供应商。三种选择对应不同的追加成本和交期。'),
 ('gantt','approved','甘特图把生产时间与延期放在同一条时间轴上。计划员比较取舍，填写审批人，再批准预算内的折中方案。'),
 ('approved','invalidated','下达前，我们手动注入一项现场变化：产线被其他任务占用三十二小时。变化实际写入本机MES，并回读检查。'),
 ('invalidated','replanned','原来的排程条件已经改变，有界立即使旧方案和审批失效，阻止沿用旧批准。接下来重新计算恢复方案。'),
 ('replanned','delivered','重算后，生产需要等到产线释放。应急采购已不能进一步提前完工，有界调整建议。计划员重新批准，才向业务系统交付。'),
 ('delivered','readback','最后看到ERPNext业务单号与OpenMES执行记录，并读取最新进度。分析、追问、决策和执行变化，在同一任务中形成闭环。'),
]
marks={x['name']:x['seconds'] for x in json.loads((RAW/'timings.json').read_text())}
video=next(RAW.glob('*.webm'))
end=duration(video)
parts=[]; subtitles=[]; edits=[]; cursor=0.0
font=ImageFont.truetype('/System/Library/Fonts/STHeiti Medium.ttc',34)
for i,(a,b,text) in enumerate(SEGMENTS):
    audio=OUT/f'{i:02}.aiff'
    run(['/usr/bin/say','-v','Tingting','-r','188','-o',str(audio),text])
    length=duration(audio)+0.8
    start=marks[a]; stop=marks[b] if b!='readback' else end
    source_length=max(0.1,stop-start)
    # Slow short actions, cut only an explicitly recorded idle tail of long intervals.
    used=min(source_length,length)
    factor=length/used
    canvas=Image.new('RGB',(1920,1080),(9,19,34))
    draw=ImageDraw.Draw(canvas)
    midpoint=len(text)//2
    breaks=[j for j in range(max(1,midpoint-9),min(len(text),midpoint+10)) if text[j-1] in '，。？']
    split=min(breaks,key=lambda j:abs(j-midpoint)) if breaks else midpoint
    lines=text[:split]+'\n'+text[split:]
    draw.multiline_text((960,973),lines,font=font,fill='white',anchor='mm',align='center',spacing=12)
    caption=OUT/f'{i:02}.png';canvas.save(caption)
    dest=OUT/f'{i:02}.mp4'
    run([FF,'-y','-ss',str(start),'-t',str(used),'-i',str(video),'-loop','1','-i',str(caption),'-i',str(audio),
         '-filter_complex',f'[0:v]setpts={factor}*PTS,scale=1440:900[v];[1:v][v]overlay=240:0:shortest=1[out];[2:a]apad[a]',
         '-map','[out]','-map','[a]','-t',str(length),'-r','30','-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p','-c:a','aac',str(dest)])
    parts.append(dest);subtitles.extend([str(i+1),f'{stamp(cursor)} --> {stamp(cursor+length)}',lines,''])
    edits.append({'source_start':start,'source_end':start+used,'output_start':cursor,'output_end':cursor+length,'speed_factor':1/factor,'text':text})
    cursor+=length
    print(f'Segment {i+1}: {length:.1f}s',flush=True)
listing=OUT/'concat.txt'; listing.write_text(''.join(f"file '{p}'\n" for p in parts))
run([FF,'-y','-f','concat','-safe','0','-i',str(listing),'-c','copy','-movflags','+faststart',str(OUT/'youjie_finals_demo.mp4')])
(OUT/'youjie_finals_demo.zh-CN.srt').write_text('\n'.join(subtitles))
(OUT/'edit_decisions.json').write_text(json.dumps({'raw':str(video),'segments':edits,'duration':cursor},ensure_ascii=False,indent=2))
print(OUT, 'Duration:',cursor)
