"""Append native video to the approved blank slide 12; preserve other parts."""
import sys
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from lxml import etree as E

source,video,poster,dest=map(Path,sys.argv[1:])
if dest.exists():raise SystemExit('Preserve existing output')
P='http://schemas.openxmlformats.org/presentationml/2006/main'
A='http://schemas.openxmlformats.org/drawingml/2006/main'
R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PK='http://schemas.openxmlformats.org/package/2006/relationships'
CT='http://schemas.openxmlformats.org/package/2006/content-types'
with ZipFile(source) as z:parts={n:z.read(n) for n in z.namelist()}
slide='ppt/slides/slide12.xml'; rel='ppt/slides/_rels/slide12.xml.rels'
root=E.fromstring(parts[slide]); tree=root.find(f'{{{P}}}cSld/{{{P}}}spTree')
shape_id=max([int(x.get('id')) for x in root.findall(f'.//{{{P}}}cNvPr')]+[1])+1
pic=E.fromstring(f'''<p:pic xmlns:p="{P}" xmlns:a="{A}" xmlns:r="{R}">
<p:nvPicPr><p:cNvPr id="{shape_id}" name="有界决赛 Demo（点击播放）"><a:hlinkClick r:id="" action="ppaction://media"/></p:cNvPr><p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr><a:videoFile r:link="rIdDemoVideo"/><p:extLst><p:ext uri="{{DAA4B4D4-6D71-4841-9C94-3DE7FCFB85D3}}"><p14:media xmlns:p14="http://schemas.microsoft.com/office/powerpoint/2010/main" r:embed="rIdDemoMedia"/></p:ext></p:extLst></p:nvPr></p:nvPicPr>
<p:blipFill><a:blip r:embed="rIdDemoPoster"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>
<p:spPr><a:xfrm><a:off x="304800" y="685800"/><a:ext cx="11582400" cy="6515100"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>''')
# Keep the official logo band visible; fit 16:9 media inside the slide bounds.
xfrm=pic.find(f'.//{{{A}}}xfrm');xfrm.find(f'{{{A}}}off').set('x','762000');xfrm.find(f'{{{A}}}off').set('y','685800')
xfrm.find(f'{{{A}}}ext').set('cx','10668000');xfrm.find(f'{{{A}}}ext').set('cy','6000750')
tree.append(pic)
timing=E.fromstring(f'''<p:timing xmlns:p="{P}"><p:tnLst><p:par><p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst><p:video><p:cMediaNode vol="80000"><p:cTn id="2" fill="hold" display="0"><p:stCondLst><p:cond delay="indefinite"/></p:stCondLst></p:cTn><p:tgtEl><p:spTgt spid="{shape_id}"/></p:tgtEl></p:cMediaNode></p:video></p:childTnLst></p:cTn></p:par></p:tnLst></p:timing>''')
root.append(timing);parts[slide]=E.tostring(root,xml_declaration=True,encoding='UTF-8',standalone=True)
rels=E.fromstring(parts[rel])
for id,typ,target in [('rIdDemoVideo',R+'/video','../media/finals_demo.mp4'),('rIdDemoMedia','http://schemas.microsoft.com/office/2007/relationships/media','../media/finals_demo.mp4'),('rIdDemoPoster',R+'/image','../media/finals_demo_poster.png')]:E.SubElement(rels,f'{{{PK}}}Relationship',Id=id,Type=typ,Target=target)
parts[rel]=E.tostring(rels,xml_declaration=True,encoding='UTF-8')
types=E.fromstring(parts['[Content_Types].xml'])
for ext,mime in [('mp4','video/mp4'),('png','image/png')]:
    if not any(x.get('Extension')==ext for x in types):E.SubElement(types,f'{{{CT}}}Default',Extension=ext,ContentType=mime)
parts['[Content_Types].xml']=E.tostring(types,xml_declaration=True,encoding='UTF-8')
parts['ppt/media/finals_demo.mp4']=video.read_bytes();parts['ppt/media/finals_demo_poster.png']=poster.read_bytes()
dest.parent.mkdir(parents=True,exist_ok=True)
with ZipFile(dest,'w',ZIP_DEFLATED) as z:
    for n,data in parts.items():z.writestr(n,data)
with ZipFile(source) as z:
    assert all(parts[n]==z.read(n) for n in z.namelist() if n not in [slide,rel,'[Content_Types].xml'])
print(json.dumps({'slides_preserved_except':12,'embedded_video_bytes':video.stat().st_size,'candidate':str(dest)},ensure_ascii=False))
