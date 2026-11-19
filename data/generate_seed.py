#!/usr/bin/env python3
"""Deterministic synthetic seed data for PAYTM_MERCH_8821 ("Sharma Electronics", Gurugram).

    python data/generate_seed.py        # writes data/seed/*, then validates everything

Standard library + pandas only. Fixed seed, so every run produces identical files.
All data is synthetic: names, phone numbers, GSTIN, UTRs and addresses are invented.
"""
from __future__ import annotations

import json
import math
import random
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

# ============================================================================ constants
SEED = 8821
rng = random.Random(SEED)
OUT = Path(__file__).resolve().parent / "seed"

MID = "PAYTM_MERCH_8821"
NAME = "Sharma Electronics"
START, END = date(2026, 5, 19), date(2026, 11, 18)
DAYS = [START + timedelta(days=i) for i in range((END - START).days + 1)]
DEMO_DAY = date(2026, 11, 19)                  # the day the demo is "live"
SNAPSHOT = datetime(2026, 11, 19, 9, 0)        # data is as of 09:00 IST on demo day
DAILY_AVG = 32000
TOTAL_GROSS = DAILY_AVG * len(DAYS)            # 184 days -> ₹58,88,000

DIWALI = date(2026, 11, 8)
DHANTERAS = date(2026, 11, 6)
BULK_DAY = date(2026, 11, 17)                  # settled in the contract batch of 2026-11-18
CLOSURE_DAYS = {date(2026, 11, 14), date(2026, 11, 15), date(2026, 11, 16)}
EDI_BOUNCES = {  # eNACH presentment date -> (reason code, reason, cause)
    date(2026, 7, 14): ("INSUFFICIENT_FUNDS", "Balance insufficient", "heavy rain 12-13 Jul"),
    date(2026, 7, 28): ("INSUFFICIENT_FUNDS", "Balance insufficient", "heavy rain 26-27 Jul"),
    date(2026, 8, 11): ("INSUFFICIENT_FUNDS", "Balance insufficient", "heavy rain 9-10 Aug"),
    date(2026, 8, 19): ("INSUFFICIENT_FUNDS", "Balance insufficient", "heavy rain 17-18 Aug"),
    date(2026, 9, 22): ("TECHNICAL_DEST_BANK_TIMEOUT", "Destination bank not reachable", "bank-side outage"),
    date(2026, 10, 13): ("INSUFFICIENT_FUNDS", "Balance insufficient", "₹38,000 Diwali stock paid on 12 Oct"),
    date(2026, 11, 17): ("INSUFFICIENT_FUNDS", "Balance insufficient", "market closure 14-16 Nov (sales -40%)"),
}
RAIN_DAYS = {b - timedelta(days=k) for b, v in EDI_BOUNCES.items() if v[2].startswith("heavy rain") for k in (1, 2)}

# ---- HARD CONSTRAINTS (contract.md / plan.md): must appear exactly -----------------
HISTORICAL_MEMORY = {
    "daily_avg_sales": 32000,
    "weekend_multiplier": "2.3x (Fri–Sun)",
    "past_edi_success_rate": "96%",
    "tomorrow_stock_payable": 4500,
    "active_lender": "Clix Capital",
    "daily_edi": 500,
    "loan_balance": 42000,
    "kfs_edi_holiday_eligible": True,
}
CONTRACT_SETTLEMENT = {"settlement_date": "2026-11-18", "gross": 100000, "net": 95840, "variance": 4160,
                       "mdr": 1450, "gst_on_mdr": 261, "refund_4412": 1500, "soundbox_rental": 149,
                       "chargeback_hold_9981": 800}
CONNECTORS = {"SHIPROCKET_SYNC": "ACTIVE", "VYAPAR_POS_SYNC": "ACTIVE", "RBI_ACCOUNT_AGGREGATOR": "ACTIVE"}
UTR_SUCCESS, UTR_PENDING, UTR_FAKE = "632184920111", "632184920999", "632184920555"
MDR_RATES = {"credit_card": 0.02, "postpaid": 0.02, "wallet_above_2k": 0.011, "upi": 0.0, "debit_card_rupay": 0.0}
SOUNDBOX_RENTAL, RENTAL_DAY = 149, 18

# ============================================================================ helpers
def pick(weights: dict):
    keys = list(weights)
    return rng.choices(keys, weights=[weights[k] for k in keys])[0]


def ts(d: date, h: int, m: int, s: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, h, m, s)


HOUR_WEIGHTS = {7: 8, 8: 10, 9: 9, 10: 6, 11: 5, 12: 4, 13: 4, 14: 3, 15: 3, 16: 4, 17: 6, 18: 9, 19: 10, 20: 9, 21: 6}


def random_time(d: date) -> datetime:
    return ts(d, pick(HOUR_WEIGHTS), rng.randrange(60), rng.randrange(60))


def is_weekend(d: date) -> bool:
    return d.weekday() >= 4  # Fri, Sat, Sun


def money(x: float) -> int:
    return int(math.floor(x + 0.5))  # round half up, INR integers


def mdr_for(method: str, card_type: str | None, amount: int) -> float:
    if method == "card" and card_type == "credit":
        return round(amount * MDR_RATES["credit_card"], 2)
    if method == "postpaid":
        return round(amount * MDR_RATES["postpaid"], 2)
    if method == "wallet" and amount > 2000:
        return round(amount * MDR_RATES["wallet_above_2k"], 2)
    return 0.0  # UPI P2M and RuPay debit: zero MDR


_used_utrs = {UTR_SUCCESS, UTR_PENDING, UTR_FAKE}


def new_utr(d: date) -> str:
    while True:
        u = f"6{d.timetuple().tm_yday:03d}{rng.randrange(10**8):08d}"
        if u not in _used_utrs:
            _used_utrs.add(u)
            return u


# ============================================================================ catalogue
# (sku, name, brand, category, unit, cost, selling, mrp, supplier, reorder_point)
SKUS = [
    # Lighting
    ("LGT-PHI-10W2", "Philips 10W LED Bulb (pack of 2)", "Philips", "Lighting", "pack", 210, 250, 290, "Signify/Philips Lighting (via Gupta Electricals)", 20),
    ("LGT-SYS-9W", "Syska 9W LED Bulb", "Syska", "Lighting", "pc", 85, 99, 120, "Gaffar Market accessories wholesaler", 30),
    ("LGT-HAV-BAT20", "Havells 20W LED Batten 4ft", "Havells", "Lighting", "pc", 290, 340, 399, "Havells (via Gupta Electricals)", 12),
    ("LGT-WIP-PNL15", "Wipro 15W LED Square Panel", "Wipro", "Lighting", "pc", 420, 480, 550, "Gaffar Market accessories wholesaler", 10),
    # Fans
    ("FAN-CRO-HS12", "Crompton HS Plus 1200mm Ceiling Fan", "Crompton", "Fans", "pc", 1850, 2150, 2600, "Crompton Greaves Consumer (via Jain Distributors)", 6),
    ("FAN-HAV-PAC12", "Havells Pacer 1200mm Ceiling Fan", "Havells", "Fans", "pc", 2100, 2450, 2900, "Havells (via Gupta Electricals)", 4),
    ("FAN-USH-TBL40", "Usha 400mm Table Fan", "Usha", "Fans", "pc", 1750, 2050, 2400, "Jain Distributors", 4),
    ("FAN-BAJ-PED", "Bajaj Pedestal Fan 400mm", "Bajaj", "Fans", "pc", 2300, 2700, 3200, "Bajaj Electricals (via Jain Distributors)", 3),
    ("FAN-BAJ-EXH15", "Bajaj Exhaust Fan 150mm", "Bajaj", "Fans", "pc", 1050, 1250, 1500, "Bajaj Electricals (via Jain Distributors)", 4),
    # Kitchen & home appliances
    ("KIT-PHI-KTL15", "Philips Electric Kettle 1.5L", "Philips", "Kitchen Appliances", "pc", 1250, 1500, 1795, "Signify/Philips Lighting (via Gupta Electricals)", 4),
    ("KIT-PRE-KTL15", "Prestige Electric Kettle 1.5L", "Prestige", "Kitchen Appliances", "pc", 950, 1150, 1495, "Jain Distributors", 4),
    ("KIT-BAJ-MIX500", "Bajaj Mixer Grinder 500W (3 jars)", "Bajaj", "Kitchen Appliances", "pc", 2600, 3000, 3600, "Bajaj Electricals (via Jain Distributors)", 3),
    ("KIT-PRE-IND", "Prestige Induction Cooktop 2000W", "Prestige", "Kitchen Appliances", "pc", 2300, 2700, 3300, "Jain Distributors", 3),
    ("KIT-BAJ-OTG16", "Bajaj OTG 16L", "Bajaj", "Kitchen Appliances", "pc", 4100, 4700, 5500, "Bajaj Electricals (via Jain Distributors)", 2),
    ("HOM-HAV-STIRN", "Havells Steam Iron 1250W", "Havells", "Home Appliances", "pc", 1400, 1650, 2000, "Havells (via Gupta Electricals)", 4),
    ("HOM-BAJ-DIRN", "Bajaj Dry Iron 750W", "Bajaj", "Home Appliances", "pc", 650, 750, 950, "Bajaj Electricals (via Jain Distributors)", 5),
    ("HOM-CRO-GYS15", "Crompton 15L Storage Water Heater", "Crompton", "Water Heaters", "pc", 6800, 7800, 9500, "Crompton Greaves Consumer (via Jain Distributors)", 2),
    ("HOM-HAV-GYS3", "Havells 3L Instant Water Heater", "Havells", "Water Heaters", "pc", 3900, 4500, 5400, "Havells (via Gupta Electricals)", 2),
    # Electricals
    ("ELC-ANC-SW6A", "Anchor Roma 6A Switch", "Anchor", "Switches & Wiring", "pc", 25, 32, 38, "Panasonic Anchor (via Gupta Electricals)", 50),
    ("ELC-ANC-SKT", "Anchor Roma 6A 5-pin Socket", "Anchor", "Switches & Wiring", "pc", 60, 75, 90, "Panasonic Anchor (via Gupta Electricals)", 30),
    ("ELC-HAV-EXT41", "Havells 4+1 Extension Board", "Havells", "Switches & Wiring", "pc", 420, 499, 599, "Havells (via Gupta Electricals)", 10),
    ("ELC-POL-W15", "Polycab 1.5 sq mm Wire (90m coil)", "Polycab", "Switches & Wiring", "coil", 1450, 1700, 2000, "Polycab Wires (via Gupta Electricals)", 6),
    ("ELC-ANC-MCB32", "Anchor 32A MCB (single pole)", "Anchor", "Switches & Wiring", "pc", 180, 220, 260, "Panasonic Anchor (via Gupta Electricals)", 10),
    # Mobile accessories
    ("MOB-MI-CHG33", "Xiaomi 33W USB-C Charger", "Xiaomi", "Mobile Accessories", "pc", 620, 749, 999, "Gaffar Market accessories wholesaler", 10),
    ("MOB-SAM-CHG25", "Samsung 25W USB-C Charger", "Samsung", "Mobile Accessories", "pc", 900, 1099, 1299, "Gaffar Market accessories wholesaler", 6),
    ("MOB-BOT-BH100", "boAt Bassheads 100 Wired Earphones", "boAt", "Mobile Accessories", "pc", 330, 400, 999, "boAt distributor (Imagine Marketing)", 15),
    ("MOB-BOT-AD141", "boAt Airdopes 141 TWS Earbuds", "boAt", "Mobile Accessories", "pc", 1150, 1299, 4490, "boAt distributor (Imagine Marketing)", 8),
    ("MOB-POR-CAB1M", "Portronics USB-C Cable 1m", "Portronics", "Mobile Accessories", "pc", 110, 150, 299, "Gaffar Market accessories wholesaler", 25),
    ("MOB-AMB-PB10K", "Ambrane 10000mAh Power Bank", "Ambrane", "Mobile Accessories", "pc", 750, 899, 1499, "Gaffar Market accessories wholesaler", 8),
    ("MOB-GEN-TGL", "Tempered Glass Screen Guard", "Generic", "Mobile Accessories", "pc", 40, 150, 299, "Gaffar Market accessories wholesaler", 40),
    ("MOB-GEN-CVR", "Phone Back Cover", "Generic", "Mobile Accessories", "pc", 60, 199, 499, "Gaffar Market accessories wholesaler", 40),
    # Batteries & small items
    ("BAT-DUR-AA4", "Duracell AA Batteries (pack of 4)", "Duracell", "Batteries", "pack", 120, 140, 160, "Gaffar Market accessories wholesaler", 20),
    ("BAT-EVR-AAA10", "Eveready AAA Batteries (pack of 10)", "Eveready", "Batteries", "pack", 150, 180, 210, "Gaffar Market accessories wholesaler", 15),
    ("ACC-GEN-REM", "Universal TV Remote", "Generic", "TV Accessories", "pc", 150, 250, 399, "Gaffar Market accessories wholesaler", 10),
    # Audio, TV, phones
    ("AUD-JBL-GO3", "JBL Go 3 Bluetooth Speaker", "JBL", "Audio", "pc", 2300, 2700, 3999, "Gaffar Market accessories wholesaler", 3),
    ("TV-MI-32", "Xiaomi 32-inch Smart LED TV", "Xiaomi", "Televisions", "pc", 13000, 14500, 24999, "Jain Distributors", 2),
    ("TV-SAM-43", "Samsung 43-inch Crystal 4K TV", "Samsung", "Televisions", "pc", 26000, 28500, 45900, "Jain Distributors", 1),
    ("PHN-RED-13C", "Redmi 13C 5G (4GB/128GB)", "Redmi", "Smartphones", "pc", 9800, 10499, 13999, "Jain Distributors", 2),
    ("PHN-SAM-M15", "Samsung Galaxy M15 5G (6GB/128GB)", "Samsung", "Smartphones", "pc", 12500, 13499, 16999, "Jain Distributors", 2),
]
SKU = {s[0]: s for s in SKUS}
PRICE = {s[0]: s[6] for s in SKUS}

# ============================================================================ customers
FIRST = ["Ramesh", "Suresh", "Anil", "Sunil", "Rajesh", "Mukesh", "Deepak", "Amit", "Sanjay", "Vijay", "Manoj", "Rakesh",
         "Pankaj", "Ashok", "Naresh", "Rohit", "Vikram", "Karan", "Arjun", "Nitin", "Sunita", "Anita", "Kavita", "Rekha",
         "Pooja", "Neha", "Priya", "Seema", "Meena", "Geeta", "Anjali", "Ritu", "Shalini", "Komal", "Payal", "Swati",
         "Babita", "Kiran", "Nisha", "Jyoti"]
LAST = ["Sharma", "Verma", "Gupta", "Yadav", "Singh", "Chauhan", "Malhotra", "Arora", "Kapoor", "Mehta", "Agarwal",
        "Bansal", "Saini", "Rawat", "Tiwari", "Mishra", "Joshi", "Bhatia", "Khanna", "Ahuja", "Dahiya", "Rana"]
GGN_LOCALITIES = ["Sector 14", "Sector 15", "Sector 17", "Sector 12A", "Old Gurgaon", "Shivaji Nagar", "Jacobpura",
                  "Civil Lines", "Sushant Lok 1", "Sector 22"]
NCR_LOCALITIES = ["Lajpat Nagar, New Delhi", "Dwarka Sector 10, New Delhi", "Sector 21, Faridabad", "Sector 62, Noida",
                  "Janakpuri, New Delhi", "Palam Vihar, Gurugram", "DLF Phase 3, Gurugram", "Sohna Road, Gurugram"]

FIXED_CUSTOMERS = {
    "C017": ("Sunita Yadav", "Sector 14", "regular"),             # duplicate PhonePe payment
    "C042": ("Rohit Verma", "Lajpat Nagar, New Delhi", "ondc"),   # chargeback #9981 (matches sample PoD)
    "C063": ("Ravi Rao (Rao PG & Hostels)", "Sector 15", "bulk"),  # ₹55,000 PG fit-out order
    "C077": ("Anjali Mehta", "Sector 15", "regular"),             # refund #4412
    "C088": ("Pooja Arora", "Sector 17", "regular"),              # UTR 632184920111
    "C095": ("Vikram Singh", "Shivaji Nagar", "regular"),         # UTR 632184920999 (pending)
    "C120": ("Neha Kapoor", "Sushant Lok 1", "regular"),          # order #4490 -> refund request
}
KHATA_CUSTOMERS = ["C005", "C011", "C023", "C037", "C054", "C071", "C099", "C133"]
ONDC_CUSTOMERS = [f"C{i:03d}" for i in range(31, 51)]

customers = []
used_names = {v[0] for v in FIXED_CUSTOMERS.values()}
for i in range(1, 151):
    cid = f"C{i:03d}"
    if cid in FIXED_CUSTOMERS:
        name, loc, seg = FIXED_CUSTOMERS[cid]
    else:
        while True:
            name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
            if name not in used_names:
                used_names.add(name)
                break
        if cid in ONDC_CUSTOMERS:
            loc, seg = rng.choice(NCR_LOCALITIES), "ondc"
        else:
            loc, seg = rng.choice(GGN_LOCALITIES), "regular"
        if cid in KHATA_CUSTOMERS:
            name, seg = f"{name} (electrician)", "electrician"
    customers.append({
        "customer_id": cid, "name": name, "phone_masked": f"9{rng.randrange(10)}XXXXXX{rng.randrange(100):02d}",
        "locality": loc, "segment": seg, "first_seen": None, "on_khata": cid in KHATA_CUSTOMERS,
        "preferred_app": pick({"Paytm": 36, "PhonePe": 31, "GPay": 27, "BHIM": 3, "Amazon Pay": 3}),
    })
customers.append({"customer_id": "WALKIN", "name": "Walk-in customer (unidentified)", "phone_masked": None,
                  "locality": None, "segment": "walk_in", "first_seen": None, "on_khata": False, "preferred_app": None})
CUST = {c["customer_id"]: c for c in customers}
INSTORE_REGULARS = [c["customer_id"] for c in customers if c["segment"] in ("regular", "electrician")]
INSTORE_WEIGHTS = [1 / (i + 1) ** 0.6 for i in range(len(INSTORE_REGULARS))]


def instore_customer() -> str:
    if rng.random() < 0.62:  # electronics: more one-off shoppers than a kirana
        return "WALKIN"
    return rng.choices(INSTORE_REGULARS, weights=INSTORE_WEIGHTS)[0]


# ============================================================================ daily targets
def season(d: date, idx: int) -> float:
    m = 1 + 0.08 * idx / (len(DAYS) - 1)              # slow growth over 6 months
    if d <= date(2026, 6, 30):
        m *= 1.15                                      # summer: fans, coolers, exhausts
    if date(2026, 7, 1) <= d <= date(2026, 8, 31):
        m *= 0.85                                      # monsoon dip
    if d in RAIN_DAYS:
        m *= 0.65                                      # heavy-rain days
    if date(2026, 10, 31) <= d <= date(2026, 11, 7):
        m *= 1.45                                      # Diwali run-up
    if d == DHANTERAS:
        m *= 1.9                                       # Dhanteras: buying appliances is auspicious
    if d == DIWALI:
        m *= 1.1
    if d in (date(2026, 11, 9), date(2026, 11, 10)):
        m *= 0.85                                      # post-festival lull
    if d in CLOSURE_DAYS:
        m *= 0.60                                      # market closure: ~40% dip
    return m


noise = {d: math.exp(rng.gauss(0, 0.07)) for d in DAYS}
weekend_factor = 2.3
for _ in range(25):  # calibrate so the *observed* Fri–Sun / Mon–Thu ratio is 2.3 with all effects included
    base = {d: (weekend_factor if is_weekend(d) else 1.0) * season(d, i) * noise[d]
            for i, d in enumerate(DAYS) if d != BULK_DAY}
    k = (TOTAL_GROSS - CONTRACT_SETTLEMENT["gross"]) / sum(base.values())
    target = {d: money(k * v) for d, v in base.items()}
    target[BULK_DAY] = CONTRACT_SETTLEMENT["gross"]
    we = [target[d] for d in DAYS if is_weekend(d)]
    wd = [target[d] for d in DAYS if not is_weekend(d)]
    ratio = (sum(we) / len(we)) / (sum(wd) / len(wd))
    weekend_factor *= 2.3 / ratio
diff = TOTAL_GROSS - sum(target.values())
target[date(2026, 6, 10)] += diff                  # absorb rounding on an ordinary Wednesday

# ============================================================================ orders with numbers
# Two numbered series exist besides plain POS bills:
#   44xx  phone / home-delivery orders billed in Vyapar (in-store channel)
#   99xx  ONDC orders shipped through Shiprocket
NUMBERED: list[dict] = []
anchor_4412 = ts(date(2026, 10, 10), 11, 20)  # kettle bought early as a Diwali gift
anchor_4490 = ts(date(2026, 11, 18), 20, 30)
bulk_ts = ts(BULK_DAY, 10, 40)
dup_ts1, dup_ts2 = ts(END, 19, 42, 10), ts(END, 19, 42, 58)

before = []
for d in DAYS:
    if d >= anchor_4412.date():
        break
    for _ in range(max(1, round(rng.choice([2, 3, 3, 3, 4]) * target[d] / DAILY_AVG))):
        before.append(random_time(d))
between = []
candidates = [d for d in DAYS if anchor_4412.date() <= d <= END and d != BULK_DAY]
cand_w = [target[d] for d in candidates]  # busier days get more phone orders
while len(between) < 75:  # + PG bulk order + duplicate = exactly 77 orders between #4412 and #4490
    t = random_time(rng.choices(candidates, weights=cand_w)[0])
    if anchor_4412 < t < anchor_4490 and t not in (dup_ts1,):
        between.append(t)
specials_between = [(bulk_ts, "BULK"), (dup_ts1, "DUPLICATE")]
series = sorted([(t, "RANDOM") for t in before]) + [(anchor_4412, "R4412")] + \
    sorted([(t, "RANDOM") for t in between] + specials_between) + [(anchor_4490, "R4490"), (ts(END, 21, 10), "RANDOM")]
idx4412 = [i for i, s in enumerate(series) if s[1] == "R4412"][0]
order_id_of = {}
for i, (t, tag) in enumerate(series):
    oid = str(4412 + i - idx4412)
    NUMBERED.append({"order_id": oid, "ts": t, "tag": tag})
    order_id_of[tag] = oid
assert order_id_of["R4490"] == "4490", order_id_of["R4490"]
DUP_ORDER = order_id_of["DUPLICATE"]
BULK_ORDER_ID = order_id_of["BULK"]

# ONDC orders (99xx), anchored so the 14 Nov order is #9981
ondc_times = []
for d in DAYS:
    if d == BULK_DAY:
        continue
    if rng.random() < 0.55:
        ondc_times.append((random_time(d), "RANDOM"))
ondc_times.append((ts(date(2026, 11, 14), 10, 15), "CB9981"))
ondc_times.sort()
idx9981 = [i for i, s in enumerate(ondc_times) if s[1] == "CB9981"][0]
ONDC = []
for i, (t, tag) in enumerate(ondc_times):
    ONDC.append({"order_id": str(9981 + i - idx9981), "ts": t, "tag": tag})
assert ONDC[idx9981]["order_id"] == "9981"


def basket(n_min=2, n_max=4) -> list[dict]:
    small = [s for s in SKU if PRICE[s] <= 1500]  # accessories, bulbs, kettles: what ships well via ONDC
    skus = rng.sample(small, rng.randint(n_min, n_max))
    return [{"sku": s, "name": SKU[s][1], "qty": rng.randint(1, 2), "price": PRICE[s]} for s in skus]


for o in ONDC:
    if o["tag"] == "CB9981":
        o["items"] = [{"sku": "LGT-PHI-10W2", "name": SKU["LGT-PHI-10W2"][1], "qty": 1, "price": 250},
                      {"sku": "MOB-BOT-BH100", "name": SKU["MOB-BOT-BH100"][1], "qty": 1, "price": 400},
                      {"sku": "MOB-POR-CAB1M", "name": SKU["MOB-POR-CAB1M"][1], "qty": 1, "price": 150}]
        o["customer_id"] = "C042"
    else:
        o["items"] = basket(1, 3)
        o["customer_id"] = rng.choice(ONDC_CUSTOMERS)
    o["amount"] = sum(it["qty"] * it["price"] for it in o["items"])
assert [o for o in ONDC if o["order_id"] == "9981"][0]["amount"] == 800

# ============================================================================ transactions
UPI_APPS = {"Paytm": 36, "PhonePe": 31, "GPay": 27, "BHIM": 3, "Amazon Pay": 3}


SMALL_MAX, BIG_MIN = 600, 2500


def small_amount() -> int:  # bulbs, cables, switches, batteries, screen guards
    return max(30, min(SMALL_MAX, int(rng.lognormvariate(math.log(180), 0.7))))


def instore_amount() -> int:
    r = rng.random()
    if r < 0.70:
        return small_amount()
    if r < 0.94:
        return rng.randint(SMALL_MAX + 1, BIG_MIN - 1)  # chargers, earbuds, irons, kettles, extension boards
    if r < 0.995:
        return rng.randint(BIG_MIN, 12000)              # fans, mixers, geysers, speakers
    return rng.randint(12000, 40000)                    # TVs and phones


def instore_method(amount: int) -> tuple[str, str | None, str]:
    if amount >= BIG_MIN:
        m = pick({"UPI": 45, "credit": 30, "debit": 12, "wallet": 5, "postpaid": 8})
    elif amount > SMALL_MAX:
        m = pick({"UPI": 70, "credit": 12, "debit": 10, "wallet": 5, "postpaid": 3})
    else:
        m = pick({"UPI": 90, "wallet": 5, "debit": 3, "credit": 2})
    if m == "UPI":
        return "UPI", None, pick(UPI_APPS)
    if m in ("credit", "debit"):
        return "card", m, "Card (Soundbox tap/swipe)"
    if m == "wallet":
        return "wallet", None, "Paytm Wallet"
    return "postpaid", None, "Paytm Postpaid"


def make_txn(t: datetime, amount: int, method: str, card_type, app: str, customer: str, order_id: str | None,
             channel: str = "in-store", status: str = "SUCCESS", utr: str | None = None, tag: str | None = None) -> dict:
    if method in ("UPI", "wallet") and utr is None:
        utr = new_utr(t.date())
    return {"timestamp": t, "amount": amount, "method": method, "card_type": card_type, "payer_app": app,
            "utr": utr, "status": status, "customer_id": customer, "order_id": order_id, "channel": channel,
            "tag": tag}


def numbered_amount() -> int:  # phone orders: delivery + installation (fans, geysers, wiring)
    return rng.randint(500, 2800)


txns: list[dict] = []
numbered_by_day = defaultdict(list)
for o in NUMBERED:
    numbered_by_day[o["ts"].date()].append(o)
ondc_by_day = defaultdict(list)
for o in ONDC:
    ondc_by_day[o["ts"].date()].append(o)

for d in DAYS:
    day: list[dict] = []
    if d == BULK_DAY:
        # contract batch STL-20261118: card+postpaid ₹62,600 @2%, wallet ₹18,000 @1.1%, UPI ₹19,400 @0%
        # ₹55,000 = Rao PG & Hostels fit-out: 14 ceiling fans + 20 LED panels + 10 battens + wiring
        day.append(make_txn(bulk_ts, 55000, "card", "credit", "Card (Soundbox tap/swipe)", "C063", BULK_ORDER_ID,
                            tag="PG_FITOUT_BULK_ORDER"))
        for (h, mi), amt, meth in [((9, 5), 2400, "credit"), ((12, 30), 1850, "postpaid"), ((18, 20), 1600, "credit"),
                                    ((20, 15), 1750, "credit")]:
            m = "postpaid" if meth == "postpaid" else "card"
            ct = None if meth == "postpaid" else "credit"
            app = "Paytm Postpaid" if meth == "postpaid" else "Card (Soundbox tap/swipe)"
            day.append(make_txn(ts(d, h, mi, rng.randrange(60)), amt, m, ct, app, instore_customer(), None))
        for h, mi in [(8, 10), (11, 45), (13, 5), (17, 40), (19, 25), (21, 5)]:
            day.append(make_txn(ts(d, h, mi, rng.randrange(60)), 3000, "wallet", None, "Paytm Wallet",
                                rng.choice([c for c in INSTORE_REGULARS if CUST[c]["segment"] == "regular"]), None,
                                tag="WALLET_ABOVE_2K"))
        remaining = 19400
        while remaining > 0:
            a = small_amount() if rng.random() < 0.8 else rng.randint(SMALL_MAX + 1, 1800)
            if a >= remaining or remaining - a < 30:
                a = remaining
            day.append(make_txn(random_time(d), a, "UPI", None, pick(UPI_APPS), instore_customer(), None))
            remaining -= a
    else:
        for o in numbered_by_day.get(d, []):
            if o["tag"] == "R4412":
                day.append(make_txn(o["ts"], 1500, "UPI", None, "PhonePe", "C077", o["order_id"], tag="ORDER_4412"))
            elif o["tag"] == "R4490":
                day.append(make_txn(o["ts"], 3500, "wallet", None, "Paytm Wallet", "C120", o["order_id"], tag="ORDER_4490"))
            elif o["tag"] == "DUPLICATE":
                for k, t in enumerate((dup_ts1, dup_ts2)):
                    day.append(make_txn(t, 1180, "UPI", None, "PhonePe", "C017", o["order_id"],
                                        tag=f"DUPLICATE_PAYMENT_{k + 1}"))
            else:
                amt = numbered_amount()
                m, ct, app = instore_method(amt)
                day.append(make_txn(o["ts"], amt, m, ct, app, instore_customer(), o["order_id"]))
        for o in ondc_by_day.get(d, []):
            if o["tag"] == "CB9981":
                m, ct, app = "card", "credit", "Card (ONDC checkout)"
            else:
                m = pick({"UPI": 70, "credit": 20, "debit": 10})
                ct = None if m == "UPI" else m
                m = "UPI" if m == "UPI" else "card"
                app = pick(UPI_APPS) if m == "UPI" else "Card (ONDC checkout)"
            day.append(make_txn(o["ts"], o["amount"], m, ct, app, o["customer_id"], o["order_id"], channel="ONDC",
                                tag="ORDER_9981" if o["tag"] == "CB9981" else None))
        if d == END:
            day.append(make_txn(ts(d, 11, 3, 14), 1250, "UPI", None, "GPay", "C088", None, utr=UTR_SUCCESS,
                                tag="UTR_SUCCESS"))
            day.append(make_txn(ts(d, 18, 15, 40), 2400, "UPI", None, "PhonePe", "C095", None, status="PENDING",
                                utr=UTR_PENDING, tag="UTR_PENDING"))
        remaining = target[d] - sum(t["amount"] for t in day if t["status"] == "SUCCESS")
        assert remaining > 0.25 * target[d], (d, remaining, target[d])
        bigs = sum(1 for t in day if t["amount"] >= BIG_MIN)
        big_allow = max(1, int(target[d] / 7000))  # big appliances scale with footfall, not randomly
        while remaining > 0:
            a = instore_amount()
            if a >= BIG_MIN:
                if bigs >= big_allow or a > 0.4 * target[d]:
                    a = rng.randint(SMALL_MAX + 1, BIG_MIN - 1) if rng.random() < 0.5 else small_amount()
                else:
                    bigs += 1
            if a >= remaining or remaining - a < 30:
                # close the day with an ordinary bill, never one giant leftover
                a = remaining if remaining <= 2 * SMALL_MAX else min(small_amount(), remaining - 30)
            m, ct, app = instore_method(a)
            if d == END and m == "wallet" and a > 2000:  # keep the 18 Nov wallet story to order #4490 only
                m, ct, app = "UPI", None, pick(UPI_APPS)
            day.append(make_txn(random_time(d), a, m, ct, app, instore_customer(), None))
            remaining -= a
    # failed UPI attempts (customer retried / bank declined): never counted in gross
    for _ in range(max(1, round(len(day) * 0.012))):
        a = small_amount()
        day.append(make_txn(random_time(d), a, "UPI", None, pick(UPI_APPS), instore_customer(), None, status="FAILED"))
    day.sort(key=lambda t: t["timestamp"])
    for seq, t in enumerate(day, 1):
        t["txn_id"] = f"PTM{d:%y%m%d}{seq:05d}"
        t["mdr_amount"] = mdr_for(t["method"], t["card_type"], t["amount"]) if t["status"] == "SUCCESS" else 0.0
        if t["method"] == "card":
            t["mdr_rate"] = MDR_RATES["credit_card"] if t["card_type"] == "credit" else 0.0
        elif t["method"] == "postpaid":
            t["mdr_rate"] = MDR_RATES["postpaid"]
        elif t["method"] == "wallet":
            t["mdr_rate"] = MDR_RATES["wallet_above_2k"] if t["amount"] > 2000 else 0.0
        else:
            t["mdr_rate"] = 0.0
        if t["status"] != "SUCCESS":
            t["mdr_rate"] = 0.0
        if t["order_id"] is None:
            t["order_id"] = f"BILL-{d:%y%m%d}-{seq:04d}"  # Vyapar POS bill number
        t["settlement_batch_id"] = f"STL-{d + timedelta(days=1):%Y%m%d}" if t["status"] == "SUCCESS" else None
    txns.extend(day)

TX = {t["txn_id"]: t for t in txns}
tx_by_tag = {t["tag"]: t for t in txns if t["tag"]}
for c in customers:
    seen = [t["timestamp"] for t in txns if t["customer_id"] == c["customer_id"]]
    c["first_seen"] = min(seen).date().isoformat() if seen and c["customer_id"] != "WALKIN" else None

# ============================================================================ refunds
refunds: list[dict] = []
t4412, t4490 = tx_by_tag["ORDER_4412"], tx_by_tag["ORDER_4490"]
refunds.append({"refund_id": "RFD-4412", "order_id": "4412", "txn_id": t4412["txn_id"], "customer_id": "C077",
                "amount": 1500, "reason": "Philips electric kettle (bought 10 Oct as a Diwali gift) stopped heating after first use; no replacement stock, so refunded",
                "requested_at": ts(date(2026, 11, 16), 10, 5), "processed_at": ts(BULK_DAY, 12, 30),
                "status": "PROCESSED", "deducted_in_batch": "STL-20261118"})
refunds.append({"refund_id": "RFD-4490", "order_id": "4490", "txn_id": t4490["txn_id"], "customer_id": "C120",
                "amount": 3500, "reason": "Mixer grinder returned unopened: customer ordered the wrong model",
                "requested_at": ts(DEMO_DAY, 11, 20), "processed_at": None, "status": "REQUESTED",
                "deducted_in_batch": "STL-20261120 (projected)"})
pool = [t for t in txns if t["status"] == "SUCCESS" and t["channel"] == "in-store" and t["amount"] >= 150
        and t["tag"] is None and t["timestamp"].date() < date(2026, 11, 14)]
reasons = ["Charger not compatible with phone", "Wrong item billed", "LED bulb dead on arrival", "Earphones defective (one side silent)",
           "Customer billed twice at counter", "Item out of stock after billing"]
for t in rng.sample(pool, 14):
    pd_ = t["timestamp"].date() + timedelta(days=rng.randint(0, 2))
    if pd_ in (BULK_DAY,) or pd_ > END:
        pd_ = t["timestamp"].date()
    amt = max(20, min(t["amount"], int(t["amount"] * rng.uniform(0.4, 1.0) / 10) * 10))
    refunds.append({"refund_id": f"RFD-{t['txn_id'][-9:]}", "order_id": t["order_id"], "txn_id": t["txn_id"],
                    "customer_id": t["customer_id"], "amount": amt, "reason": rng.choice(reasons),
                    "requested_at": t["timestamp"] + timedelta(hours=rng.randint(1, 20)),
                    "processed_at": datetime.combine(pd_, datetime.min.time()) + timedelta(hours=17),
                    "status": "PROCESSED", "deducted_in_batch": f"STL-{pd_ + timedelta(days=1):%Y%m%d}"})
    refunds[-1]["requested_at"] = min(refunds[-1]["requested_at"], refunds[-1]["processed_at"] - timedelta(hours=1))

# ============================================================================ Shiprocket / ONDC fulfilment
COURIERS = ["Delhivery", "Xpressbees", "Ekart", "Shadowfax", "Blue Dart"]
ondc_tx = {t["order_id"]: t for t in txns if t["channel"] == "ONDC"}
lost_order = next(o for o in ONDC if o["ts"].date().month == 8 and o["tag"] == "RANDOM")
won_order = next(o for o in ONDC if o["ts"].date().month == 10 and o["ts"].day > 15 and o["tag"] == "RANDOM")
rto_orders = rng.sample([o for o in ONDC if o["tag"] == "RANDOM" and o not in (lost_order, won_order)
                         and o["ts"].date() < date(2026, 11, 1)], 3)
shipments = []
for o in ONDC:
    shipped = o["ts"] + timedelta(hours=rng.randint(4, 8))
    rec = {"order_id": o["order_id"], "ondc_order_id": f"ONDC-{o['ts']:%y%m%d}-{o['order_id']}",
           "buyer_app": pick({"Paytm (ONDC)": 55, "Other ONDC buyer app": 45}), "customer_id": o["customer_id"],
           "ship_to": CUST[o["customer_id"]]["locality"], "items": o["items"], "amount": o["amount"],
           "payment_txn_id": ondc_tx[o["order_id"]]["txn_id"], "ordered_at": o["ts"].isoformat(),
           "courier": rng.choice(COURIERS), "awb": f"AWB{rng.randrange(10**10):010d}",
           "shipped_at": shipped.isoformat(), "status": "DELIVERED", "pod": None}
    delivered = shipped + timedelta(days=rng.randint(1, 3), hours=rng.randint(0, 6))
    if o["tag"] == "CB9981":
        rec.update({"courier": "Demo Express Logistics", "awb": "DEX7781203345", "ship_to": "B-14, Lajpat Nagar, New Delhi 110024",
                    "shipped_at": ts(date(2026, 11, 14), 16, 0).isoformat()})
        rec["pod"] = {"delivered_at": ts(date(2026, 11, 16), 18, 42).isoformat(), "recipient": "Rohit Verma",
                      "otp_verified": True, "signature": True, "photo_on_delivery": False,
                      "document": "services/sarvam_service/app/samples/pod_9981.png",
                      "note": "Same values as the Sarvam sample PoD read by /doc-extract (use_sample_connector=true)"}
    elif o is lost_order:
        rec["status"], rec["pod"] = "LOST_IN_TRANSIT", None
    elif o in rto_orders:
        rec["status"], rec["pod"] = "RTO_DELIVERED", None
        rec["rto_reason"] = "Customer not reachable (3 attempts)"
    elif delivered > SNAPSHOT:
        rec["status"], rec["pod"] = "IN_TRANSIT", None
    else:
        otp = rng.random() < 0.85
        rec["pod"] = {"delivered_at": delivered.isoformat(), "recipient": CUST[o["customer_id"]]["name"],
                      "otp_verified": otp, "signature": (not otp) or rng.random() < 0.5,
                      "photo_on_delivery": rng.random() < 0.6, "document": None}
    shipments.append(rec)
SHIP = {s["order_id"]: s for s in shipments}

for o in rto_orders:  # prepaid RTO orders are refunded in full
    t = ondc_tx[o["order_id"]]
    pd_ = (datetime.fromisoformat(SHIP[o["order_id"]]["shipped_at"]) + timedelta(days=6)).date()
    if pd_ == BULK_DAY:
        pd_ += timedelta(days=1)
    refunds.append({"refund_id": f"RFD-{o['order_id']}", "order_id": o["order_id"], "txn_id": t["txn_id"],
                    "customer_id": o["customer_id"], "amount": o["amount"], "reason": "ONDC order returned to origin (RTO)",
                    "requested_at": datetime.combine(pd_, datetime.min.time()) + timedelta(hours=10),
                    "processed_at": datetime.combine(pd_, datetime.min.time()) + timedelta(hours=16),
                    "status": "PROCESSED", "deducted_in_batch": f"STL-{pd_ + timedelta(days=1):%Y%m%d}"})

# ============================================================================ chargebacks
t9981 = tx_by_tag["ORDER_9981"]
chargebacks = [
    {"chargeback_id": "CB-0001", "txn_id": ondc_tx[lost_order["order_id"]]["txn_id"], "order_id": lost_order["order_id"],
     "customer_id": lost_order["customer_id"], "amount": lost_order["amount"], "reason_code": "ITEM_NOT_RECEIVED",
     "raised_at": lost_order["ts"] + timedelta(days=6), "respond_by": lost_order["ts"] + timedelta(days=8),
     "status": "LOST", "resolved_at": lost_order["ts"] + timedelta(days=9), "pod_awb": SHIP[lost_order["order_id"]]["awb"],
     "evidence": "None: parcel lost by courier", "contract_ref": None},
    {"chargeback_id": "CB-0002", "txn_id": ondc_tx[won_order["order_id"]]["txn_id"], "order_id": won_order["order_id"],
     "customer_id": won_order["customer_id"], "amount": won_order["amount"], "reason_code": "ITEM_NOT_RECEIVED",
     "raised_at": won_order["ts"] + timedelta(days=5), "respond_by": won_order["ts"] + timedelta(days=7),
     "status": "WON", "resolved_at": won_order["ts"] + timedelta(days=7), "pod_awb": SHIP[won_order["order_id"]]["awb"],
     "evidence": "OTP-verified PoD from Shiprocket", "contract_ref": None},
    {"chargeback_id": "CB-9981", "txn_id": t9981["txn_id"], "order_id": "9981", "customer_id": "C042", "amount": 800,
     "reason_code": "ITEM_NOT_RECEIVED", "raised_at": ts(BULK_DAY, 14, 5), "respond_by": ts(DEMO_DAY, 14, 5),
     "status": "HELD", "resolved_at": None, "pod_awb": "DEX7781203345",
     "evidence": "Signed, OTP-verified PoD available in SHIPROCKET_SYNC (not yet submitted)",
     "contract_ref": "TXNID #9981 / ORDER #9981"},
]
for cb in chargebacks:
    for key in ("raised_at", "resolved_at"):
        if cb[key] is not None and cb[key].date() == BULK_DAY and cb["chargeback_id"] != "CB-9981":
            cb[key] += timedelta(days=1)
    cb["held_in_batch"] = f"STL-{cb['raised_at'].date() + timedelta(days=1):%Y%m%d}"
    cb["released_in_batch"] = (f"STL-{cb['resolved_at'].date() + timedelta(days=1):%Y%m%d}"
                               if cb["status"] == "WON" else None)

# ============================================================================ settlements (T+1)
by_day = defaultdict(list)
for t in txns:
    if t["status"] == "SUCCESS":
        by_day[t["timestamp"].date()].append(t)
settlements = []
for d in DAYS:
    sd = d + timedelta(days=1)
    gross = sum(t["amount"] for t in by_day[d])
    mdr = money(sum(t["mdr_amount"] for t in by_day[d]))
    gst = money(mdr * 0.18)
    rf = sum(r["amount"] for r in refunds if r["processed_at"] and r["processed_at"].date() == d)
    rental = SOUNDBOX_RENTAL if sd.day == RENTAL_DAY else 0
    hold = sum(c["amount"] for c in chargebacks if c["raised_at"].date() == d)
    release = sum(c["amount"] for c in chargebacks if c["status"] == "WON" and c["resolved_at"].date() == d)
    net = gross - mdr - gst - rf - rental - hold + release
    settlements.append({"batch_id": f"STL-{sd:%Y%m%d}", "settlement_date": sd.isoformat(), "txn_date": d.isoformat(),
                        "gross": gross, "mdr": mdr, "gst_on_mdr": gst, "refunds": rf, "soundbox_rental": rental,
                        "chargeback_hold": hold, "chargeback_release": release, "net_credit": net,
                        "variance": gross - net, "credited_at": f"{sd.isoformat()}T08:00:00",
                        "payout_ref": f"PYTMSTL{sd:%y%m%d}{rng.randrange(10**6):06d}", "status": "SUCCESS"})
STL = {s["batch_id"]: s for s in settlements}

# ============================================================================ loan + EDI
EDI_START, LOAN_EDIS, SANCTIONED, FEE = date(2026, 6, 1), 254, 115000, 1150  # 1% processing fee
edi_rows, collected = [], 0
recovery = {date(2026, 7, 14): ("REMINDER_ONLY", "Paid next day via re-presentment"),
            date(2026, 7, 28): ("UPI_LINK", "Paid via 1-tap UPI link in 1h 50m"),
            date(2026, 8, 11): ("UPI_LINK", "Paid via 1-tap UPI link in 2h 10m"),
            date(2026, 8, 19): ("UPI_LINK", "Paid via 1-tap UPI link in 1h 35m"),
            date(2026, 9, 22): ("AUTO_RETRY", "Auto re-presented next day after bank outage"),
            date(2026, 10, 13): ("UPI_LINK", "Paid via 1-tap UPI link in 3h 05m")}
d = EDI_START
while d <= END:
    if d in EDI_BOUNCES:
        code, reason, cause = EDI_BOUNCES[d]
        rec = recovery.get(d)
        if rec:
            collected += 500
        edi_rows.append({"edi_date": d.isoformat(), "amount": 500, "channel": "eNACH", "status": "BOUNCED",
                         "bounce_code": code, "bounce_reason": reason, "context": cause,
                         "recovery": rec[0] if rec else "PENDING", "recovery_note": rec[1] if rec else "Not yet recovered",
                         "cumulative_collected": collected})
    else:
        collected += 500
        edi_rows.append({"edi_date": d.isoformat(), "amount": 500, "channel": "eNACH", "status": "SUCCESS",
                         "bounce_code": None, "bounce_reason": None, "context": None, "recovery": None,
                         "recovery_note": None, "cumulative_collected": collected})
    d += timedelta(days=1)
total_repayable = LOAN_EDIS * 500
for r in edi_rows:
    r["balance_after"] = total_repayable - r["cumulative_collected"]


def apr_from_edis(net_disbursed: float, edi: float, n: int) -> float:
    lo, hi = 0.0, 0.01
    for _ in range(200):
        mid = (lo + hi) / 2
        pv = sum(edi / (1 + mid) ** t for t in range(1, n + 1))
        lo, hi = (mid, hi) if pv > net_disbursed else (lo, mid)
    return round(((lo + hi) / 2) * 365 * 100, 2)


loan = {
    "loan_id": "CLX-ML-26-008821", "mid": MID, "lender": "Clix Capital", "lender_type": "NBFC (lending partner)",
    "distributor": "Paytm (Lending Service Provider)", "product": "Merchant cash loan with daily EDI",
    "sanctioned_amount": SANCTIONED, "processing_fee": FEE, "net_disbursed": SANCTIONED - FEE,
    "disbursed_on": "2026-05-31", "daily_edi": 500, "total_edis": LOAN_EDIS, "total_repayable": total_repayable,
    "edis_due_so_far": len(edi_rows), "collected_so_far": collected,
    "loan_balance": total_repayable - collected, "first_attempt_success_rate": None,
    "collection_method": "Daily eNACH auto-debit on the merchant's bank account at 07:00 (not netted from settlements)",
    "mandate": {"type": "eNACH", "umrn": "UMRN-DEMO-0000008821", "bank_account_masked": "XXXXXX4821",
                "status": "ACTIVE (last presentment BOUNCED on 2026-11-17)"},
    "kfs": {
        "apr_percent": apr_from_edis(SANCTIONED - FEE, 500, LOAN_EDIS),
        "cooling_off_days": 3, "foreclosure_charges": "Nil after 90 days",
        "bounce_charges": "Nil (waived for first-attempt friction cases under hardship policy)",
        "clauses": {
            "4.1": "EDI of ₹500 is collected daily by eNACH; a bounced EDI may be paid the same day via a UPI link without penalty.",
            "4.2": "EDI holiday: on documented cash-flow stress the borrower may pause EDIs for up to 2 consecutive days, "
                   "with explicit consent, at most once per 30 days. Paused EDIs move to the end of the tenure; no penalty interest.",
            "4.3": "Hardship assessment uses settlement history shared with consent via the RBI Account Aggregator framework.",
        },
    },
    "kfs_edi_holiday_eligible": True, "edi_holiday_used_last_30_days": False,
}
loan["first_attempt_success_rate"] = round(sum(r["status"] == "SUCCESS" for r in edi_rows) / len(edi_rows), 4)

# ============================================================================ suppliers, khata, inventory
payables = []
supplier_cycles = [("Gaffar Market accessories wholesaler", 4, (3000, 7000)), ("Havells (via Gupta Electricals)", 10, (8000, 20000)),
                   ("Signify/Philips Lighting (via Gupta Electricals)", 14, (5000, 12000)),
                   ("Crompton Greaves Consumer (via Jain Distributors)", 14, (10000, 25000)),
                   ("Bajaj Electricals (via Jain Distributors)", 14, (8000, 18000)),
                   ("Panasonic Anchor (via Gupta Electricals)", 7, (3000, 8000)), ("Polycab Wires (via Gupta Electricals)", 14, (6000, 15000)),
                   ("boAt distributor (Imagine Marketing)", 10, (4000, 9000))]
TOMORROW_SUPPLIER = "Gaffar Market accessories wholesaler"
pid = 1
for sup, every, (lo, hi) in supplier_cycles:
    d = START + timedelta(days=rng.randrange(every))
    while d <= END:
        amt = rng.randrange(lo, hi, 50)
        if date(2026, 10, 24) <= d <= date(2026, 11, 6):
            amt = int(amt * 1.6 / 50) * 50  # festive stocking
        due = d + timedelta(days=2 if sup == TOMORROW_SUPPLIER else 7)
        if sup == TOMORROW_SUPPLIER and d == END:
            d += timedelta(days=every)
            continue
        payables.append({"payable_id": f"PAY-{pid:04d}", "supplier": sup, "invoice_no": f"INV-{d:%y%m%d}-{pid:03d}",
                         "amount": amt, "invoice_date": d.isoformat(), "due_date": due.isoformat(),
                         "status": "PAID" if due <= DEMO_DAY else "DUE", "paid_on": due.isoformat() if due <= DEMO_DAY else None,
                         "source": "VYAPAR_POS_SYNC"})
        pid += 1
        d += timedelta(days=every)
payables.append({"payable_id": f"PAY-{pid:04d}", "supplier": "Crompton + Havells (Dhanteras/Diwali stock)",
                 "invoice_no": "INV-261012-DIWALI", "amount": 38000, "invoice_date": "2026-10-10", "due_date": "2026-10-12",
                 "status": "PAID", "paid_on": "2026-10-12", "source": "VYAPAR_POS_SYNC"})
pid += 1
payables.append({"payable_id": "PAY-TOMORROW", "supplier": TOMORROW_SUPPLIER,
                 "invoice_no": "INV-261118-GAFFAR", "amount": 4500, "invoice_date": "2026-11-18", "due_date": "2026-11-20",
                 "status": "DUE", "paid_on": None, "source": "VYAPAR_POS_SYNC"})
for p in payables:  # anything else falling due on/after demo day stays DUE but must not be "tomorrow"
    if p["payable_id"] != "PAY-TOMORROW" and p["due_date"] == "2026-11-20":
        p["due_date"] = "2026-11-23"

khata, eid = [], 1
for cid in KHATA_CUSTOMERS:
    bal = 0
    their = [t for t in txns if t["customer_id"] == cid and t["status"] == "SUCCESS" and t["method"] == "UPI"]
    credit_days = sorted(rng.sample(DAYS[:-5], 14))
    events = [("credit", datetime.combine(d, datetime.min.time()) + timedelta(hours=rng.randint(8, 20))) for d in credit_days]
    events += [("pay", t["timestamp"], t) for t in their]
    events.sort(key=lambda e: e[1])
    for e in events:
        if e[0] == "credit":
            amt = rng.randrange(500, 4000, 10)
            bal += amt
            khata.append({"entry_id": f"KH-{eid:04d}", "customer_id": cid, "timestamp": e[1], "type": "credit_given",
                          "amount": amt, "txn_id": None, "balance_after": bal, "note": "Wires/switches for a site job, on khata"})
            eid += 1
        elif bal >= e[2]["amount"] and rng.random() < 0.45:
            bal -= e[2]["amount"]
            khata.append({"entry_id": f"KH-{eid:04d}", "customer_id": cid, "timestamp": e[1], "type": "payment_received",
                          "amount": e[2]["amount"], "txn_id": e[2]["txn_id"], "balance_after": bal,
                          "note": "Paid back via UPI"})
            eid += 1

weekend_heavy = {"MOB-MI-CHG33": 10, "MOB-BOT-BH100": 9, "LGT-PHI-10W2": 8, "ELC-HAV-EXT41": 7, "MOB-POR-CAB1M": 7,
                 "MOB-BOT-AD141": 6, "FAN-CRO-HS12": 6, "MOB-GEN-TGL": 5, "BAT-DUR-AA4": 4, "KIT-PRE-KTL15": 3}
inventory = []
for s in SKUS:
    sku, name, brand, cat, unit, cost, sell, mrp, sup, rop = s
    stock = max(0, int(rop * rng.uniform(0.6, 3.0)))
    inventory.append({"sku": sku, "name": name, "brand": brand, "category": cat, "unit": unit, "cost_price": cost,
                      "selling_price": sell, "mrp": mrp, "margin_pct": round((sell - cost) / sell * 100, 1),
                      "stock_qty": stock, "reorder_point": rop, "below_reorder": stock < rop, "supplier": sup,
                      "weekend_stockout_count_6m": weekend_heavy.get(sku, rng.randint(0, 2))})

# ============================================================================ device logs
device_logs = []
t = datetime(2026, 11, 1, 0, 0)
while t <= datetime(2026, 11, 18, 23, 0):
    day_i = (t.date() - date(2026, 11, 1)).days
    health = 45 if day_i < 9 else max(18, 41 - (day_i - 9) * 3)  # 41% on 10 Nov -> 18% by 18 Nov
    open_hours = 7 <= t.hour <= 21
    battery = max(3, min(100, int(100 - (t.hour - 7) * (100 - health) / 14))) if open_hours else 100
    faulty = t.date() >= date(2026, 11, 15)
    hb_ok = not (faulty and open_hours and rng.random() < 0.35)
    net = "4G" if hb_ok else rng.choice(["2G", "offline"])
    fails = rng.randint(1, 6) if faulty and open_hours else (1 if rng.random() < 0.02 else 0)
    event = None
    if not hb_ok:
        event = "HEARTBEAT_MISSED"
    elif fails >= 3:
        event = "SPEAKER_ANNOUNCE_FAILED"
    elif open_hours and battery < 15:
        event = "LOW_BATTERY"
    device_logs.append({"ts": t, "device_id": "SB-8821-01", "device": "Paytm Card Soundbox", "battery_pct": battery,
                        "battery_health_pct": health, "network": net,
                        "signal_dbm": -75 - rng.randint(0, 10) if hb_ok else -105 - rng.randint(0, 10),
                        "heartbeat_ok": hb_ok, "announce_failures": fails, "event": event})
    t += timedelta(hours=1)

# ============================================================================ support history + strategy memory
support = [
    ("TKT-PAYTM-1041", "2026-06-14 10:20", "ESCALATE_HUMAN", "Soundbox not announcing payments", "app_chat",
     "Remote restart + volume reset", "2026-06-14 11:05", "RESOLVED", 5),
    ("TKT-PAYTM-1107", "2026-07-14 09:10", "MANDATE_TROUBLESHOOT", "EDI bounced after heavy rain", "voice",
     "Reminder sent; re-presented next day", "2026-07-15 07:05", "RESOLVED", 3),
    ("TKT-PAYTM-1119", "2026-07-28 08:40", "MANDATE_TROUBLESHOOT", "EDI bounced after heavy rain", "voice",
     "1-tap UPI link sent", "2026-07-28 10:30", "RESOLVED", 5),
    ("TKT-PAYTM-1162", "2026-08-21 12:00", "SETTLEMENT_RECONCILE", "Why was MDR deducted?", "app_chat",
     "Explained card/wallet MDR + GST ITC", "2026-08-21 12:20", "RESOLVED", 4),
    ("TKT-PAYTM-1178", f"{chargebacks[0]['raised_at']:%Y-%m-%d %H:%M}", "CHARGEBACK_RESOLVE",
     f"Chargeback on ONDC order #{chargebacks[0]['order_id']}", "app_chat",
     "No PoD (parcel lost by courier); chargeback accepted", f"{chargebacks[0]['resolved_at']:%Y-%m-%d %H:%M}", "LOST", 2),
    ("TKT-PAYTM-1204", "2026-09-22 09:30", "MANDATE_TROUBLESHOOT", "EDI bounced: bank outage", "voice",
     "Auto re-presented next day", "2026-09-23 07:05", "RESOLVED", 4),
    ("TKT-PAYTM-1236", "2026-10-03 19:15", "UTR_VERIFY", "Customer showed payment screenshot, no Soundbox alert",
     "voice", "UTR not in NPCI log; merchant asked customer to pay again", "2026-10-03 19:18", "FRAUD_PREVENTED", 5),
    ("TKT-PAYTM-1251", "2026-10-13 08:15", "MANDATE_TROUBLESHOOT", "EDI bounced after Diwali stock payment", "voice",
     "1-tap UPI link sent", "2026-10-13 11:20", "RESOLVED", 5),
    ("TKT-PAYTM-1263", f"{chargebacks[1]['raised_at']:%Y-%m-%d %H:%M}", "CHARGEBACK_RESOLVE",
     f"Chargeback on ONDC order #{chargebacks[1]['order_id']}", "app_chat",
     "Submitted OTP-verified Shiprocket PoD; hold released", f"{chargebacks[1]['resolved_at']:%Y-%m-%d %H:%M}", "WON", 5),
    ("TKT-PAYTM-1290", "2026-11-16 21:40", "ESCALATE_HUMAN", "Soundbox battery drains by evening, misses announcements",
     "app_chat", "Advised full charge overnight; issue persists", None, "OPEN", None),
]
support_history = [dict(zip(["ticket_id", "opened_at", "intent", "summary", "channel", "resolution", "resolved_at",
                             "outcome", "csat"], s)) for s in support]

strategy_memory = [
    {"memory_id": "SM-001", "date": "2026-07-14", "intent": "MANDATE_TROUBLESHOOT",
     "situation": "eNACH bounce after 2 heavy-rain days (sales -35%)",
     "options_considered": ["A: reminder", "B: 1-tap UPI link", "C: escalate to collections"], "chosen": "A",
     "verified_outcome": "Paid next day on re-presentment", "time_to_outcome": "24h", "success": True},
    {"memory_id": "SM-002", "date": "2026-07-28", "intent": "MANDATE_TROUBLESHOOT",
     "situation": "eNACH bounce after heavy rain", "options_considered": ["A: reminder", "B: 1-tap UPI link"],
     "chosen": "B", "verified_outcome": "UPI link after mandate bounce -> paid within 2h", "time_to_outcome": "1h 50m",
     "success": True},
    {"memory_id": "SM-003", "date": "2026-08-11", "intent": "MANDATE_TROUBLESHOOT", "situation": "eNACH bounce after heavy rain",
     "options_considered": ["B: 1-tap UPI link"], "chosen": "B", "verified_outcome": "Paid within 2h 10m",
     "time_to_outcome": "2h 10m", "success": True},
    {"memory_id": "SM-004", "date": "2026-08-19", "intent": "MANDATE_TROUBLESHOOT", "situation": "eNACH bounce after heavy rain",
     "options_considered": ["B: 1-tap UPI link"], "chosen": "B", "verified_outcome": "Paid within 1h 35m",
     "time_to_outcome": "1h 35m", "success": True},
    {"memory_id": "SM-005", "date": f"{chargebacks[0]['resolved_at']:%Y-%m-%d}", "intent": "CHARGEBACK_RESOLVE",
     "situation": "Chargeback, no PoD available (parcel lost)", "options_considered": ["A: accept", "C: escalate"],
     "chosen": "A", "verified_outcome": f"Lost ₹{chargebacks[0]['amount']}; lesson: insist on OTP delivery",
     "time_to_outcome": "3 days", "success": False},
    {"memory_id": "SM-006", "date": "2026-10-03", "intent": "UTR_VERIFY", "situation": "Screenshot shown, no Soundbox alert",
     "options_considered": ["A: trust screenshot", "B: verify UTR with NPCI log"], "chosen": "B",
     "verified_outcome": "UTR not found; goods not handed over; fraud prevented", "time_to_outcome": "3 min", "success": True},
    {"memory_id": "SM-007", "date": "2026-10-13", "intent": "MANDATE_TROUBLESHOOT",
     "situation": "eNACH bounce after ₹38,000 Diwali stock payment (cash-flow timing, not sales)",
     "options_considered": ["A: reminder", "B: 1-tap UPI link"], "chosen": "B", "verified_outcome": "Paid within 3h 05m",
     "time_to_outcome": "3h 05m", "success": True},
    {"memory_id": "SM-008", "date": f"{chargebacks[1]['resolved_at']:%Y-%m-%d}", "intent": "CHARGEBACK_RESOLVE",
     "situation": "Chargeback with OTP-verified PoD in Shiprocket", "options_considered": ["A: accept", "B: submit PoD"],
     "chosen": "B", "verified_outcome": f"Won; ₹{chargebacks[1]['amount']} hold released", "time_to_outcome": "2 days",
     "success": True},
]
strategy = {"mid": MID, "learned_policies": [
    {"intent": "MANDATE_TROUBLESHOOT", "policy": "For first-attempt bounces with >=95% EDI history, send a 1-tap UPI link "
     "(4/4 paid within ~3h) rather than a reminder (1/1 paid only after 24h).", "evidence": ["SM-002", "SM-003", "SM-004", "SM-007", "SM-001"]},
    {"intent": "CHARGEBACK_RESOLVE", "policy": "Submit OTP-verified Shiprocket PoD immediately; chargebacks without PoD are lost.",
     "evidence": ["SM-008", "SM-005"]},
    {"intent": "UTR_VERIFY", "policy": "Never hand over goods on a screenshot alone; verify the UTR against the NPCI log.",
     "evidence": ["SM-006"]}], "memories": strategy_memory}

# ============================================================================ UTR ledger
utr_rows = []
for t in txns:
    if t["utr"]:
        flag = None
        if t["tag"] and t["tag"].startswith("DUPLICATE_PAYMENT"):
            flag = "DUPLICATE"
        elif t["status"] == "PENDING":
            flag = "PENDING_AUTO_REVERSAL_T+1"
        utr_rows.append({"utr": t["utr"], "txn_id": t["txn_id"], "amount": t["amount"], "payer_app": t["payer_app"],
                         "payer_vpa_masked": f"{CUST[t['customer_id']]['name'].split()[0].lower()}{rng.randrange(100)}@xx"
                         if t["customer_id"] != "WALKIN" else "xxxxxx@xx", "npci_status": t["status"],
                         "timestamp": t["timestamp"], "order_id": t["order_id"], "customer_id": t["customer_id"], "flag": flag})

# ============================================================================ daily summary
daily = []
for d in DAYS:
    ok = by_day[d]
    gross = sum(t["amount"] for t in ok)
    upi = sum(t["amount"] for t in ok if t["method"] == "UPI")
    note = None
    if d == BULK_DAY:
        note = "Market reopens + ₹55,000 PG fit-out order by Rao PG & Hostels (credit card); eNACH EDI bounced 07:00"
    elif d in CLOSURE_DAYS:
        note = "Local market closure (road-widening work): sales ~40% below normal"
    elif d in RAIN_DAYS:
        note = "Heavy rain: low footfall"
    elif d == DHANTERAS:
        note = "Dhanteras: appliance buying peak"
    elif d == DIWALI:
        note = "Diwali"
    daily.append({"date": d.isoformat(), "weekday": d.strftime("%A"), "gross": gross, "txn_count": len(ok),
                  "avg_ticket": round(gross / len(ok), 1), "upi_share_by_value": round(upi / gross, 3),
                  "is_weekend": is_weekend(d), "is_festival": date(2026, 10, 31) <= d <= DIWALI,
                  "rain_dip": d in RAIN_DAYS, "closure_dip": d in CLOSURE_DAYS, "bulk_order_day": d == BULK_DAY,
                  "note": note})
DAILY = {r["date"]: r for r in daily}

# ============================================================================ merchant profile
top_customers = sorted(((sum(t["amount"] for t in txns if t["customer_id"] == c and t["status"] == "SUCCESS"), c)
                        for c in INSTORE_REGULARS), reverse=True)[:10]
profile = {
    "mid": MID, "name": NAME, "owner": "Rajesh Sharma",
    "category": "Consumer electronics, appliances & electricals", "mcc": "5732", "kyc_tier": "Full KYC (Video KYC) + GST registered",
    "gstin": "06ABCDE1234F1Z5 (dummy)", "pan_masked": "ABCDE####F (dummy)",
    "address": {"line1": "Shop 12, Sector 14 Market", "city": "Gurugram", "state": "Haryana", "pincode": "122001"},
    "store_hours": "07:00-22:00, peaks 07-10 and 18-21", "onboarded_on": "2024-03-04",
    "settlement": {"cycle": "T+1 (all instruments, daily batch credited ~08:00)", "bank": "XXXXXX4821 (masked)",
                   "ifsc": "DEMO0000821", "mdr_rates": {"credit_card": "2%", "paytm_postpaid": "2%",
                                                        "wallet_on_upi_above_2000": "1.1%", "upi_p2m": "0%", "rupay_debit": "0%"}},
    "devices": [{"device_id": "SB-8821-01", "type": "Paytm Card Soundbox", "rental_inr_per_month": 149,
                 "rental_billing_day": 18, "status": "DEGRADED (see device_logs.csv)"},
                {"device_id": "QR-8821-01", "type": "Paytm QR standee", "status": "ACTIVE"}],
    "connectors": [
        {"name": "SHIPROCKET_SYNC", "status": "ACTIVE", "dpdp_consent": "GRANTED", "granted_at": "2026-06-02",
         "holds": "ONDC shipments + PoD (incl. signed PoD for ORDER #9981)"},
        {"name": "VYAPAR_POS_SYNC", "status": "ACTIVE", "dpdp_consent": "GRANTED", "granted_at": "2026-05-20",
         "holds": "POS bills, inventory, supplier payables (₹4,500 due tomorrow)"},
        {"name": "RBI_ACCOUNT_AGGREGATOR", "status": "ACTIVE", "dpdp_consent": "GRANTED", "granted_at": "2026-05-28",
         "holds": "Bank statement view used for loan underwriting and hardship checks"},
    ],
    "historical_memory": dict(HISTORICAL_MEMORY),
    "recent_customers": [{"customer_id": c, "name": CUST[c]["name"], "six_month_spend": s} for s, c in top_customers],
    "as_of": SNAPSHOT.isoformat(),
}

breakdown = {
    "batch_id": "STL-20261118", "mid": MID, "settlement_date": "2026-11-18",
    "covers_transactions_of": "2026-11-17 (Tue) 07:00-22:00, T+1",
    "why_gross_is_high": "Market reopened after a 3-day closure and Rao PG & Hostels paid ₹55,000 by credit card to fit out "
                         "a new PG (14 ceiling fans, 20 LED panels, battens, wiring). The 6-month average is ₹32,000/day.",
    "gross": STL["STL-20261118"]["gross"],
    "by_rail": {
        "credit_card_and_postpaid": {"amount": 62600, "mdr_rate": "2%", "mdr": 1252},
        "wallet_on_upi_above_2000": {"amount": 18000, "mdr_rate": "1.1%", "mdr": 198},
        "upi_p2m": {"amount": 19400, "mdr_rate": "0%", "mdr": 0},
    },
    "deductions": [
        {"type": "MDR", "amount": 1450, "source": "card/postpaid 2% on ₹62,600 + wallet 1.1% on ₹18,000"},
        {"type": "GST_ON_MDR", "amount": 261, "source": "18% of ₹1,450; ITC-eligible (merchant is GST registered)"},
        {"type": "REFUND", "amount": 1500, "source": "RFD-4412 for ORDER #4412 (processed 2026-11-17)",
         "txn_id": t4412["txn_id"]},
        {"type": "SOUNDBOX_RENTAL", "amount": 149, "source": "Monthly rental for SB-8821-01 (billed on the 18th)"},
        {"type": "CHARGEBACK_HOLD", "amount": 800, "source": "CB-9981 on ORDER #9981 (raised 2026-11-17 14:05)",
         "status": "HELD", "txn_id": t9981["txn_id"]},
    ],
    "net_credit": STL["STL-20261118"]["net_credit"], "variance": STL["STL-20261118"]["variance"],
    "contributing_txn_ids": {"pg_fitout_bulk_order": tx_by_tag["PG_FITOUT_BULK_ORDER"]["txn_id"],
                             "mdr_bearing": [t["txn_id"] for t in by_day[BULK_DAY] if t["mdr_amount"] > 0]},
    "edi_note": "The ₹500 EDI is collected by eNACH from the bank account, not from this settlement.",
}

# ============================================================================ scenarios
dup = [t for t in txns if t["tag"] and t["tag"].startswith("DUPLICATE_PAYMENT")]
intraday_19 = [("07:12", 340, "UPI"), ("07:40", 1150, "UPI"), ("08:05", 560, "UPI"), ("08:31", 890, "UPI"),
               ("09:02", 420, "UPI"), ("09:48", 760, "UPI"), ("10:30", 580, "UPI")]
assert sum(a for _, a, _ in intraday_19) == 4700
monthly = defaultdict(int)
for r in daily:
    monthly[r["date"][:7]] += r["gross"]
we = [r["gross"] for r in daily if r["is_weekend"]]
wd = [r["gross"] for r in daily if not r["is_weekend"]]
scenarios = {"mid": MID, "demo_day": DEMO_DAY.isoformat(), "scenarios": [
    {"intent": "MANDATE_TROUBLESHOOT", "contract_v1_intent": "FEE_GST_LOAN",
     "trigger_hinglish": "Mera ₹500 ka loan EDI mandate fail ho gaya",
     "record_ids": {"edi_date": "2026-11-17", "loan_id": loan["loan_id"],
                    "dip_days": [d.isoformat() for d in sorted(CLOSURE_DAYS)], "strategy_memory": ["SM-002", "SM-007"]},
     "story": "Market closure cut sales ~40% for 3 days, so the 17 Nov eNACH bounced; sales recovered the same day and "
              "the EDI record is 96% on time: friction, not default.",
     "expected_root_cause": "TEMPORARY_FRICTION",
     "expected_intervention": "Option B: 1-tap UPI link for ₹500 (KFS 4.1, no penalty); KFS 4.2 pause available if needed",
     "expected_verified_outcome": "EDI for 2026-11-17 marked RECOVERED_VIA_UPI_LINK, no penalty, mandate stays ACTIVE"},
    {"intent": "SETTLEMENT_RECONCILE", "contract_v1_intent": "SETTLEMENT_RECONCILE",
     "trigger_hinglish": "Kal ka settlement ₹4,160 kam kyun aaya? Paisa kahan kata?",
     "record_ids": {"batch_id": "STL-20261118", "refund_id": "RFD-4412", "chargeback_id": "CB-9981",
                    "bulk_order_txn_id": tx_by_tag["PG_FITOUT_BULK_ORDER"]["txn_id"]},
     "story": "₹1,00,000 gross on 17 Nov (PG owner's card order) -> MDR ₹1,450 + GST ₹261 (ITC) + refund #4412 ₹1,500 + "
              "Soundbox ₹149 + hold #9981 ₹800 = ₹4,160; net ₹95,840.",
     "expected_root_cause": "VALID_DEDUCTIONS_PLUS_HOLD", "expected_intervention": "Itemised explanation + auto-log ₹261 GST ITC",
     "expected_verified_outcome": "Merchant sees itemised ₹4,160; ₹261 logged to ITC register; ₹800 linked to CB-9981"},
    {"intent": "CHARGEBACK_RESOLVE", "contract_v1_intent": "CHARGEBACK_RESOLVE",
     "trigger_hinglish": "Order 9981 pe chargeback aaya hai, ₹800 hold ho gaya",
     "record_ids": {"chargeback_id": "CB-9981", "order_id": "9981", "txn_id": t9981["txn_id"], "awb": "DEX7781203345",
                    "pod_document": "services/sarvam_service/app/samples/pod_9981.png", "connector": "SHIPROCKET_SYNC"},
     "story": "ONDC buyer claims non-delivery, but Shiprocket holds an OTP-verified, signed PoD (delivered 16 Nov to "
              "Rohit Verma); merchant signs off in one tap.",
     "expected_root_cause": "DISPUTE_WITH_EVIDENCE_AVAILABLE", "expected_intervention": "Submit Shiprocket PoD after 1-tap sign-off",
     "expected_verified_outcome": "CB-9981 HELD -> RELEASED; ₹800 added back in the next settlement"},
    {"intent": "UTR_VERIFY", "contract_v1_intent": "UTR_VERIFY",
     "trigger_hinglish": "Customer ne screenshot dikhaya, UTR 632184920555, paisa aaya kya?",
     "record_ids": {"genuine_utr": UTR_SUCCESS, "genuine_txn_id": tx_by_tag["UTR_SUCCESS"]["txn_id"],
                    "pending_utr": UTR_PENDING, "pending_txn_id": tx_by_tag["UTR_PENDING"]["txn_id"],
                    "fake_screenshot_utr": UTR_FAKE},
     "story": "…0111 is a settled GPay payment, …0999 is PhonePe PENDING (auto-reversal T+1), …0555 is not in the NPCI log.",
     "expected_root_cause": "NOT_FOUND_SUSPECTED_FAKE (for …0555)",
     "expected_intervention": "Tell merchant, neutrally, not to hand over goods until a payment shows on the Soundbox",
     "expected_verified_outcome": "Fraud blocked; no goods released against an unverified screenshot"},
    {"intent": "DUPLICATE_RECONCILE", "contract_v1_intent": "REFUND_MANAGE",
     "trigger_hinglish": "Sunita ji ne ek hi order ke liye do baar payment kar diya",
     "record_ids": {"order_id": DUP_ORDER, "customer_id": "C017", "txn_ids": [t["txn_id"] for t in dup],
                    "utrs": [t["utr"] for t in dup]},
     "story": "PhonePe charged ₹1,180 twice, 48 seconds apart, for one order; both UTRs map to the same order.",
     "expected_root_cause": "DUPLICATE_PAYMENT", "expected_intervention": "Auto-refund ₹1,180 (under ₹5,000 autonomous limit)",
     "expected_verified_outcome": "Refund for the second UTR PROCESSED; order reconciled to one payment"},
    {"intent": "GROWTH_ADVISORY", "contract_v1_intent": "FEE_GST_LOAN",
     "trigger_hinglish": "Mere pichle 6 mahine ke data se business badhane ka suggestion do",
     "record_ids": {"daily_avg": round(sum(r["gross"] for r in daily) / len(daily)),
                    "fri_sun_vs_mon_thu": round((sum(we) / len(we)) / (sum(wd) / len(wd)), 2),
                    "monthly_gross": dict(monthly),
                    "weekend_stockout_skus": sorted(weekend_heavy, key=weekend_heavy.get, reverse=True)[:5]},
     "story": "₹32,000/day average with a 2.3x Fri–Sun peak; chargers, earphones, LED bulbs and extension boards run out on weekends.",
     "expected_root_cause": "GROWTH_OPPORTUNITY",
     "expected_intervention": "Stock up by Thursday; optional KFS-transparent working-capital line sized to weekend demand",
     "expected_verified_outcome": "Advice delivered with cited numbers; no money moved without consent"},
    {"intent": "CASHFLOW_EDI_SWITCH", "contract_v1_intent": "FEE_GST_LOAN",
     "trigger_hinglish": "Refund ke baad kal payout bahut kam hai, supplier ko ₹4,500 dena hai",
     "record_ids": {"refund_id": "RFD-4490", "order_id": "4490", "payable_id": "PAY-TOMORROW", "loan_id": loan["loan_id"],
                    "kfs_clause": "4.2"},
     "cashflow_projection": {"as_of": "2026-11-19T11:30:00", "collections_so_far": 4700,
                             "intraday_txns": [{"time": a, "amount": b, "method": c} for a, b, c in intraday_19],
                             "refund_request": 3500, "projected_net_payout": 1200, "tomorrow_stock_due": 4500,
                             "shortfall": 3300},
     "story": "A ₹3,500 refund (#4490) leaves a ₹1,200 payout against ₹4,500 owed to the Gaffar Market accessories wholesaler on Friday for weekend stock.",
     "expected_root_cause": "CASHFLOW_SHORTFALL",
     "expected_intervention": "Pause Clix Capital EDI for 2 days under KFS clause 4.2 (with consent)",
     "expected_verified_outcome": "loan_edi_status PAUSED_2_DAYS, ₹1,000 freed, EDI resumes 2026-11-21"},
    {"intent": "ESCALATE_HUMAN", "contract_v1_intent": "ESCALATE_HUMAN",
     "trigger_hinglish": "Mera Soundbox kharab ho gaya, payment ki awaaz nahi aa rahi",
     "record_ids": {"device_id": "SB-8821-01", "log_window": "2026-11-10 to 2026-11-18", "open_ticket": "TKT-PAYTM-1290"},
     "story": "Battery health fell from 41% to 18%; heartbeats and announcements fail from 15 Nov.",
     "expected_root_cause": "HARDWARE_FAULT", "expected_intervention": "Priority L2 replacement ticket with diagnostics attached",
     "expected_verified_outcome": "TKT-PAYTM-xxxx created with logs; merchant not asked to repeat anything"},
]}

# ============================================================================ write files
OUT.mkdir(parents=True, exist_ok=True)


def write_csv(name: str, rows: list[dict], cols: list[str]) -> None:
    df = pd.DataFrame(rows)[cols]
    for c in df.columns:
        if df[c].map(lambda v: isinstance(v, datetime)).any():
            df[c] = df[c].map(lambda v: v.isoformat() if isinstance(v, datetime) else v)
    df.to_csv(OUT / name, index=False)


def write_json(name: str, obj) -> None:
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


TXN_COLS = ["txn_id", "timestamp", "amount", "method", "card_type", "payer_app", "utr", "status", "customer_id",
            "order_id", "channel", "mdr_rate", "mdr_amount", "settlement_batch_id", "tag"]
write_json("merchant_profile.json", profile)
write_csv("customers.csv", customers, ["customer_id", "name", "phone_masked", "locality", "segment", "first_seen",
                                       "on_khata", "preferred_app"])
write_csv("transactions.csv", txns, TXN_COLS)
write_csv("daily_sales_summary.csv", daily, list(daily[0]))
write_csv("settlements.csv", settlements, list(settlements[0]))
write_json("settlement_breakdown_2026-11-18.json", breakdown)
write_json("loan.json", loan)
write_csv("edi_schedule.csv", edi_rows, ["edi_date", "amount", "channel", "status", "bounce_code", "bounce_reason",
                                         "context", "recovery", "recovery_note", "cumulative_collected", "balance_after"])
write_csv("refunds.csv", refunds, ["refund_id", "order_id", "txn_id", "customer_id", "amount", "reason", "requested_at",
                                   "processed_at", "status", "deducted_in_batch"])
write_csv("chargebacks.csv", chargebacks, ["chargeback_id", "txn_id", "order_id", "customer_id", "amount", "reason_code",
                                           "raised_at", "respond_by", "status", "resolved_at", "held_in_batch",
                                           "released_in_batch", "pod_awb", "evidence", "contract_ref"])
write_json("shiprocket_orders.json", {"connector": "SHIPROCKET_SYNC", "mid": MID, "orders": shipments})
write_csv("utr_ledger.csv", utr_rows, list(utr_rows[0]))
write_csv("supplier_payables.csv", payables, list(payables[0]))
write_csv("khata.csv", khata, list(khata[0]))
write_csv("inventory.csv", inventory, list(inventory[0]))
write_csv("device_logs.csv", device_logs, list(device_logs[0]))
write_csv("support_history.csv", support_history, list(support_history[0]))
write_json("strategy_memory.json", strategy)
write_json("scenarios.json", scenarios)

# ============================================================================ README
DICT = {
    "merchant_profile.json": "Merchant identity, KYC, address, settlement terms + MDR rates, devices, the 3 consented "
                             "connectors, `historical_memory` (the 8 contract values, verbatim) and the top 10 customers.",
    "customers.csv": {"customer_id": "C001–C150, plus WALKIN for unidentified one-off shoppers", "name": "Synthetic Indian name",
                      "phone_masked": "Masked mobile", "locality": "Gurugram sector (in-store) or NCR area (ONDC)",
                      "segment": "regular / electrician (buys on khata) / ondc / bulk / walk_in", "first_seen": "First transaction date",
                      "on_khata": "True if the customer buys on store credit", "preferred_app": "Most used UPI app"},
    "transactions.csv": {"txn_id": "PTM + yymmdd + daily sequence", "timestamp": "IST, store hours 07:00–22:00",
                         "amount": "INR integer", "method": "UPI / card / wallet / postpaid", "card_type": "credit / debit (RuPay) for cards",
                         "payer_app": "GPay, PhonePe, Paytm, BHIM, Amazon Pay, Paytm Wallet, Paytm Postpaid, Card (…)",
                         "utr": "12-digit UPI reference (UPI and wallet-on-UPI only); read as text, e.g. `dtype={'utr': str}`", "status": "SUCCESS / PENDING / FAILED (only SUCCESS counts toward gross)",
                         "customer_id": "FK → customers.csv", "order_id": "BILL-yymmdd-nnnn (POS bill), 44xx (phone/home-delivery order) or 99xx (ONDC order)",
                         "channel": "in-store / ONDC", "mdr_rate": "Rate applied (see merchant_profile.settlement.mdr_rates)",
                         "mdr_amount": "MDR on this transaction (2 decimals; batch MDR is rounded to whole rupees)",
                         "settlement_batch_id": "FK → settlements.csv (T+1)", "tag": "Marks demo-relevant records (e.g. ORDER_9981, UTR_SUCCESS)"},
    "daily_sales_summary.csv": {"date": "Calendar day", "weekday": "Day name", "gross": "Sum of SUCCESS transactions",
                                "txn_count": "Number of SUCCESS transactions", "avg_ticket": "gross / txn_count",
                                "upi_share_by_value": "UPI share of gross", "is_weekend": "Fri, Sat or Sun",
                                "is_festival": "Diwali run-up 31 Oct – 8 Nov (Dhanteras 6 Nov)", "rain_dip": "Heavy-rain day (monsoon)",
                                "closure_dip": "Market closure 14–16 Nov (~40% dip)", "bulk_order_day": "17 Nov PG fit-out order",
                                "note": "Human-readable context"},
    "settlements.csv": {"batch_id": "STL-<settlement date>", "settlement_date": "Credit date (T+1)", "txn_date": "Transactions covered",
                        "gross": "Sum of SUCCESS transactions on txn_date", "mdr": "Whole-rupee MDR", "gst_on_mdr": "18% of MDR",
                        "refunds": "Refunds processed on txn_date", "soundbox_rental": "₹149 on the 18th of each month",
                        "chargeback_hold": "Disputes raised on txn_date", "chargeback_release": "Won disputes resolved on txn_date",
                        "net_credit": "gross − deductions + releases", "variance": "gross − net_credit",
                        "credited_at": "Bank credit time", "payout_ref": "Payout reference", "status": "SUCCESS"},
    "settlement_breakdown_2026-11-18.json": "The contract batch, item by item, with the rail-level MDR calculation and the source record of every deduction.",
    "loan.json": "Clix Capital loan: amounts, eNACH mandate, KFS (APR, clauses 4.1–4.3 incl. the 4.2 EDI holiday), collected and balance.",
    "edi_schedule.csv": {"edi_date": "Presentment date (daily from 1 Jun)", "amount": "₹500", "channel": "eNACH",
                         "status": "SUCCESS / BOUNCED", "bounce_code": "Reason code", "bounce_reason": "Bank reason",
                         "context": "What caused it", "recovery": "REMINDER_ONLY / UPI_LINK / AUTO_RETRY / PENDING",
                         "recovery_note": "How and how fast it was recovered", "cumulative_collected": "Running total collected",
                         "balance_after": "total_repayable − cumulative_collected"},
    "refunds.csv": {"refund_id": "RFD-…", "order_id": "FK → transactions.order_id", "txn_id": "FK → transactions.csv",
                    "customer_id": "FK → customers.csv", "amount": "INR", "reason": "Why", "requested_at": "Request time",
                    "processed_at": "Processing time (null if pending)", "status": "PROCESSED / REQUESTED",
                    "deducted_in_batch": "Settlement batch that deducts it"},
    "chargebacks.csv": {"chargeback_id": "CB-…", "txn_id": "FK → transactions.csv", "order_id": "FK → shiprocket_orders.json",
                        "customer_id": "FK → customers.csv", "amount": "INR held", "reason_code": "Dispute reason",
                        "raised_at": "Dispute time", "respond_by": "48h deadline", "status": "HELD / WON / LOST",
                        "resolved_at": "Resolution time", "held_in_batch": "Batch with the hold", "released_in_batch": "Batch with the release",
                        "pod_awb": "Shipment AWB", "evidence": "What evidence exists", "contract_ref": "Contract name for the record"},
    "shiprocket_orders.json": "SHIPROCKET_SYNC connector view: every ONDC order with items, courier, AWB, status and PoD (delivered_at, recipient, otp_verified, signature, document).",
    "utr_ledger.csv": {"utr": "12-digit UPI reference (read as text: `pd.read_csv(..., dtype={'utr': str})`)", "txn_id": "FK → transactions.csv", "amount": "INR", "payer_app": "UPI app",
                       "payer_vpa_masked": "Masked payer VPA", "npci_status": "SUCCESS / PENDING / FAILED",
                       "timestamp": "IST", "order_id": "Order / bill", "customer_id": "FK → customers.csv",
                       "flag": "DUPLICATE / PENDING_AUTO_REVERSAL_T+1 / blank"},
    "supplier_payables.csv": {"payable_id": "PAY-…", "supplier": "Distributor", "invoice_no": "Invoice", "amount": "INR",
                              "invoice_date": "Invoice date", "due_date": "Due date", "status": "PAID / DUE",
                              "paid_on": "Payment date", "source": "VYAPAR_POS_SYNC"},
    "khata.csv": {"entry_id": "KH-…", "customer_id": "FK → customers.csv", "timestamp": "IST",
                  "type": "credit_given / payment_received", "amount": "INR", "txn_id": "FK → transactions.csv for repayments",
                  "balance_after": "Outstanding store credit", "note": "Context"},
    "inventory.csv": {"sku": "SKU code", "name": "Product", "brand": "Brand", "category": "Category", "unit": "Selling unit",
                      "cost_price": "INR", "selling_price": "INR", "mrp": "INR", "margin_pct": "(sell − cost) / sell",
                      "stock_qty": "Units on hand (as of snapshot)", "reorder_point": "Reorder threshold",
                      "below_reorder": "stock_qty < reorder_point", "supplier": "Distributor",
                      "weekend_stockout_count_6m": "Weekends it ran out in the last 6 months"},
    "device_logs.csv": {"ts": "Hourly, 1–18 Nov", "device_id": "SB-8821-01", "device": "Model", "battery_pct": "Charge",
                        "battery_health_pct": "Battery health (degrading from 10 Nov)", "network": "4G / 2G / offline",
                        "signal_dbm": "Signal strength", "heartbeat_ok": "Device reached Paytm servers",
                        "announce_failures": "Payments it failed to announce that hour", "event": "Notable event"},
    "support_history.csv": {"ticket_id": "TKT-PAYTM-…", "opened_at": "IST", "intent": "Plan intent", "summary": "Issue",
                            "channel": "voice / app_chat", "resolution": "What was done", "resolved_at": "IST",
                            "outcome": "RESOLVED / WON / LOST / FRAUD_PREVENTED / OPEN", "csat": "1–5"},
    "strategy_memory.json": "Past interventions with options considered, choice and verified outcome, plus learned policies the Merchant Buddy can cite.",
    "scenarios.json": "One ready fixture per intent: Hinglish trigger, exact record IDs, story, expected root cause, intervention and verified outcome.",
}
lines = [
    f"# Seed data: {NAME} ({MID})", "",
    "Synthetic, deterministic dataset for the Build for Bharat demo. **Every name, number, GSTIN, UTR and address is invented.**", "",
    "```bash", "pip install pandas", "python data/generate_seed.py   # rewrites data/seed/* and runs all validation checks", "```", "",
    f"Period: {START} → {END} ({len(DAYS)} days). Snapshot: {SNAPSHOT:%Y-%m-%d %H:%M} IST on the demo day ({DEMO_DAY}).",
    f"Seed: `{SEED}`. Re-running produces byte-identical files.", "",
    "## How the contract values reconcile", "",
    "| Contract value | How the data makes it true |", "|---|---|",
    "| Daily average ₹32,000 | The 184 daily totals are scaled to exactly ₹58,88,000 (= ₹32,000 × 184), with every effect below included. |",
    "| Fri–Sun 2.3× | The weekend factor is calibrated until the observed Fri–Sun average ÷ Mon–Thu average is 2.30. |",
    "| ₹1,00,000 gross in one settlement | `STL-20261118` is the **T+1 batch for Tue 17 Nov**: the market reopened after a 3-day closure and Rao PG & Hostels paid **₹55,000 by credit card** to fit out a new PG (fans, LED panels, wiring). |",
    "| MDR ₹1,450 (UPI is 0%) | That day's MDR-bearing volume: card + Paytm Postpaid ₹62,600 × 2% = ₹1,252, wallet-on-UPI over ₹2,000 ₹18,000 × 1.1% = ₹198. UPI ₹19,400 × 0%. Electronics sees more card use than a kirana, but UPI is still the largest rail over 6 months. |",
    "| GST ₹261 | 18% of ₹1,450. The store is GST-registered (turnover ~₹1.17 Cr/yr), so it's claimable as ITC. |",
    "| Refund #4412 ₹1,500 | Philips kettle bought 10 Oct as a Diwali gift, failed after first use, returned 16 Nov, refund processed 17 Nov → deducted in the 18 Nov batch. |",
    "| Soundbox ₹149 | Monthly rental, billed on the 18th of each month. |",
    "| Chargeback #9981 ₹800 HELD | ONDC order placed 14 Nov, delivered 16 Nov (OTP + signature), dispute raised 17 Nov → held in the 18 Nov batch. |",
    "| Net ₹95,840 | 1,00,000 − (1,450 + 261 + 1,500 + 149 + 800) = 95,840. |",
    "| EDI ₹500/day, 96% success | eNACH from 1 Jun: 164 of 171 first attempts succeeded (95.9%). EDI is debited from the **bank account**, not netted from settlements, which is why it's absent from the 18 Nov breakdown and how a mandate can bounce. |",
    "| Loan balance ₹42,000 | Total repayable ₹1,27,000 (254 × ₹500) − collected ₹85,000 (164 successes + 6 recovered bounces). The 17 Nov bounce is not yet recovered. |",
    "| ₹4,500 due tomorrow | `PAY-TOMORROW`: Gaffar Market accessories wholesaler invoice of 18 Nov (chargers, earphones for the weekend), due Fri 20 Nov. |",
    "| Cashflow: payout ₹1,200 | Contract V2 numbers kept (plan.md's ₹8,500 refund was not used): ₹4,700 collected by 11:30 on 19 Nov − ₹3,500 refund request #4490 = ₹1,200. |",
    f"| UTRs | `{UTR_SUCCESS}` ₹1,250 GPay SUCCESS (18 Nov 11:03), `{UTR_PENDING}` ₹2,400 PhonePe PENDING (18 Nov 18:15). `{UTR_FAKE}` (fake-screenshot test) is deliberately **absent**. |",
    "| Connectors | SHIPROCKET_SYNC, VYAPAR_POS_SYNC, RBI_ACCOUNT_AGGREGATOR are all ACTIVE with DPDP consent GRANTED. |", "",
    "Other decisions:",
    "- **Shop type:** an electronics, appliances and electricals shop, as in contract.md (*Sharma Electronics*). Bills are "
    "fewer and larger than a kirana's, card use is higher, summer lifts fan sales, and Dhanteras (6 Nov) is the biggest day of the festive run.",
    "- **Khata** (store credit) goes to 8 local electricians who buy wires and switches for site jobs.",
    "- **Rain in November** isn't realistic for Gurugram, so the dip before the 17 Nov bounce is a **market closure** (14–16 Nov). "
    "Monsoon rain explains the July/August bounces.",
    "- **Chargeback #9981** uses exactly the values on `services/sarvam_service/app/samples/pod_9981.png` "
    "(₹800, delivered 2026-11-16 to Rohit Verma, OTP-verified, AWB DEX7781203345).",
    "- contract.md calls the dispute `TXNID #9981`; the real payment row has a normal txn_id, and "
    "`chargebacks.csv.contract_ref` keeps the contract's name.",
    "- **Intent names:** `scenarios.json` uses the 8 plan.md names and adds `contract_v1_intent` for the 6 older names.", "",
    "## Scenario stories", "",
]
for s in scenarios["scenarios"]:
    lines.append(f"- **{s['intent']}**: {s['story']} → *{s['expected_verified_outcome']}*")
lines += ["", "## Data dictionary", ""]
for fname, desc in DICT.items():
    lines.append(f"### `{fname}`")
    if isinstance(desc, str):
        lines.append(desc)
    else:
        lines += ["| Column | Meaning |", "|---|---|"] + [f"| `{c}` | {m} |" for c, m in desc.items()]
    lines.append("")
(OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")

# ============================================================================ validation (reads files back from disk)
R = lambda n: pd.read_csv(OUT / n, dtype=str, keep_default_na=False)  # noqa: E731
J = lambda n: json.loads((OUT / n).read_text(encoding="utf-8"))       # noqa: E731
p_ = J("merchant_profile.json")
tx = R("transactions.csv")
for c in ("amount",):
    tx[c] = tx[c].astype(int)
st = R("settlements.csv")
ds = R("daily_sales_summary.csv")
edi = R("edi_schedule.csv")
utr = R("utr_ledger.csv")
cb = R("chargebacks.csv")
rf = R("refunds.csv")
ship = {o["order_id"]: o for o in J("shiprocket_orders.json")["orders"]}
cust_ids = set(R("customers.csv")["customer_id"])
ln = J("loan.json")
pay = R("supplier_payables.csv")

# 1. HARD CONSTRAINTS, exactly
assert p_["historical_memory"] == HISTORICAL_MEMORY, p_["historical_memory"]
assert p_["mid"] == MID and p_["name"] == NAME
assert {c["name"]: c["status"] for c in p_["connectors"]} == CONNECTORS
assert "#9981" in [c for c in p_["connectors"] if c["name"] == "SHIPROCKET_SYNC"][0]["holds"]
row = st[st.batch_id == "STL-20261118"].iloc[0]
got = {k: int(row[k]) for k in ("gross", "mdr", "gst_on_mdr", "refunds", "soundbox_rental", "chargeback_hold",
                                "chargeback_release", "net_credit", "variance")}
assert got == {"gross": 100000, "mdr": 1450, "gst_on_mdr": 261, "refunds": 1500, "soundbox_rental": 149,
               "chargeback_hold": 800, "chargeback_release": 0, "net_credit": 95840, "variance": 4160}, got
assert row["settlement_date"] == "2026-11-18"
bd = J("settlement_breakdown_2026-11-18.json")
assert {d["type"]: d["amount"] for d in bd["deductions"]} == {"MDR": 1450, "GST_ON_MDR": 261, "REFUND": 1500,
                                                             "SOUNDBOX_RENTAL": 149, "CHARGEBACK_HOLD": 800}
assert bd["gross"] == 100000 and bd["net_credit"] == 95840
assert ln["lender"] == "Clix Capital" and ln["daily_edi"] == 500 and ln["loan_balance"] == 42000
assert ln["kfs_edi_holiday_eligible"] is True and "4.2" in ln["kfs"]["clauses"]
u = utr.set_index("utr")
assert (u.loc[UTR_SUCCESS, "amount"], u.loc[UTR_SUCCESS, "payer_app"], u.loc[UTR_SUCCESS, "npci_status"]) == ("1250", "GPay", "SUCCESS")
assert (u.loc[UTR_PENDING, "amount"], u.loc[UTR_PENDING, "payer_app"], u.loc[UTR_PENDING, "npci_status"]) == ("2400", "PhonePe", "PENDING")
assert UTR_FAKE not in set(utr["utr"]) and UTR_FAKE not in set(tx["utr"]), "fake UTR must not exist"
assert utr["utr"].is_unique
tp = pay[pay.payable_id == "PAY-TOMORROW"].iloc[0]
assert (int(tp["amount"]), tp["due_date"], tp["status"]) == (4500, "2026-11-20", "DUE")
assert ((pay.due_date == "2026-11-20") & (pay.status == "DUE")).sum() == 1
assert not ((pay.due_date <= "2026-11-20") & (pay.status == "DUE") & (pay.payable_id != "PAY-TOMORROW")).any()
assert 20 <= ln["kfs"]["apr_percent"] <= 40, ln["kfs"]["apr_percent"]
r4412 = rf[rf.refund_id == "RFD-4412"].iloc[0]
assert (int(r4412["amount"]), r4412["order_id"], r4412["deducted_in_batch"]) == (1500, "4412", "STL-20261118")
c9981 = cb[cb.chargeback_id == "CB-9981"].iloc[0]
assert (int(c9981["amount"]), c9981["status"], c9981["order_id"], c9981["held_in_batch"]) == (800, "HELD", "9981", "STL-20261118")

# 2. variance arithmetic
assert 1450 + 261 + 1500 + 149 + 800 == 4160 == 100000 - 95840
assert round(1450 * 0.18) == 261

# 3. daily average + weekend pattern
gross_by_day = tx[tx.status == "SUCCESS"].groupby(tx.timestamp.str[:10])["amount"].sum()
assert len(gross_by_day) == 184 and gross_by_day.sum() == TOTAL_GROSS
assert abs(gross_by_day.mean() - 32000) < 1, gross_by_day.mean()
wkd = pd.to_datetime(gross_by_day.index).weekday
ratio = gross_by_day[wkd >= 4].mean() / gross_by_day[wkd < 4].mean()
assert 2.25 <= ratio <= 2.35, ratio
closure = gross_by_day[[d.isoformat() for d in sorted(CLOSURE_DAYS)]].sum()
oct_ = gross_by_day[(gross_by_day.index >= "2026-10-03") & (gross_by_day.index <= "2026-10-30")]
oct_wd = pd.to_datetime(oct_.index).weekday
normal = sum(oct_[oct_wd == d.weekday()].mean() for d in sorted(CLOSURE_DAYS))
dip = 1 - closure / normal
assert 0.30 <= dip <= 0.50, dip  # ~40% below the same weekdays in ordinary (pre-festive) October weeks
assert int(gross_by_day["2026-11-17"]) == 100000

cnt = tx[tx.status == "SUCCESS"].groupby(tx.timestamp.str[:10]).size()
assert cnt.min() >= 8 and 20 <= cnt.mean() <= 70, (cnt.min(), cnt.mean())

# 4. EDI ~96%
succ = (edi.status == "SUCCESS").sum() / len(edi)
assert len(edi) == 171 and round(succ * 100) == 96, succ
assert edi.iloc[-1]["edi_date"] == "2026-11-17" or edi[edi.edi_date == "2026-11-17"].iloc[0]["status"] == "BOUNCED"
assert int(edi.iloc[-1]["balance_after"]) == 42000

# 5. foreign keys + internal consistency
assert set(tx.customer_id) <= cust_ids
tx_ids = set(tx.txn_id)
assert set(rf.txn_id) <= tx_ids and set(cb.txn_id) <= tx_ids and set(utr.txn_id) <= tx_ids
kh = R("khata.csv")
assert set(kh[kh.txn_id != ""].txn_id) <= tx_ids and set(kh.customer_id) <= set(KHATA_CUSTOMERS)
assert (kh.balance_after.astype(int) >= 0).all()
for _, c in cb.iterrows():
    assert c["order_id"] in ship, c["order_id"]
    assert tx.set_index("txn_id").loc[c["txn_id"], "order_id"] == c["order_id"]
pod = ship["9981"]["pod"]
assert pod["recipient"] == "Rohit Verma" and pod["otp_verified"] and pod["signature"] and pod["delivered_at"].startswith("2026-11-16")
assert ship["9981"]["amount"] == 800
for _, r in rf.iterrows():
    assert tx.set_index("txn_id").loc[r["txn_id"], "order_id"] == r["order_id"]
s_by_date = st.set_index("txn_date")["gross"].astype(int)
assert (s_by_date.sort_index() == gross_by_day.sort_index()).all(), "settlement gross must equal transactions"
assert (ds.set_index("date")["gross"].astype(int).sort_index() == gross_by_day.sort_index()).all()
assert set(tx[tx.settlement_batch_id != ""].settlement_batch_id) <= set(st.batch_id)
d_ = tx[tx.tag.str.startswith("DUPLICATE")]
assert len(d_) == 2 and d_.order_id.nunique() == 1 and d_.customer_id.nunique() == 1 and d_.amount.nunique() == 1
assert {"9981", "4412", "4490", DUP_ORDER} <= set(tx.order_id)
sc = J("scenarios.json")["scenarios"]
assert [s["intent"] for s in sc] == ["MANDATE_TROUBLESHOOT", "SETTLEMENT_RECONCILE", "CHARGEBACK_RESOLVE", "UTR_VERIFY",
                                     "DUPLICATE_RECONCILE", "GROWTH_ADVISORY", "CASHFLOW_EDI_SWITCH", "ESCALATE_HUMAN"]
cf = sc[6]["cashflow_projection"]
assert cf["collections_so_far"] - cf["refund_request"] == cf["projected_net_payout"] == 1200
assert cf["tomorrow_stock_due"] - cf["projected_net_payout"] == cf["shortfall"] == 3300

print(f"""
All checks passed. Wrote {len(list(OUT.iterdir()))} files to {OUT}
  merchant           {NAME} ({MID}), {len(cust_ids) - 1} customers + walk-ins
  period             {START} → {END} (184 days), {len(tx):,} payment rows ({(tx.status == 'SUCCESS').sum():,} successful)
  daily average      ₹{gross_by_day.mean():,.0f}   Fri–Sun ÷ Mon–Thu = {ratio:.2f}x
  STL-20261118       gross ₹1,00,000 − ₹4,160 = net ₹95,840
  closure dip        {dip:.0%} below normal on 14–16 Nov (same weekdays, October)
  EDI                {(edi.status == 'SUCCESS').sum()}/{len(edi)} first-attempt success ({succ:.1%}), balance ₹42,000
  UTRs               …0111 SUCCESS, …0999 PENDING, …0555 absent (fake)
  scenarios          8 intents with fixtures in scenarios.json
""")
