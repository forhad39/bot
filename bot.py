import requests
import time
from datetime import datetime, timezone

BASE_URL = "https://cashclub.sbs/"

def run(script):
    url = BASE_URL + script
    try:
        r = requests.get(url, timeout=10)
        print(f"{datetime.now(timezone.utc).isoformat()} | {script} | {r.status_code}")
    except Exception as e:
        print(f"{datetime.now(timezone.utc).isoformat()} | {script} | ERROR: {e}")

last_30 = None
last_60 = None
last_180 = None
last_300 = None
last_600 = None

while True:
    now = time.time()
    s30 = int(now // 30)
    s60 = int(now // 60)
    s180 = int(now // 180)
    s300 = int(now // 300)
    s600 = int(now // 600)

    if s30 != last_30:
        run("niyamitakelasa30sec.php")   # FIXED
        last_30 = s30

    if s60 != last_60:
        run("niyamitakelasa.php")
        run("niyamitakelasa_aidudi.php")
        run("niyamitakelasa_kemuru.php")
        run("ktrx.php")
        last_60 = s60

    if s180 != last_180:
        run("niyamitakelasa_drei.php")
        run("niyamitakelasa_aidudi_drei.php")
        run("niyamitakelasa_kemuru_drei.php")
        run("ktrx3.php")
        last_180 = s180

    if s300 != last_300:
        run("niyamitakelasa_funf.php")
        run("niyamitakelasa_aidudi_funf.php")
        run("niyamitakelasa_kemuru_funf.php")
        run("ktrx5.php")
        last_300 = s300

    if s600 != last_600:
        run("niyamitakelasa_zehn.php")
        run("niyamitakelasa_aidudi_zehn.php")
        run("niyamitakelasa_kemuru_zehn.php")
        run("ktrx10.php")
        last_600 = s600

    time.sleep(0.2)