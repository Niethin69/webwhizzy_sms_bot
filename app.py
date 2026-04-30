#!/usr/bin/env python3
"""WebWhizzy SMS Bot v2 - Multi-admin support"""

import os, json, re, urllib.request, logging
from flask import Flask, request, Response
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client

ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_SMS_NUMBER  = os.getenv("TWILIO_SMS_NUMBER", "")
ADMIN_PHONE        = os.getenv("ADMIN_PHONE", "")        # primary alert destination
ADMIN_PHONE_2      = os.getenv("ADMIN_PHONE_2", "")      # optional second admin number

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN) if TWILIO_ACCOUNT_SID else None

IDLE="idle"; FORM_FIRST="ff"; FORM_LAST="fl"; FORM_EMAIL="fe"
FORM_BIZ="fb"; FORM_PLAN="fp"; FORM_NOTE="fn"; HUMAN_WAIT="hw"; ADMIN_REPLY="ar"
sessions: dict = {}

SYSTEM_PROMPT = """You are the WebWhizzy SMS assistant. WebWhizzy builds AI-powered agents for SMS and Telegram.
Keep replies SHORT (under 300 chars). Plain text only, no markdown.
SERVICES: SMS Agents + Telegram Agents. Standard $750 one-time. Premium $1500 + $250/mo.
Suggest CONTACT for quote, HUMAN for live agent. Be warm and concise."""

MENU = ("WebWhizzy - AI Agents for SMS & Telegram\n\n"
        "Reply with:\nSERVICES - What we build\n"
        "PRICING - Plans & costs\nHOW - How it works\n"
        "CONTACT - Free quote\nHUMAN - Talk to our team\n\n"
        "Or just ask me anything!")

PLANS = {"1":"SMS Standard ($750 one-time)","2":"SMS Premium ($1,500 + $250/mo)",
         "3":"Telegram Standard ($750 one-time)","4":"Telegram Premium ($1,500 + $250/mo)","5":"Not sure yet"}

FB = {
    "pricing": ("WebWhizzy Pricing:\n\nStandard - $750 (one-time)\nTemplate workflow, 1-week delivery, 30-day support.\n\n"
                "Premium - $1,500 + $250/mo\nCustom AI, automation, priority support.\n\nReply CONTACT for a free quote!"),
    "services": ("WebWhizzy builds:\n\nSMS Agents - Auto-replies, lead capture, follow-ups\n\n"
                 "Telegram Agents - Rich media, buttons, group management\n\nBoth in Standard ($750) or Premium ($1,500)"),
    "how": ("How it works:\n\n1. Discovery Call\n2. Design & Build\n3. Test & Refine\n4. Deploy & Monitor\n\n"
            "Ready in as little as 1 week!\nReply CONTACT to start."),
    "about": "WebWhizzy builds AI agents for SMS & Telegram that handle customer conversations 24/7.\n\nwww.webwhizzy.com",
    "default": "Not sure about that! Try: SERVICES, PRICING, HOW, CONTACT, or HUMAN",
}

KW = {"price|cost|pricing|plan|package":"pricing","service|sms|telegram|build|agent":"services",
      "how|process|work|step|timeline":"how","about|who|webwhizzy":"about",
      "hi|hello|hey|start|menu|help":"greeting","stop|unsubscribe|quit":"stop"}

def get_admin_numbers():
    """Return list of all admin numbers."""
    admins = []
    if ADMIN_PHONE: admins.append(ADMIN_PHONE.strip())
    if ADMIN_PHONE_2: admins.append(ADMIN_PHONE_2.strip())
    return admins

def is_admin(phone):
    """Check if a phone number belongs to admin."""
    return phone in get_admin_numbers()

def get_sess(phone):
    if phone not in sessions:
        sessions[phone]={"state":IDLE,"contact":{},"history":[],"live_client":None}
    return sessions[phone]

def sms_out(to, body):
    if not twilio_client: logger.warning(f"[NO TWILIO] {body[:60]}"); return
    try: twilio_client.messages.create(to=to, from_=TWILIO_SMS_NUMBER, body=body[:1600])
    except Exception as e: logger.error(f"SMS fail: {e}")

def alert_admin(msg):
    """Send alert to all admin numbers."""
    for admin in get_admin_numbers():
        sms_out(admin, msg)

def twiml(text):
    r=MessagingResponse(); r.message(text[:1600])
    return Response(str(r), mimetype="text/xml")

def empty():
    return Response(str(MessagingResponse()), mimetype="text/xml")

def ask_claude(text, history):
    if not ANTHROPIC_API_KEY: return None
    msgs=history[-6:]+[{"role":"user","content":text}]
    payload=json.dumps({"model":"claude-haiku-4-5-20251001","max_tokens":200,
        "system":SYSTEM_PROMPT,"messages":msgs}).encode()
    req=urllib.request.Request("https://api.anthropic.com/v1/messages",data=payload,
        headers={"Content-Type":"application/json","x-api-key":ANTHROPIC_API_KEY,
                 "anthropic-version":"2023-06-01"},method="POST")
    try:
        with urllib.request.urlopen(req,timeout=15) as r: return json.loads(r.read())["content"][0]["text"].strip()
    except Exception as e: logger.error(f"Claude: {e}"); return None

def kw_match(text):
    t=text.lower()
    for pat,intent in KW.items():
        if any(k in t for k in pat.split("|")): return intent
    return None

@app.route("/sms",methods=["POST"])
def webhook():
    from_num=request.form.get("From","").strip()
    body=request.form.get("Body","").strip()
    if not from_num or not body: return empty()
    sess=get_sess(from_num); cmd=body.upper().strip()
    logger.info(f"SMS|{from_num[:8]}***|{sess['state']}|{body[:50]}")

    # ── Admin commands (from any registered admin number) ───────────────────
    if is_admin(from_num):
        if cmd.startswith("REPLYTO "):
            parts=body.strip().split(" ",2)
            if len(parts)>=3:
                cnum,msg=parts[1].strip(),parts[2].strip()
                sms_out(cnum,f"WebWhizzy Agent: {msg}")
                sess["state"]=ADMIN_REPLY; sess["live_client"]=cnum
                if cnum in sessions: sessions[cnum]["state"]=HUMAN_WAIT
                return twiml(f"Sent to {cnum}. Reply mode on. Send DONE to close.")
            return twiml("Usage: REPLYTO <number> <message>")

        if cmd.startswith("CLOSE "):
            parts=body.strip().split(" ",1)
            if len(parts)==2:
                cnum=parts[1].strip()
                sms_out(cnum,"Chat ended. Text us anytime - WebWhizzy")
                if cnum in sessions: sessions[cnum]["state"]=IDLE
                sess["state"]=IDLE; sess["live_client"]=None
                return twiml(f"Session with {cnum} closed.")

        if cmd=="DONE":
            cnum=sess.get("live_client")
            if cnum:
                sms_out(cnum,"Chat ended. Thanks for reaching out to WebWhizzy!")
                if cnum in sessions: sessions[cnum]["state"]=IDLE
            sess["state"]=IDLE; sess["live_client"]=None
            return twiml("Session closed.")

        if sess["state"]==ADMIN_REPLY:
            cnum=sess.get("live_client")
            if cnum:
                sms_out(cnum,f"WebWhizzy Agent: {body}")
                return twiml("Sent! Keep replying or DONE to close.")
            sess["state"]=IDLE
            return twiml("No active session. Use REPLYTO <number> <message>.")

    # ── Global client commands ──────────────────────────────────────────────
    if cmd in("START","MENU","HELP"): sess["state"]=IDLE; sess["history"]=[]; return twiml(MENU)
    if cmd in("STOP","UNSUBSCRIBE","QUIT"): sess["state"]=IDLE; return twiml("Unsubscribed. Text START anytime.")
    if cmd=="CANCEL": sess["state"]=IDLE; return twiml("No problem! Text MENU anytime.")

    if cmd=="CONTACT":
        sess["state"]=FORM_FIRST; sess["contact"]={}
        return twiml("Let's get you connected!\n\nWhat is your first name?")

    if cmd=="HUMAN":
        sess["state"]=HUMAN_WAIT
        c=sess["contact"]; name=f"{c.get('first_name','')} {c.get('last_name','')}".strip() or "Someone"
        alert_admin(f"WebWhizzy: Human request!\nName: {name}\nPhone: {from_num}\n\nReply: REPLYTO {from_num} msg\nClose: CLOSE {from_num}")
        return twiml("Connecting you to our team! An agent has been notified.\n\nType your message now.\n(Text CANCEL to return to AI)")

    if cmd in("SERVICES","SERVICE"): return twiml(FB["services"])
    if cmd=="PRICING": return twiml(FB["pricing"])
    if cmd in("HOW","HOWITWORKS"): return twiml(FB["how"])
    if cmd=="ABOUT": return twiml(FB["about"])

    # ── State machine ───────────────────────────────────────────────────────
    state=sess["state"]
    if state==FORM_FIRST:
        sess["contact"]["first_name"]=body.strip(); sess["state"]=FORM_LAST
        return twiml(f"Nice to meet you, {body.strip()}!\n\nWhat is your last name?")
    if state==FORM_LAST:
        sess["contact"]["last_name"]=body.strip(); sess["state"]=FORM_EMAIL
        return twiml("What is your email address?")
    if state==FORM_EMAIL:
        if not re.match(r"[^@]+@[^@]+\.[^@]+",body.strip()): return twiml("That doesn't look right. Please check your email.")
        sess["contact"]["email"]=body.strip(); sess["state"]=FORM_BIZ
        return twiml("What is your business name?")
    if state==FORM_BIZ:
        sess["contact"]["business"]=body.strip(); sess["state"]=FORM_PLAN
        return twiml("Which plan interests you?\n\n1. SMS Standard ($750)\n2. SMS Premium ($1,500+)\n3. Telegram Standard ($750)\n4. Telegram Premium ($1,500+)\n5. Not sure\n\nReply 1-5")
    if state==FORM_PLAN:
        sess["contact"]["plan"]=PLANS.get(body.strip(),body.strip()); sess["state"]=FORM_NOTE
        return twiml("Almost done!\n\nAny details about your business or automation needs?\n(Reply SKIP to leave blank)")
    if state==FORM_NOTE:
        note="" if body.upper().strip()=="SKIP" else body.strip()
        sess["contact"]["note"]=note
        c=sess["contact"]; first,last=c.get("first_name",""),c.get("last_name","")
        email,biz,plan=c.get("email",""),c.get("business",""),c.get("plan","")
        confirm=(f"All done, {first}!\n\nName: {first} {last}\nEmail: {email}\nBusiness: {biz}\nPlan: {plan}\n")
        if note: confirm+=f"Note: {note}\n"
        confirm+="\nWe will be in touch within 24 hours!"
        sess["state"]=IDLE; logger.info(f"LEAD|{first} {last}|{email}|{biz}|{plan}|{from_num}")
        alert_admin(f"WebWhizzy New Lead!\nName: {first} {last}\nEmail: {email}\nBusiness: {biz}\nPlan: {plan}\n" +
                   (f"Note: {note}\n" if note else "") + f"Phone: {from_num}\n\nReply: REPLYTO {from_num} msg")
        sess["contact"]={}; return twiml(confirm)
    if state==HUMAN_WAIT:
        c=sess["contact"]; name=f"{c.get('first_name','')} {c.get('last_name','')}".strip() or from_num
        alert_admin(f"Msg from {name} ({from_num}):\n{body}\n\nReply: REPLYTO {from_num} msg\nClose: CLOSE {from_num}")
        return twiml("Message sent to our team! They will reply shortly.")

    # ── AI then keyword fallback ─────────────────────────────────────────────
    ai=ask_claude(body,sess["history"])
    if ai:
        sess["history"].append({"role":"user","content":body})
        sess["history"].append({"role":"assistant","content":ai})
        if len(sess["history"])>12: sess["history"]=sess["history"][-12:]
        return twiml(ai)
    intent=kw_match(body)
    if intent=="greeting": sess["history"]=[]; return twiml(MENU)
    if intent=="stop": return twiml("Unsubscribed. Text START anytime.")
    if intent and intent in FB: return twiml(FB[intent])
    return twiml(FB["default"])

@app.route("/",methods=["GET"])
def health():
    active=sum(1 for s in sessions.values() if s["state"]!=IDLE)
    return f"WebWhizzy SMS Bot v2 running | Active sessions: {active}", 200

if __name__=="__main__":
    port=int(os.getenv("PORT",5000))
    logger.info(f"Starting on port {port}")
    app.run(host="0.0.0.0",port=port)
