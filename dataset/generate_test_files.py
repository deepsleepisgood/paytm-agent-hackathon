"""Generate placeholder demo images. Run: python3 generate_test_files.py"""
from PIL import Image, ImageDraw
def card(path, title, lines, color):
    im = Image.new("RGB", (600, 800), "white"); d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 600, 110], fill=color); d.text((30, 40), title, fill="white")
    y = 170
    for l in lines:
        d.text((30, y), l, fill="black"); y += 48
    im.save(path)
card("test_files/pod_9981.png", "PROOF OF DELIVERY", ["Order ID: #9981", "Status: DELIVERED", "Customer: Rohit Verma", "Date: 2026-11-17", "Signature: R. Verma"], (0, 46, 110))
card("test_files/fake_upi.png", "Payment Successful", ["Rs 2,400 paid", "To: Sharma Electronics", "UPI Ref / UTR: 632184920000", "From: PhonePe", "Date: 2026-11-18"], (95, 37, 159))
