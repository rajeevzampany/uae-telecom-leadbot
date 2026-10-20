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
        date_, name, phone, email, loc, site, src, fz = rows[0]
        self.assertEqual(name, "Brew & Bloom")
        self.assertEqual(phone, "+971 4 321 7788")
        self.assertEqual(loc, "Al Quoz, Dubai")
        self.assertTrue(src.startswith("Google News: Khaleej Times | https://"))
        self.assertEqual(fz, "")

    def test_free_zone_lead(self):
        llm = ('[{"item":1,"company_name":"Nordic Freight","business_type":"office",'
               '"location":"Almas Tower, Dubai","free_zone":"DMCC","website":"","phone":"","email":"",'
               '"confidence":0.85}]')
        rows = self._run(FZ_RSS, llm)
        self.assertEqual(len(rows), 1)
        _, name, _, _, loc, _, src, fz = rows[0]
        self.assertEqual(fz, "DMCC Free Zone")
        self.assertIn("(DMCC Free Zone)", loc)
        self.assertTrue(src.startswith("Free Zone: DMCC via Google News: WAM | https://"))
        self.assertIn("verify: https://dmcc.ae/business-directory", src)


if __name__ == "__main__":
    unittest.main()
