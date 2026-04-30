#!/usr/bin/env python3
"""
WebWhizzy SMS Bot - Professional Edition
Powered by Claude AI + Twilio SMS
"""

import os, json, re, urllib.request, logging
from flask import Flask, request, Response
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client

ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_SMS_NUMBER  = os.getenv("TWILIO_SMS_NUMBER", "")
ADMIN_PHONE        = os.getenv("ADMIN_PHONE", "")
ADMIN_PHONE_2      = os.getenv("ADMIN_PHONE_2", "")

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN) if TWILIO_ACCOUNT_SID else None

IDLE="idle"; FORM_FIRST="ff"; FORM_LAST="fl"; FORM_EMAIL="fe"
FORM_BIZ="fb"; FORM_PLAN="fp"; FORM_NOTE="fn"; HUMAN_WAIT="hw"; ADMIN_REPLY="ar"
sessions: dict = {}

SYSTEM_PROMPT = """You are the WebWhizzy virtual assistant - professional, warm, and helpful.
WebWhizzy builds custom AI-powered agents for WhatsApp, SMS, and Telegram that handle customer conversations, automate workflows, and grow businesses 24/7.
Keep SMS replies SHORT and clear (under 300 characters when possible). Plain text only.
SERVICES: WhatsApp Agents, SMS Agents, Telegram Agents.
PRICING: Standard $750 one-time | Premium $1,500 + $250/month
HOW: Discovery Call > Design & Build > Test & Refine > Deploy & Monitor (1-week delivery)
Suggest CONTACT for a free quote or HUMAN to speak with the team.
Website: www.webwhizzy.com"""

WELCOME = ("Welcome to WebWhizzy!\n\n"
    "We build AI agents for WhatsApp, SMS & Telegram that handle your customer conversations 24/7.\n\n"
    "SERVICES - What we build\n"
    "PRICING - Plans & investment\n"
    "HOW - Our process\n"
    "CONTACT - Get a free quote\n"
    "HUMAN - Speak with our team\n\n"
    "Or just ask me anything.")

SERVICES = ("WebWhizzy AI Agents:\n\n"
    "WhatsApp Agents\nHandle queries, media, leads & follow-ups inside WhatsApp.\n\n"
    "SMS Agents\nReach every customer - no app required. Inquiries, updates & lead capture.\n\n"
    "Telegram Agents\nRich media, buttons, groups & deep automation.\n\n"
    "All available in Standard ($750) or Premium ($1,500+).\nReply PRICING for full details.")

PRICING = ("WebWhizzy Pricing\n\n"
    "STANDARD - $750 one-time\nNo monthly fees.\n"
    "- Custom bot (WhatsApp, SMS or Telegram)\n"
    "- Auto-replies, FAQs & lead collection\n"
    "- Rule-based workflows\n"
    "- 1-week delivery, 30-day support\n\n"
    "PREMIUM - $1,500 + $250/mo\nEverything in Standard, plus:\n"
    "- AI natural language understanding\n"
    "- Human handoff & live agent escalation\n"
    "- Admin alerts & daily summaries\n"
    "- Monthly updates & priority support\n\n"
    "Reply CONTACT to get a free quote.")

HOW = ("How WebWhizzy Works:\n\n"
    "01. Discovery Call\nWe learn your business & workflows.\n\n"
    "02. Design & Build\nYour custom agent is built.\n\n"
    "03. Test & Refine\nRigorous testing before launch.\n\n"
    "04. Deploy & Monitor\nYour agent goes live. Premium clients get ongoing support.\n\n"
    "Typical delivery: 1 week.\nReply CONTACT for a free scoping call.")

PLANS = {"1":"WhatsApp - Standard ($750 one-time)","2":"WhatsApp - Premium ($1,500 + $250/mo)",
         "3":"SMS - Standard ($750 one-time)","4":"SMS - Premium ($1,500 + $250/mo)",
         "5":"Telegram - Standard ($750 one-time)","6":"Telegram - Premium ($1,500 + $250/mo)","7":"Not sure yet - help me decide"}

PLAN_MENU = ("Which plan interests you?\n\n"
    "1. WhatsApp Standard ($750)\n2. WhatsApp Premium ($1,500+)\n"
    "3. SMS Standard ($750)\n4. SMS Premium ($1,500+)\n"
    "5. Telegram Standard ($750)\n6. Telegram Premium ($1,500+)\n"
    "7. Not sure yet\n\nReply with a number (1-7)")

def get_admin_numbers():
    admins = []
    if ADMIN_PHONE: admins.append(ADMIN_PHONE.strip())
    if ADMIN_PHONE_2: admins.append(ADMIN_PHONE_2.strip())
    return admins

def is_admin(phone): return phone in get_admin_numbers()

def get_sess(phone):
    if phone not in sessions:
        sessions[phone]={"state":IDLE,"contact":{},"history":[],"live_client":None}
    return sessions[phone]

def sms_out(to, body):
    if not twilio_client: logger.warning(f"[NO TWILIO] {body[:60]}"); return
    try: twilio_client.messages.create(to=to, from_=TWILIO_SMS_NUMBER, body=body[:1600])
    except Exception as e: logger.error(f"SMS fail: {e}")

def alert_admins(msg):
    for admin in get_admin_numbers(): sms_out(admin, msg)

def twiml(text):
    r=MessagingResponse(); r.message(text[:1600])
    return Response(str(r), mimetype="text/xml")

def empty(): return Response(str(MessagingResponse()), mimetype="text/xml")

def ask_claude(text, history):
    if not ANTHROPIC_API_KEY: return None
    msgs=history[-6:]+[{"role":"user","content":text}]
    payload=json.dumps({"model":"claude-haiku-4-5-20251001","max_tokens":250,"system":SYSTEM_PROMPT,"messages":msgs}).encode()
    req=urllib.request.Request("https://api.anthropic.com/v1/messages",data=payload,
        headers={"Content-Type":"application/json","x-api-key":ANTHROPIC_API_KEY,"anthropic-version":"2023-06-01"},method="POST")
    try:
        with urllib.request.urlopen(req,timeout=15) as r: return json.loads(r.read())["content"][0]["text"].strip()
    except Exception as e: logger.error(f"Claude: {e}"); return None

def kw(text,*words): return any(w in text.lower() for w in words)

@app.route("/sms",methods=["POST"])
def webhook():
    from_num=request.form.get("From","").strip()
    body=request.form.get("Body","").strip()
    if not from_num or not body: return empty()
    sess=get_sess(from_num); cmd=body.upper().strip()
    logger.info(f"SMS|{from_num[:8]}***|{sess['state']}|{body[:60]}")

    if is_admin(from_num):
        if cmd.startswith("REPLYTO "):
            parts=body.strip().split(" ",2)
            if len(parts)>=3:
                cnum,msg=parts[1].strip(),parts[2].strip()
                sms_out(cnum,f"WebWhizzy Team: {msg}")
                sess["state"]=ADMIN_REPLY; sess["live_client"]=cnum
                if cnum in sessions: sessions[cnum]["state"]=HUMAN_WAIT
                return twiml(f"Sent to {cnum}. Reply mode active. Send DONE to close.")
            return twiml("Usage: REPLYTO <number> <message>")
        if cmd.startswith("CLOSE "):
            parts=body.strip().split(" ",1)
            if len(parts)==2:
                cnum=parts[1].strip()
                sms_out(cnum,"Thank you for reaching out to WebWhizzy. Our team has closed this session. Text us anytime!")
                if cnum in sessions: sessions[cnum]["state"]=IDLE
                sess["state"]=IDLE; sess["live_client"]=None
                return twiml(f"Session with {cnum} closed.")
        if cmd=="DONE":
            cnum=sess.get("live_client")
            if cnum:
                sms_out(cnum,"Thank you for chatting with WebWhizzy! We look forward to working with you. Text us anytime.")
                if cnum in sessions: sessions[cnum]["state"]=IDLE
            sess["state"]=IDLE; sess["live_client"]=None
            return twiml("Session closed.")
        if sess["state"]==ADMIN_REPLY:
            cnum=sess.get("live_client")
            if cnum: sms_out(cnum,f"WebWhizzy Team: {body}"); return twiml("Delivered. Keep replying or DONE to close.")
            sess["state"]=IDLE; return twiml("No active session. Use REPLYTO <number> <message>.")

    if cmd in("START","MENU","HELP","HI","HELLO"): sess["state"]=IDLE; sess["history"]=[]; return twiml(WELCOME)
    if cmd in("STOP","UNSUBSCRIBE"): sess["state"]=IDLE; return twiml("Unsubscribed. Text START anytime to reconnect.")
    if cmd=="CANCEL": sess["state"]=IDLE; return twiml("No problem. Text MENU to see your options or ask me anything.")
    if cmd=="SERVICES": return twiml(SERVICES)
    if cmd=="PRICING": return twiml(PRICING)
    if cmd in("HOW","PROCESS"): return twiml(HOW)

    if cmd=="CONTACT":
        sess["state"]=FORM_FIRST; sess["contact"]={}
        return twiml("Great! Let's get you a free quote.\n\nI'll collect a few details and our team will reach out within 24 hours.\n\nWhat is your first name?")

    if cmd=="HUMAN":
        sess["state"]=HUMAN_WAIT
        c=sess["contact"]; name=f"{c.get('first_name','')} {c.get('last_name','')}".strip() or "A visitor"
        alert_admins(f"[WebWhizzy] Human Handoff\nName: {name}\nNumber: {from_num}\n\nReply: REPLYTO {from_num} <message>\nClose: CLOSE {from_num}")
        return twiml("Connecting you with our team now.\n\nA WebWhizzy team member has been notified and will reply shortly.\n\nGo ahead and type your message. (Text CANCEL to return to AI)")

    state=sess["state"]
    if state==FORM_FIRST:
        sess["contact"]["first_name"]=body.strip(); sess["state"]=FORM_LAST
        return twiml(f"Nice to meet you, {body.strip()}! What is your last name?")
    if state==FORM_LAST:
        sess["contact"]["last_name"]=body.strip(); sess["state"]=FORM_EMAIL
        return twiml("What is your email address?\n(We'll use this to send you our proposal.)")
    if state==FORM_EMAIL:
        if not __import__("re").match(r"[^@]+@[^@]+\.[^@]+",body.strip()): return twiml("That doesn't look valid. Please check and try again:")
        sess["contact"]["email"]=body.strip(); sess["state"]=FORM_BIZ
        return twiml("What is your business name?")
    if state==FORM_BIZ:
        sess["contact"]["business"]=body.strip(); sess["state"]=FORM_PLAN
        return twiml(PLAN_MENU)
    if state==FORM_PLAN:
        sess["contact"]["plan"]=PLANS.get(body.strip(),body.strip()); sess["state"]=FORM_NOTE
        return twiml("Almost done!\n\nAny specific details about your business or what you'd like to automate?\n(Reply SKIP to leave blank)")
    if state==FORM_NOTE:
        note="" if body.upper().strip()=="SKIP" else body.strip()
        sess["contact"]["note"]=note
        c=sess["contact"]; first,last=c.get("first_name",""),c.get("last_name","")
        email,biz,plan=c.get("email",""),c.get("business",""),c.get("plan","")
        confirm=(f"All done, {first}!\n\nEnquiry summary:\nName: {first} {last}\nEmail: {email}\nBusiness: {biz}\nPlan: {plan}\n")
        if note: confirm+=f"Notes: {note}\n"
        confirm+="\nOur team will contact you within 24 hours. Thank you for choosing WebWhizzy!"
        sess["state"]=IDLE; logger.info(f"LEAD|{first} {last}|{email}|{biz}|{plan}|{from_num}")
        amsg=(f"[WebWhizzy] New Lead\nName: {first} {last}\nEmail: {email}\nBusiness: {biz}\nPlan: {plan}\n"+(f"Notes: {note}\n" if note else "")+f"Phone: {from_num}\n\nREPLYTO {from_num} <message>")
        alert_admins(amsg); sess["contact"]={}; return twiml(confirm)
    if state==HUMAN_WAIT:
        c=sess["contact"]; name=f"{c.get('first_name','')} {c.get('last_name','')}".strip() or from_num
        alert_admins(f"[WebWhizzy] Msg from {name} ({from_num}):\n{body}\n\nREPLYTO {from_num} <message>\nCLOSE {from_num}")
        return twiml("Message received. Our team will reply shortly. Thank you for your patience.")

    if kw(body,"price","cost","how much","pricing","plan"): return twiml(PRICING)
    if kw(body,"service","what do you","offer","build"): return twiml(SERVICES)
    if kw(body,"how does","process","how do you"): return twiml(HOW)
    if kw(body,"hi","hello","hey","start"): sess["history"]=[]; return twiml(WELCOME)

    ai=ask_claude(body,sess["history"])
    if ai:
        sess["history"].append({"role":"user","content":body}); sess["history"].append({"role":"assistant","content":ai})
        if len(sess["history"])>12: sess["history"]=sess["history"][-12:]
        return twiml(ai)
    return twiml("I'm not sure how to help with that. Text MENU to see options, CONTACT for a quote, or HUMAN to speak with our team.")

@app.route("/",methods=["GET"])
def health():
    active=sum(1 for s in sessions.values() if s["state"]!=IDLE)
    return f"WebWhizzy SMS Bot | Active sessions: {active}", 200

if __name__=="__main__":
    port=int(os.getenv("PORT",5000))
    logger.info(f"WebWhizzy SMS Bot starting on port {port}")
    app.run(host="0.0.0.0",port=port)
