from pathlib import Path
import re,json,html
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,PageBreak,Image
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
import fitz
from PIL import Image as PILImage,ImageOps,ImageDraw
P=Path('F:/脑机项目/guanweixin_demo_v01');O=P/'submission/观微芯_AI精度优化_20261030_r14';D=O/'docs';E=P/'development/ai_accuracy_20261030_r14/reports/board';V=E/'tmp/pdf_review';V.mkdir(parents=True,exist_ok=True)
pdfmetrics.registerFont(TTFont('Song',r'C:/Windows/Fonts/simsun.ttc',subfontIndex=0))
body=ParagraphStyle('body',fontName='Song',fontSize=10.5,leading=18,spaceAfter=11,wordWrap='CJK')
heading=ParagraphStyle('heading',parent=body,fontSize=18,leading=26,spaceAfter=22)
title=ParagraphStyle('title',parent=body,fontSize=25,leading=36,spaceAfter=26)
small=ParagraphStyle('small',parent=body,fontSize=9,leading=15)
story=[]
for para in (D/'技术与性能分析报告.md').read_text(encoding='utf-8').split('\n\n'):
 para=para.strip()
 if not para:continue
 if para.startswith('# '):
  parts=para.split('\n',1);story.append(Paragraph(html.escape(parts[0][2:]),title))
  if len(parts)>1:story.append(Paragraph(html.escape(parts[1]),small))
 elif para.startswith('## '):
  story.append(PageBreak());story.append(Paragraph(html.escape(para[3:]),heading))
  if '实板ILA' in para:story.append(Image(str(D/'coremark_ila_r14.png'),width=490,height=245));story.append(Spacer(1,14))
 else:
  # Break long checksums without changing their visible characters.
  para=re.sub(r'[0-9a-f]{64}',lambda m:'<br/>'.join(m[0][i:i+32] for i in range(0,64,32)),html.escape(para))
  story.append(Paragraph(para.replace('\n','<br/>'),body))
def footer(c,d):
 c.setStrokeColor(colors.HexColor('#cccccc'));c.line(48,43,547,43);c.setFont('Song',8);c.drawString(48,29,'观微芯 | r14 | 片上自测实板版 | 2026-10-30');c.drawRightString(547,29,str(d.page))
pdf=D/'观微芯_技术与性能分析报告.pdf';SimpleDocTemplate(str(pdf),pagesize=A4,rightMargin=48,leftMargin=48,topMargin=48,bottomMargin=57,title='观微芯 r14 技术与性能分析报告',author='观微芯项目').build(story,onFirstPage=footer,onLaterPages=footer)
doc=fitz.open(pdf);imgs=[]
for i,p in enumerate(doc):
 q=V/f'page-{i+1:02}.png';p.get_pixmap(matrix=fitz.Matrix(1.15,1.15),alpha=False).save(q);im=PILImage.open(q);im.thumbnail((420,595));imgs.append(im.copy())
for start in range(0,len(imgs),4):
 sheet=PILImage.new('RGB',(880,1240),'#dddddd')
 for j,im in enumerate(imgs[start:start+4]):sheet.paste(im,(15+(j%2)*440,15+(j//2)*620))
 sheet.save(V/f'contact-{start//4+1}.png')
(E/'pdf_render_status.json').write_text(json.dumps(dict(pages=len(doc),rendered_all=True,visual_review_pass=False,pdf=str(pdf)),ensure_ascii=False,indent=2),encoding='utf-8')
print('PDF pages',len(doc));print('Contact sheets',list(V.glob('contact-*.png')))
