import asyncio
import json
import re
import unittest
import xml.etree.ElementTree as ET

import httpx

import app as app_module


class SeoSurfaceTests(unittest.TestCase):
    def run_async(self, coroutine):
        return asyncio.run(coroutine)

    async def fetch(self, path):
        transport = httpx.ASGITransport(app=app_module.app)
        async with httpx.AsyncClient(transport=transport, base_url="https://sunxiris.top") as client:
            return await client.get(path, headers={"User-Agent": "Googlebot"})

    def test_public_home_has_search_metadata_and_valid_json_ld(self):
        response = self.run_async(self.fetch("/"))
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("许墨 Lucien｜沉浸式 AI 陪伴与成长应用", html)
        self.assertIn('<link rel="canonical" href="https://sunxiris.top/">', html)
        self.assertNotIn('content="noindex', html)
        match = re.search(r'<script type="application/ld\+json">\s*(.*?)\s*</script>', html, re.S)
        self.assertIsNotNone(match)
        self.assertEqual(json.loads(match.group(1))["@type"], "WebApplication")

    def test_robots_and_sitemap_are_public_and_valid(self):
        robots = self.run_async(self.fetch("/robots.txt"))
        self.assertEqual(robots.status_code, 200)
        self.assertIn("Sitemap: https://sunxiris.top/sitemap.xml", robots.text)
        self.assertIn("Disallow: /api/", robots.text)

        sitemap = self.run_async(self.fetch("/sitemap.xml"))
        self.assertEqual(sitemap.status_code, 200)
        root = ET.fromstring(sitemap.text)
        locations = [node.text for node in root.findall("{http://www.sitemaps.org/schemas/sitemap/0.9}url/{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
        self.assertEqual(locations, ["https://sunxiris.top/", "https://sunxiris.top/tutorial.html"])

    def test_tutorial_is_public_but_private_surfaces_are_noindex(self):
        tutorial = self.run_async(self.fetch("/tutorial.html"))
        self.assertEqual(tutorial.status_code, 200)
        self.assertIn('content="index, follow', tutorial.text)

        account = self.run_async(self.fetch("/account.html"))
        self.assertEqual(account.status_code, 200)
        self.assertEqual(account.headers.get("x-robots-tag"), "noindex, nofollow")

        api = self.run_async(self.fetch("/api/status"))
        self.assertEqual(api.status_code, 401)
        self.assertEqual(api.headers.get("x-robots-tag"), "noindex, nofollow")


if __name__ == "__main__":
    unittest.main()
