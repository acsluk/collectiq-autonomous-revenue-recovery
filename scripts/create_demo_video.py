"""Render a 120-second narrated evidence walkthrough; never invokes financial APIs."""
import json
import sqlite3
import subprocess
import sys
import textwrap
import wave
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont

ROOT=Path(__file__).resolve().parent.parent
OUT=ROOT/'data'/'demo_video'
OUT.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(ROOT/'data'/'video_deps'))
import imageio_ffmpeg

FONT=Path('C:/Windows/Fonts')
def font(size,bold=False):return ImageFont.truetype(str(FONT/('segoeuib.ttf' if bold else 'segoeui.ttf')),size)
db=sqlite3.connect(f'file:{ROOT / "data" / "collectiq.sqlite3"}?mode=ro',uri=True)
case=json.loads(db.execute('SELECT body FROM cases WHERE id=?',('cq_1f246066264227319912',)).fetchone()[0])
b=json.loads(db.execute('SELECT body FROM workflows WHERE id=?',('ai_d029e580a4bb729f7e3056',)).fetchone()[0])
count=db.execute('SELECT count(*) FROM events').fetchone()[0]
db.close()
ready=json.loads((ROOT/'submission'/'READINESS.json').read_text())
segments=[
 (12,'CollectIQ','Autonomous Revenue Recovery',
  'CollectIQ is autonomous revenue recovery. AI agents investigate invoice disputes, negotiate permitted repayment terms, and execute policy-approved billing through Stripe. Here is our working hackathon demonstration.',
  [('TRACK 2','Agents That Collect'),('COGNEE PRIZE','Persistent memory that changes decisions')]),
 (15,'Start with the customer','Acme Solutions · synthetic demo customer',
  'Acme disputes two hundred pounds of a one thousand pound invoice because a contracted deliverable was incomplete. They request three hundred pounds now and five hundred next month. The orchestrator selects the dispute workflow first.',
  [('ORIGINAL INVOICE','£1,000'),('CUSTOMER REQUEST','£200 disputed · £300 now · £500 next month')]),
 (15,'Retrieve before deciding','Cognee Cloud · real authenticated evidence retrieval',
  'Cognee retrieves the customer contract, collection policy, and incomplete-deliverable evidence from Acme’s isolated dataset. Dispute2Cash checks the documented two hundred pound report. Customer-specific memory is the evidence base for the decision.',
  [('CONTRACT','ACME-CONTRACT-001'),('POLICY','ACME-POLICY-001'),('ACCEPTANCE EVIDENCE','ACME-ACCEPTANCE-001')]),
 (15,'Financial authority stays deterministic','Integer pence · evidence cap · exact reconciliation',
  'Deterministic rules approve the supported two hundred pound reduction, capped at twenty percent. Three hundred plus five hundred exactly equals the remaining eight hundred pounds. The verified dates are fifteenth October and fifteenth November, next calendar month.',
  [('SUPPORTED REDUCTION','£1,000 − £200 = £800'),('APPROVED ARRANGEMENT','£300 on 15 Oct 2026 · £500 on 15 Nov 2026')]),
 (17,'Genuine Stripe test billing','Actual returned invoice IDs · no payment collection claimed',
  'Stripe confirms the original invoice is void. The three hundred and five hundred pound replacement invoices are open and unpaid. The workflow prepared replacement drafts, verified ownership and zero payments, retired only its own original, and finalised the replacements.',
  [('£1,000 ORIGINAL · VOID',case['invoice']['id']),('£300 REPLACEMENT · OPEN / UNPAID',case['replacements'][0]['id']),('£500 REPLACEMENT · OPEN / UNPAID',case['replacements'][1]['id'])]),
 (13,'An execution trail you can inspect','Durable operation keys · Cognee decision records',
  'A verified replay created zero additional financial operations. Cognee retrieved the actual Stripe invoice identifiers. Every financial intent and response is audited, and a live customer-isolation test passed. No live Stripe key is accepted.',
  [('IDEMPOTENCY','0 additional financial operations on verified replay'),('AUDIT JOURNAL',f'{count} persisted events · hash chain verified'),('MEMORY ISOLATION','Live cross-customer isolation check passed')]),
 (17,'Memory changes the negotiation','Separate seller and simulated-buyer model calls',
  'In the saved live negotiation, the simulated buyer offers two hundred now and six hundred next month. Cognee recalls a broken promise. The stricter policy requires eight hundred upfront, above the buyer’s two hundred and fifty pound authority. The seller rejects and cites the policy and history.',
  [('SIMULATED BUYER · OFFER','£200 now + £600 next month'),('SELLER · REJECT','Broken promise → £800 upfront required'),('EVIDENCE REFERENCES','POLICY-B-001 · HISTORY-B-001')]),
 (11,'Verified results. Honest boundaries.','Existing MVP · no advanced dashboard required',
  'The core billing workflow is verified. New agent scenarios default to dry run. The corrected full agent run remains unverified, and Scenario C requires review. No received payment is claimed.',
  [('CORE MVP','Real Cognee + Stripe test invoicing verified'),('AGENT SCENARIOS','A: agreement recorded · B: rejection recorded'),('DISCLOSURE','Scenario C / corrected full run: not verified')]),
 (5,'CollectIQ','Autonomous Revenue Recovery',
  'CollectIQ. Evidence-led collections, persistent memory, and policy-approved Stripe billing.',
  [('PUBLIC SOURCE','github.com/acsluk/collectiq-autonomous-revenue-recovery')])
]
assert sum(s[0] for s in segments)==120

def lines(draw,text,width,ft):
    result=[];line=''
    for word in text.split():
        trial=(line+' '+word).strip()
        if draw.textlength(trial,font=ft)>width and line:result.append(line);line=word
        else:line=trial
    if line:result.append(line)
    return result

for index,(duration,title,sub,narration,cards) in enumerate(segments):
    im=Image.new('RGB',(1280,720),'#f7f8fb');d=ImageDraw.Draw(im)
    d.rounded_rectangle((44,30,89,75),12,fill='#6c57dc');d.text((55,34),'C',font=font(30,True),fill='white')
    d.text((101,37),'CollectIQ',font=font(24,True),fill='#292538')
    d.text((870,42),'BRIEFCASE × STRIPE HACKATHON',font=font(15,True),fill='#8a7f9d')
    d.line((44,95,1236,95),fill='#e5e0ed',width=2)
    d.text((52,119),title,font=font(44,True),fill='#332b49')
    d.text((55,184),sub,font=font(21),fill='#84778f')
    y=238
    card_height=90 if len(cards)==3 else 119
    for label,value in cards:
        d.rounded_rectangle((52,y,1228,y+card_height-12),12,fill='white',outline='#e7e0ef',width=2)
        d.text((74,y+12),label,font=font(14,True),fill='#8a7ba4')
        vf=font(25 if len(value)<55 else 21,True)
        d.text((74,y+35),value,font=vf,fill='#6952cd' if 'REJECT' not in label else '#aa6b33')
        y+=card_height
    d.rounded_rectangle((44,554,1236,678),10,fill='#30293e')
    cap=lines(d,narration,1135,font(21))
    for row,text in enumerate(cap[:4]):d.text((65,566+row*25),text,font=font(21),fill='#f5f2fa')
    d.text((53,690),'RECORDED API EVIDENCE  ·  STRIPE TEST MODE  ·  SIMULATED CUSTOMER DATA',font=font(12,True),fill='#92859f')
    d.text((1177,689),f'{index+1:02d} / 09',font=font(12),fill='#92859f')
    im.save(OUT/f'slide{index:02d}.png')
    (OUT/f'speech{index:02d}.txt').write_text(narration,encoding='utf-8-sig')

ps='''Add-Type -AssemblyName System.Speech
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
$speaker.Rate = 1
$voices = $speaker.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -eq 'en-GB' }
if ($voices) { $speaker.SelectVoice($voices[0].VoiceInfo.Name) }
Get-ChildItem -LiteralPath $PSScriptRoot -Filter 'speech*.txt' | Sort-Object Name | ForEach-Object {
    $taskWave = [System.IO.Path]::ChangeExtension($_.FullName, '.wav')
    $speaker.SetOutputToWaveFile($taskWave)
    $speaker.Speak([System.IO.File]::ReadAllText($_.FullName))
    $speaker.SetOutputToNull()
}
$speaker.Dispose()
'''
(OUT/'narrate.ps1').write_text(ps,encoding='utf-8-sig')
speech_command=ps.replace('$PSScriptRoot',"'"+str(OUT).replace("'","''")+"'")
subprocess.run(['C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe','-NoProfile','-Command',speech_command],check=True,timeout=90)
encoder=imageio_ffmpeg.get_ffmpeg_exe()
clips=[]
for i,(duration,*_) in enumerate(segments):
    audio=OUT/f'speech{i:02d}.wav'
    with wave.open(str(audio),'rb') as stream:seconds=stream.getnframes()/stream.getframerate()
    speed=max(1,seconds/(duration-0.3))
    target=OUT/f'clip{i:02d}.mp4'
    subprocess.run([encoder,'-hide_banner','-loglevel','error','-y','-loop','1','-framerate','15','-i',str(OUT/f'slide{i:02d}.png'),
                    '-i',str(audio),'-af',f'atempo={speed:.5f},apad','-t',str(duration),'-c:v','libx264','-preset','ultrafast',
                    '-crf','23','-pix_fmt','yuv420p','-c:a','aac','-ar','48000','-ac','2',str(target)],check=True,timeout=45)
    clips.append(target)
concat=OUT/'clips.txt';concat.write_text(''.join("file '"+str(p).replace('\\','/')+"'\n" for p in clips),encoding='utf-8')
final=ROOT/'CollectIQ_2_Minute_Demo.mp4'
subprocess.run([encoder,'-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',str(concat),'-c','copy','-t','119.8','-movflags','+faststart',str(final)],check=True,timeout=30)
print(json.dumps({'video':str(final),'duration_seconds':'under 120','size_bytes':final.stat().st_size,'narrated':True,'captions':'burned in','source':'Recorded actual API evidence; no financial APIs invoked'}))
