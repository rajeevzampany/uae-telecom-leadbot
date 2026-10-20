"""Offline tests: parsing, normalisation, dedupe and the full pipeline with mocked network."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date  # noqa: E402

from leadbot import config, contacts, extract, freezones, sheet, sources  # noqa: E402

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Brew &amp; Bloom cafe opens in Al Quoz, Dubai - Khaleej Times</title>
<link>https://news.google.com/rss/articles/abc</link>
<description>&lt;a href="x"&gt;Brew &amp;amp; Bloom&lt;/a&gt; opens doors this week, call 04 321 7788</description>
<source url="https://www.khaleejtimes.com">Khaleej Times</source></item>
<item><title>Unrelated</title><link>https://news.google.com/rss/articles/def</link>
<description>x</description><source>Gulf News</source></item>
</channel></rss>"""


class ContactTests(unittest.TestCase):
    def test_phones(self):
        p, _ = contacts.extract("Call +971 4 123 4567 or 050-765-4321, toll free 800 12345; id 12345678901")
        self.assertIn("+971 4 123 4567", p)
        self.assertIn("+971 50 765 4321", p)

    def test_00971_and_landline(self):
        p, _ = contacts.extract("00971 2 555 1212 / (06) 555 0000")
        self.assertEqual(p, ["+971 2 555 1212", "+971 6 555 0000"])

    def test_emails_filtered(self):
        _, e = contacts.extract("hello@brewbloom.ae logo@2x.png info@example.com")
        self.assertEqual(e, ["hello@brewbloom.ae"])

    def test_best_email_prefers_own_domain(self):
        self.assertEqual(contacts.best_email(["press@agency.com", "info@brew.ae"], "https://www.brew.ae"),
                         "info@brew.ae")


class ParseTests(unittest.TestCase):
    def test_rss(self):
        c = sources.parse_google_news(RSS)
        self.assertEqual(len(c), 2)
        self.assertEqual(c[0].channel, "Google News: Khaleej Times")
        self.assertIn("04 321 7788", c[0].snippet)

    def test_channel(self):
        self.assertEqual(sources.channel_for("https://www.instagram.com/p/xyz"), "Instagram")
        self.assertEqual(sources.channel_for("https://ae.linkedin.com/posts/a"), "LinkedIn")

    def test_llm_json(self):
        self.assertEqual(extract.parse_json_array('Sure!\n[{"item":1}]\n'), [{"item": 1}])
        self.assertEqual(extract.parse_json_array("no json"), [])

    def test_name_norm(self):
        self.assertEqual(sheet.norm_name("The Brew & Bloom Cafe L.L.C"), sheet.norm_name("brew bloom cafe"))
        self.assertEqual(sheet.norm_site("www.brew.ae/contact"), "brew.ae")
        self.assertEqual(sheet.norm_site("https://instagram.com/brew"), "")


class FreeZoneTests(unittest.TestCase):
    def test_detect_aliases(self):
        self.assertEqual(freezones.detect("New cafe opens in Cluster T, JLT").code, "DMCC")
        self.assertEqual(freezones.detect("firm opens office on Al Maryah Island").code, "ADGM")
        self.assertEqual(freezones.detect("RAKEZ welcomes logistics firm").code, "RAKEZ")
        self.assertEqual(freezones.detect("sets up in Dubai Silicon Oasis").code, "DSO")

    def test_no_false_positive(self):
        self.assertIsNone(freezones.detect("New restaurant in Business Bay, Dubai"))
        self.assertIsNone(freezones.detect("enjoy the shams of summer"))   # lowercase, not SHAMS
        self.assertIsNone(freezones.detect("the dso said"))

    def test_queries_and_reference(self):
        self.assertEqual(len(freezones.news_queries()), len(freezones.ZONES))
        self.assertTrue(all(q.startswith("site:") for q in freezones.web_queries()))
        ref = freezones.reference_rows()
        self.assertEqual(len(ref), len(freezones.ZONES) + 1)
        dmcc = next(r for r in ref if r[0] == "DMCC")
        self.assertIn("prohibit", dmcc[5])
        self.assertTrue(all(r[4].startswith("https://") for r in ref[1:]))


class ComplianceTests(unittest.TestCase):
    def test_mobile_flag(self):
        self.assertEqual(contacts.label("+971 4 123 4567"), "+971 4 123 4567")
        self.assertIn("may be personal", contacts.label("+971 50 765 4321"))

    def test_optout(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write("# comment\nBrew & Bloom Cafe LLC\nother.ae\n+971 4 999 0000\n")
        try:
            o = sheet.load_optouts(f.name)
        finally:
            os.unlink(f.name)
        lead = {"company_name": "Brew and Bloom Cafe", "website": "", "email": "", "phone": ""}
        self.assertTrue(sheet.is_opted_out(lead, o))
        self.assertTrue(sheet.is_opted_out({"company_name": "X", "website": "https://www.other.ae",
                                            "email": "", "phone": ""}, o))
        self.assertTrue(sheet.is_opted_out({"company_name": "Y", "website": "", "email": "",
                                            "phone": "+971 4 999 0000"}, o))
        self.assertFalse(sheet.is_opted_out({"company_name": "Z", "website": "", "email": "",
                                             "phone": ""}, o))

    def test_retention(self):
        vals = [config.HEADERS, ["2026-08-01"], ["2026-09-01"], ["2026-10-19"]]
        self.assertEqual(sheet.rows_to_expire(vals, 30, date(2026, 10, 20)), [2, 3])
        self.assertEqual(sheet.rows_to_expire(vals, 0, date(2026, 10, 20)), [])

    def test_robots_blocks(self):
        from leadbot import http
        http._robots.clear()
        with mock.patch("leadbot.http.get", return_value=("u", "User-agent: *\nDisallow: /\n")):
            self.assertFalse(http.allowed_by_robots("https://blocked.example/contact"))
        with mock.patch("leadbot.http.get", return_value=("u", "User-agent: *\nDisallow: /admin\n")):
            self.assertTrue(http.allowed_by_robots("https://open.example/contact"))


TIMEOUT_FEED = """<?xml version="1.0"?>
<rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel><title>Time Out Dubai</title>
<item><title>11 new restaurants to try in Dubai this month</title>
<link>https://www.timeoutdubai.com/restaurants/new-restaurants-this-month</link>
<description>Short excerpt</description>
<content:encoded><![CDATA[<p><b>Saffron Lane</b> - a modern Indian spot in Dubai Hills Mall. Call 04 222 3333.</p>
<p><b>Koi Garden</b> - Japanese izakaya now open in DIFC Gate Village. Tel 04 555 6666.</p>]]></content:encoded></item>
<item><title>30 dining deals in Dubai this week</title>
<link>https://www.timeoutdubai.com/restaurants/deals</link><description>deals</description></item>
</channel></rss>"""


class ListingSiteTests(unittest.TestCase):
    def test_config_queries(self):
        self.assertTrue(any("site:timeoutdubai.com" in q for q in config.NEWS_QUERIES))
        self.assertTrue(any("site:timeoutabudhabi.com" in q for q in config.NEWS_QUERIES))
        self.assertEqual(sum("site:timeout" in q for q in config.WEB_QUERIES), 4)

    def test_channel_names(self):
        self.assertEqual(sources.channel_for("https://www.timeoutdubai.com/x"), "Time Out Dubai")
        self.assertEqual(sources.channel_for("https://www.timeoutabudhabi.com/x"), "Time Out Abu Dhabi")

    def test_feed_filters_and_full_content(self):
        c = sources.parse_rss(TIMEOUT_FEED, "Time Out Dubai")
        self.assertEqual(len(c), 1)                       # deals article filtered out
        self.assertIn("Koi Garden", c[0].snippet)          # content:encoded used

    def test_article_text(self):
        page = "<html><nav>Menu Home</nav><body><article><h1>New cafes</h1><p>Bean There opens</p></article>" \
               "<footer>(c) 04 000 0000</footer><script>var a=1</script></body></html>"
        t = sources.article_text(page)
        self.assertIn("Bean There opens", t)
        self.assertNotIn("Menu", t)
        self.assertNotIn("04 000 0000", t)

    def test_expand_fetches_short_snippets_only(self):
        short = sources.Candidate("New restaurants open", "tiny", "https://www.timeoutabudhabi.com/a", "Time Out Abu Dhabi")
        other = sources.Candidate("New restaurants open", "tiny", "https://gulfnews.com/a", "gulfnews.com")
        page = "<body><article>" + "Al Fanar Cafe opens on Saadiyat. " * 60 + "</article></body>"
        with mock.patch("leadbot.http.polite_get", return_value=("u", page)) as g:
            self.assertEqual(sources.expand_listing_articles([short, other]), 1)
        g.assert_called_once()
        self.assertIn("Al Fanar Cafe", short.snippet)

    def test_listicle_contacts_not_mixed(self):
        from leadbot.enrich import enrich
        cand = sources.parse_rss(TIMEOUT_FEED, "Time Out Dubai")[0]
        cand.snippet = cand.snippet + " filler" * 300      # make it "full article" length
        lead = {"company_name": "Koi Garden", "phone": "", "email": "", "website": "",
                "location": "Gate Village, DIFC", "source": cand}
        with mock.patch("leadbot.http.polite_get", return_value=None):
            out = enrich(lead)
        self.assertEqual(out["phone"], "+971 4 555 6666")


def row(values):
    return dict(zip(config.HEADERS, values))


def _lead(name, url="https://x.com/a", conf=0.8, **kw):
    base = {"company_name": name, "business_type": "cafe", "location": "", "website": "", "phone": "",
            "email": "", "confidence": conf, "free_zone_hint": "",
            "source": sources.Candidate(name, "", url, sources.channel_for(url))}
    base.update(kw)
    return base


class DedupeTests(unittest.TestCase):
    def test_same_name_variants(self):
        from leadbot.dedupe import same_name
        n = sheet.norm_name
        self.assertTrue(same_name(n("ROKA"), n("Roka Dubai")))
        self.assertTrue(same_name(n("Cafe Bateel"), n("Bateel")))
        self.assertTrue(same_name(n("Al Sharqi Trading LLC"), n("Al Sharqi")))
        self.assertTrue(same_name(n("Milora Gold & Diamonds"), n("Milora Gold and Diamonds")))
        self.assertFalse(same_name(n("Koi Garden"), n("Koi Kitchen")))
        self.assertFalse(same_name(n("Gold Store"), n("Gold Souk Store")))    # generic words only
        self.assertFalse(same_name(n("China Securities"), n("Dubai Securities")))

    def test_merge_within_keeps_one_and_fills_fields(self):
        from leadbot import dedupe
        a = _lead("ROKA", "https://news.google.com/rss/articles/1", 0.9, location="Dubai")
        b = _lead("Roka Dubai", "https://www.timeoutdubai.com/roka", 0.7,
                  location="Palm West Beach, Dubai", phone="+971 4 111 2222")
        c = _lead("Saffron Lane", "https://gulfnews.com/s", 0.8)
        out = dedupe.merge_within([b, a, c])
        self.assertEqual(len(out), 2)
        roka = next(l for l in out if "roka" in l["company_name"].lower())
        self.assertEqual(roka["company_name"], "ROKA")                    # highest confidence kept
        self.assertEqual(roka["phone"], "+971 4 111 2222")                # filled from duplicate
        self.assertEqual(roka["location"], "Palm West Beach, Dubai")      # more specific wins
        self.assertEqual(len(roka["extra_sources"]), 1)

    def test_match_on_site_phone_email(self):
        from leadbot import dedupe
        idx = dedupe.Index()
        old_layout = ["DATE", "COMPANY NAME", "CONTACT NUMBER", "EMAIL", "LOCATION", "WEBSITE", "SOURCE", "FREE ZONE"]
        idx.add_sheet_row(["2026-10-01", "Brew Bloom", "+971 4 321 7788", "hi@brew.ae", "", "https://brew.ae", "", ""],
                          old_layout)
        self.assertIsNotNone(idx.match(_lead("Totally Different", website="www.brew.ae/contact")))
        self.assertIsNotNone(idx.match(_lead("Other Name", phone="04 321 7788")))
        self.assertIsNotNone(idx.match(_lead("Third", email="HI@brew.ae")))
        self.assertIsNotNone(idx.match(_lead("The Brew & Bloom Cafe")))
        self.assertIsNone(idx.match(_lead("Saffron Lane")))

    def test_pipeline_merges_repeats_into_one_row(self):
        from leadbot import main
        rss = """<?xml version="1.0"?><rss><channel>
<item><title>ROKA opens on the Palm - Time Out Dubai</title><link>https://news.google.com/rss/articles/r1</link>
<description>x</description><source>Time Out Dubai</source></item>
<item><title>Japanese restaurant Roka arrives in Dubai - Gulf News</title><link>https://news.google.com/rss/articles/r2</link>
<description>y</description><source>Gulf News</source></item></channel></rss>"""
        llm = ('[{"item":1,"company_name":"ROKA","business_type":"restaurant","location":"The Palm, Dubai",'
               '"free_zone":"","website":"","phone":"","email":"","confidence":0.9},'
               '{"item":2,"company_name":"Roka Dubai","business_type":"restaurant","location":"Dubai",'
               '"free_zone":"","website":"","phone":"","email":"","confidence":0.8}]')
        rows = PipelineTest()._run(rss, llm)
        self.assertEqual(len(rows), 1)
        self.assertIn("also in: Google News: Gulf News", row(rows[0])["SOURCE"])


class EnrichHelperTests(unittest.TestCase):
    def test_clean_location(self):
        from leadbot.enrich import clean_location
        self.assertEqual(clean_location("Dubai, Dubai"), "Dubai")
        self.assertEqual(clean_location("Gate Village, DIFC, Dubai, UAE"), "Gate Village, DIFC, Dubai")

    def test_official_site(self):
        from leadbot.enrich import is_official_site
        self.assertTrue(is_official_site("https://www.rokarestaurant.com/dubai", "ROKA"))
        self.assertTrue(is_official_site("https://milora.ae", "Milora Gold & Diamonds"))
        self.assertTrue(is_official_site("https://www.koi-garden.ae", "Koi Garden"))
        self.assertFalse(is_official_site("https://www.timeoutdubai.com/roka", "ROKA"))
        self.assertFalse(is_official_site("https://www.instagram.com/roka", "ROKA"))
        self.assertFalse(is_official_site("https://www.goldstore.ae", "Gold Store"))   # generic name
        self.assertFalse(is_official_site("https://www.unrelated.com", "Saffron Lane"))

    def test_article_lookup_and_website(self):
        from leadbot import enrich as en, search
        lead = _lead("Koi Garden", "https://news.google.com/rss/articles/k1", location="Dubai")
        lead["source"].title = "Koi Garden opens in DIFC - Gulf News"
        article = ("<body><article>" + "Intro text about Dubai dining. " * 20 +
                   "Koi Garden is now open at Gate Village 3, DIFC. Call 04 555 6666.</article></body>")
        searches = [
            [{"title": "Koi Garden opens in DIFC", "url": "https://gulfnews.com/koi", "description": "d"}],
            [{"title": "Koi Garden - Home", "url": "https://www.koigarden.ae/menu", "description": "d"},
             {"title": "Koi on Instagram", "url": "https://instagram.com/koi", "description": "d"}],
        ]
        def fake_get(url, **kw):
            return ("u", article) if "gulfnews" in url else None
        with mock.patch.dict(os.environ, {"BRAVE_API_KEY": "k"}), \
                mock.patch("leadbot.search.web_search", side_effect=searches), \
                mock.patch("leadbot.http.polite_get", side_effect=fake_get), \
                mock.patch("leadbot.extract.details_from_article",
                           return_value={"location": "Gate Village 3, DIFC, Dubai", "free_zone": "DIFC"}):
            out = en.enrich(lead, search.Budget(5))
        self.assertEqual(out["article_url"], "https://gulfnews.com/koi")
        self.assertEqual(out["location"], "Gate Village 3, DIFC, Dubai")
        self.assertEqual(out["free_zone_hint"], "DIFC")
        self.assertEqual(out["phone"], "+971 4 555 6666")
        self.assertEqual(out["website"], "https://www.koigarden.ae")

    def test_budget(self):
        from leadbot import search
        b = search.Budget(1)
        self.assertTrue(b.take())
        self.assertFalse(b.take())


class MarketEntryTests(unittest.TestCase):
    def test_normalisers(self):
        self.assertEqual(extract.norm_stage("Opening soon"), "Opening soon")
        self.assertEqual(extract.norm_stage("announced plans"), "Announced")
        self.assertEqual(extract.norm_stage("opened last week"), "Recently opened")
        self.assertEqual(extract.norm_yes_no("yes - first UAE store"), "Yes")
        self.assertEqual(extract.norm_yes_no(""), "Unknown")
        self.assertEqual(extract.norm_emirate("Al Ain"), "Abu Dhabi")
        self.assertEqual(extract.norm_emirate("RAK"), "Ras Al Khaimah")
        self.assertEqual(extract.norm_emirate("Mleiha, Sharjah"), "Sharjah")
        self.assertEqual(extract.norm_emirate("somewhere"), "")

    def test_queries_cover_all_emirates_and_arabic(self):
        text = " ".join(config.NEWS_QUERIES)
        for e in config.EMIRATES + ["Al Ain"]:
            self.assertIn(f'"{e}"', text)
        self.assertGreaterEqual(len(config.NEWS_QUERIES_AR), 10)
        self.assertEqual(config.NEWS_WINDOW, "7d")

    def test_market_fields_in_row(self):
        from leadbot import main
        rss = """<?xml version="1.0"?><rss><channel>
<item><title>UK bakery chain Gail's to open first UAE store in Sharjah - Gulf News</title>
<link>https://news.google.com/rss/articles/g1</link><description>x</description><source>Gulf News</source></item>
</channel></rss>"""
        llm = ('[{"item":1,"company_name":"Gail\'s Bakery","sector":"Bakery cafe","business_type":"cafe",'
               '"stage":"Opening soon","expected_opening":"Q1 2027","new_to_uae":"Yes","origin":"UK",'
               '"emirate":"Sharjah","location":"Aljada, Sharjah","free_zone":"","website":"","phone":"",'
               '"email":"","confidence":0.9}]')
        r = row(PipelineTest()._run(rss, llm)[0])
        self.assertEqual(config.HEADERS[:3], ["DATE", "COMPANY NAME", "SECTOR"])
        self.assertEqual((r["STAGE"], r["EXPECTED OPENING"], r["NEW TO UAE"], r["ORIGIN"], r["EMIRATE"]),
                         ("Opening soon", "Q1 2027", "Yes", "UK", "Sharjah"))
        self.assertEqual(r["SECTOR"], "Bakery cafe")


FZ_RSS = """<?xml version="1.0"?><rss><channel>
<item><title>DMCC welcomes Nordic Freight as it opens new office in JLT - WAM</title>
<link>https://news.google.com/rss/articles/fz1</link>
<description>Nordic Freight opened its Middle East office in Almas Tower.</description>
<source>WAM</source></item></channel></rss>"""


class PipelineTest(unittest.TestCase):
    def _run(self, rss, llm):
        from leadbot import main

        cands = sources.parse_google_news(rss)
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "x"}, clear=False), \
                mock.patch("leadbot.config.STATE_FILE", os.path.join(d, "seen.json")), \
                mock.patch("leadbot.config.OPTOUT_FILE", os.path.join(d, "none.txt")), \
                mock.patch("leadbot.sources.collect", return_value=cands), \
                mock.patch("leadbot.extract._call_claude", return_value=llm), \
                mock.patch("leadbot.http.polite_get", return_value=None):
            cwd = os.getcwd()
            os.chdir(d)
            try:
                return main.run(["--dry-run"])
            finally:
                os.chdir(cwd)

    def test_dry_run_end_to_end(self):
        llm = ('[{"item":1,"company_name":"Brew & Bloom","business_type":"cafe",'
               '"location":"Al Quoz, Dubai","free_zone":"","website":"","phone":"","email":"","confidence":0.9},'
               '{"item":2,"company_name":"Low Conf","confidence":0.2}]')
        rows = self._run(RSS, llm)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]), len(config.HEADERS))
        r = row(rows[0])
        self.assertEqual(r["COMPANY NAME"], "Brew & Bloom")
        self.assertEqual(r["CONTACT NUMBER"], "+971 4 321 7788")
        self.assertEqual(r["LOCATION"], "Al Quoz, Dubai")
        self.assertEqual(r["EMIRATE"], "Dubai")
        self.assertTrue(r["SOURCE"].startswith("Google News: Khaleej Times | https://"))
        self.assertEqual(r["FREE ZONE"], "")

    def test_free_zone_lead(self):
        llm = ('[{"item":1,"company_name":"Nordic Freight","business_type":"office",'
               '"location":"Almas Tower, Dubai","free_zone":"DMCC","website":"","phone":"","email":"",'
               '"confidence":0.85}]')
        rows = self._run(FZ_RSS, llm)
        self.assertEqual(len(rows), 1)
        r = row(rows[0])
        loc, src, fz = r["LOCATION"], r["SOURCE"], r["FREE ZONE"]
        self.assertEqual(fz, "DMCC Free Zone")
        self.assertIn("(DMCC Free Zone)", loc)
        self.assertTrue(src.startswith("Free Zone: DMCC via Google News: WAM | https://"))
        self.assertIn("verify: https://dmcc.ae/business-directory", src)


if __name__ == "__main__":
    unittest.main()
