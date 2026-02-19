"""Test bildirim portal via direct httpx POST (no browser needed)."""

import asyncio
import re
import httpx

BILDIRIM_URL = (
    "https://bildirim.epdk.gov.tr/bildirim-portal/faces/pages/"
    "tarife/petrol/illereGorePetrolAkaryakitFiyatSorgula.xhtml"
)


async def test():
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "tr-TR,tr;q=0.9",
    }

    async with httpx.AsyncClient(
        timeout=60, follow_redirects=True, headers=headers
    ) as client:
        # Step 1: GET the page to extract ViewState token
        print("Step 1: Getting page and ViewState...")
        resp = await client.get(BILDIRIM_URL)
        print(f"GET status: {resp.status_code}")

        # Extract ViewState
        vs_pattern = r'name="javax\.faces\.ViewState"[^>]*value="([^"]+)"'
        viewstate_match = re.search(vs_pattern, resp.text)

        if not viewstate_match:
            # Try alternative pattern
            vs_pattern2 = r'id="j_id1:javax\.faces\.ViewState:0"\s+value="([^"]+)"'
            viewstate_match = re.search(vs_pattern2, resp.text)

        if viewstate_match:
            viewstate = viewstate_match.group(1)
            print(f"ViewState found: {viewstate[:80]}...")
        else:
            print("ViewState NOT found!")
            # Debug
            vs_area = resp.text[resp.text.find("ViewState"):resp.text.find("ViewState") + 200]
            print(f"ViewState area: {vs_area}")
            return

        # Step 2: POST the form data with ViewState
        print("\nStep 2: Submitting form...")
        form_data = {
            "javax.faces.partial.ajax": "true",
            "javax.faces.source": "akarYakitFiyatlariKriterleriForm:j_idt49",
            "javax.faces.partial.execute": "@all",
            "javax.faces.partial.render": "akaryakitSorguSonucu messages akarYakitFiyatlariKriterleriForm",
            "akarYakitFiyatlariKriterleriForm:j_idt49": "akarYakitFiyatlariKriterleriForm:j_idt49",
            "akarYakitFiyatlariKriterleriForm": "akarYakitFiyatlariKriterleriForm",
            "akarYakitFiyatlariKriterleriForm:j_idt29_input": "14.02.2026",
            "akarYakitFiyatlariKriterleriForm:j_idt32_focus": "",
            "akarYakitFiyatlariKriterleriForm:j_idt32_input": "Tümü",
            "akarYakitFiyatlariKriterleriForm:j_idt36_input": "14.02.2026",
            "akarYakitFiyatlariKriterleriForm:j_idt39_focus": "",
            "akarYakitFiyatlariKriterleriForm:j_idt39_input": "Tümü",
            "akarYakitFiyatlariKriterleriForm:j_idt46_focus": "",
            "akarYakitFiyatlariKriterleriForm:j_idt46_input": "Kurşunsuz Benzin 95 Oktan",
            "javax.faces.ViewState": viewstate,
        }

        post_headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Faces-Request": "partial/ajax",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": BILDIRIM_URL,
            "Origin": "https://bildirim.epdk.gov.tr",
        }

        resp2 = await client.post(BILDIRIM_URL, data=form_data, headers=post_headers)
        print(f"POST status: {resp2.status_code}")
        print(f"Response length: {len(resp2.text)}")

        # Extract data from CDATA sections
        cdata_matches = re.findall(r"<!\[CDATA\[(.*?)\]\]>", resp2.text, re.DOTALL)
        print(f"CDATA sections: {len(cdata_matches)}")

        for idx, cdata in enumerate(cdata_matches):
            if "data-ri" in cdata or "Benzin" in cdata or "Motorin" in cdata:
                print(f"\nCDATA {idx} has fuel data!")
                # Extract table cells
                tds = re.findall(r"<td[^>]*>(.*?)</td>", cdata, re.DOTALL)
                clean_data = []
                for td in tds:
                    clean = re.sub(r"<[^>]+>", "", td).strip()
                    if clean and not clean.startswith("PrimeFaces") and len(clean) < 200:
                        clean_data.append(clean)

                # Parse records: date, city, distributor, product, price
                i = 0
                records = []
                date_pattern = re.compile(r"\d{2}\.\d{2}\.\d{4}")
                while i < len(clean_data):
                    if date_pattern.match(clean_data[i]) and i + 4 < len(clean_data):
                        records.append({
                            "tarih": clean_data[i],
                            "il": clean_data[i + 1],
                            "dagitici": clean_data[i + 2],
                            "urun": clean_data[i + 3],
                            "fiyat": clean_data[i + 4],
                        })
                        i += 5
                    else:
                        i += 1

                print(f"Records parsed: {len(records)}")
                for r in records:
                    print(
                        f"  {r['tarih']} | {r['il']} | {r['dagitici']} "
                        f"| {r['urun']} | {r['fiyat']}"
                    )

        if not cdata_matches:
            # Check for Kayıt Bulunamadı or error
            if "Kayıt Bulunamadı" in resp2.text:
                print("No records found (Kayıt Bulunamadı)")
            elif "Blocked" in resp2.text:
                print("BLOCKED by WAF!")
            else:
                print("Unknown response:")
                print(resp2.text[:2000])


asyncio.run(test())
