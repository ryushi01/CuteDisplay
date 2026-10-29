#!/usr/bin/env python3
"""Interpret multilingual natural-language dates relative to an explicit local clock.

Dependency: dateparser. Pure parser; never assumes a plan was completed.
"""
import argparse, datetime as dt, json
from zoneinfo import ZoneInfo

LANGS=["en","fr","ja"]
def interpret(phrase, now, zone="Asia/Tokyo"):
    import dateparser
    tz=ZoneInfo(zone)
    if isinstance(now,str):now=dt.datetime.fromisoformat(now)
    if now.tzinfo is None:now=now.replace(tzinfo=tz)
    now=now.astimezone(tz)
    result=dateparser.parse(phrase,languages=LANGS,
        settings={"RELATIVE_BASE":now,"TIMEZONE":zone,"TO_TIMEZONE":zone,
                  "RETURN_AS_TIMEZONE_AWARE":True,"PREFER_DATES_FROM":"future",
                  "DATE_ORDER":"YMD"})
    if result is None:return {"resolved":False,"raw":phrase}
    return {"resolved":True,"date":result.astimezone(tz).date().isoformat(),
            "local_datetime":result.astimezone(tz).isoformat(),
            "timezone":zone,"outcome":"unconfirmed","raw":phrase}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--text",required=True);p.add_argument("--timezone",default="Asia/Tokyo")
    p.add_argument("--now",help="explicit ISO timestamp for tests; otherwise current local time")
    a=p.parse_args()
    now=dt.datetime.fromisoformat(a.now) if a.now else dt.datetime.now(ZoneInfo(a.timezone))
    print(json.dumps(interpret(a.text,now,a.timezone),ensure_ascii=False))
if __name__=="__main__":main()
