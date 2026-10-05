# -*- coding: utf-8 -*-
"""Tests for the Yahoo Finance RSS news provider."""

import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

# Mock newspaper before search_service import (optional dependency)
if "newspaper" not in sys.modules:
    mock_np = MagicMock()
    mock_np.Article = MagicMock()
    mock_np.Config = MagicMock()
    sys.modules["newspaper"] = mock_np

from src.search_service import SearchService, YahooFinanceNewsProvider


class TestYahooFinanceNewsProvider(unittest.TestCase):
    @staticmethod
    def _response(text: str, *, status_code: int = 200, content_type: str = "application/rss+xml") -> MagicMock:
        resp = MagicMock()
        resp.status_code = status_code
        resp.text = text
        resp.headers = {"content-type": content_type}
        return resp

    @staticmethod
    def _rss(pub_date: str) -> str:
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>台積電先進製程需求升溫</title>
      <description><![CDATA[台積電受惠 AI 晶片需求，市場關注後續資本支出。]]></description>
      <link>https://tw.stock.yahoo.com/news/tsmc-ai-chip.html?.tsrc=rss</link>
      <pubDate>{pub_date}</pubDate>
    </item>
  </channel>
</rss>"""

    @patch("src.search_service.requests.get")
    def test_tw_symbol_uses_traditional_chinese_yahoo_rss(self, mock_get: MagicMock) -> None:
        pub_date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
        mock_get.return_value = self._response(self._rss(pub_date))

        provider = YahooFinanceNewsProvider()
        resp = provider.search("台積電 2330.TW 股票 最新消息", max_results=3, days=3)

        self.assertTrue(resp.success)
        self.assertEqual(resp.provider, "YahooFinanceRSS")
        self.assertEqual(len(resp.results), 1)
        self.assertEqual(resp.results[0].title, "台積電先進製程需求升溫")
        self.assertEqual(resp.results[0].source, "tw.stock.yahoo.com")
        self.assertEqual(resp.results[0].published_date, pub_date)
        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs["params"]["s"], "2330.TW")
        self.assertEqual(kwargs["params"]["region"], "TW")
        self.assertEqual(kwargs["params"]["lang"], "zh-Hant-TW")
        self.assertIn("Mozilla/5.0", kwargs["headers"]["User-Agent"])

    @patch("src.search_service.requests.get")
    def test_html_error_page_is_reported_as_failure(self, mock_get: MagicMock) -> None:
        mock_get.return_value = self._response(
            "<!doctype html><html><title>Yahoo</title></html>",
            content_type="text/html",
        )

        provider = YahooFinanceNewsProvider()
        resp = provider.search("台積電 2330.TW 股票 最新消息", max_results=3)

        self.assertFalse(resp.success)
        self.assertEqual(resp.results, [])
        self.assertIn("RSS", resp.error_message or "")

    @patch("src.search_service.requests.get")
    def test_search_service_can_return_2330_news_without_search_api_keys(self, mock_get: MagicMock) -> None:
        pub_date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
        mock_get.return_value = self._response(self._rss(pub_date))

        service = SearchService(
            yahoo_finance_news_enabled=True,
            searxng_public_instances_enabled=False,
            news_max_age_days=3,
            news_strategy_profile="short",
        )
        resp = service.search_stock_news("2330.TW", "台積電", max_results=2)

        self.assertTrue(resp.success)
        self.assertEqual(resp.provider, "YahooFinanceRSS")
        self.assertEqual(len(resp.results), 1)
        self.assertEqual(resp.results[0].relevance_category, "direct_company_news")

    def test_disabled_provider_does_not_make_search_service_available(self) -> None:
        service = SearchService(
            yahoo_finance_news_enabled=False,
            searxng_public_instances_enabled=False,
        )

        self.assertFalse(service.is_available)
