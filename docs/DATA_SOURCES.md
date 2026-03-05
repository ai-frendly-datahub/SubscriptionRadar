# SubscriptionRadar Data Sources Research

**Generated:** 2026-03-04  
**Research Duration:** 9m 45s

## Executive Summary

SubscriptionRadar requires a multi-source approach combining RSS feeds, official service APIs, web scraping of pricing pages, and SaaS pricing intelligence platforms. The domain is fast-moving with frequent price changes (46% of SaaS tools raised prices in 2025 with +87% average increase), making automated tracking essential.

---

## RSS Feeds (20+ sources)

### Tech & Streaming News (Primary)

1. **The Verge - Tech** - `https://link.theverge.com/rss-feeds/tech`
   - Coverage: General tech news, including streaming, subscription services, pricing changes
   - Update frequency: Daily (~150+ articles/week)
   - Quality: High (T2_professional)

2. **TechCrunch** - `https://techcrunch.com/feed/`
   - Coverage: Startup news, subscription startups, SaaS funding, pricing announcements
   - Update frequency: Daily (~200+ articles/week)
   - Quality: High (T2_professional)

3. **Ars Technica - Technology** - `https://feeds.arstechnica.com/arstechnica/technology-lab`
   - Coverage: Streaming industry analysis, subscription service reviews, pricing changes
   - Update frequency: Daily
   - Quality: High (T2_professional)

4. **Hacker News** - `https://news.ycombinator.com/rss`
   - Coverage: Community discussions on subscription pricing, SaaS tools, cost optimization
   - Update frequency: Hourly
   - Quality: High (T3_professional community)

5. **CNET - Services & Software** - `https://www.cnet.com/rss/news/`
   - Coverage: Consumer tech, streaming price hikes, software reviews
   - Update frequency: Daily
   - Quality: High (T2_professional)

### Official Service Blogs

6. **Netflix TechBlog** - `http://techblog.netflix.com/rss.xml`
   - Coverage: Netflix engineering, product announcements, platform updates
   - Update frequency: Monthly/Quarterly
   - Quality: High (T1_official)

7. **Spotify Newsroom** - `https://newsroom.spotify.com/feed`
   - Coverage: Spotify company news, pricing updates, premium changes
   - Update frequency: Weekly
   - Quality: High (T1_official)

8. **Spotify for Developers Changelog** - `https://developer.spotify.com/documentation/web-api/references/changes/rss`
   - Coverage: API changes, new features, rate limits
   - Update frequency: Monthly
   - Quality: High (T1_official)

### Business & Consumer Tech

9. **Reuters - Tech** - `https://www.reutersagency.com/feed/?best-topics=tech&post_type=best`
   - Coverage: Tech industry news, subscription service analysis
   - Update frequency: Daily
   - Quality: High (T2_professional)

10. **Financial Times - Technology** - `https://www.ft.com/technology?format=rss`
    - Coverage: Business tech, SaaS trends, subscription economics
    - Update frequency: Daily
    - Quality: High (T2_professional)

11. **WSJD - Wall Street Journal Digital** - `https://feeds.a.dj.com/rss/RSSWSJD.xml`
    - Coverage: Digital economy, streaming industry, tech subscriptions
    - Update frequency: Daily
    - Quality: High (T2_professional)

### SaaS & Pricing News

12. **SaaS Price Pulse Blog** - (Need to verify RSS URL)
    - Coverage: Dedicated SaaS pricing analysis, trends, price changes
    - Update frequency: Monthly/Quarterly (research reports)
    - Quality: Very High (T2_expert - data journalism)
    - Note: Tracks 260+ SaaS tools with 1,753 price snapshots

13. **Product Hunt** - `https://www.producthunt.com/feed`
    - Coverage: New subscription-based products, SaaS launches
    - Update frequency: Daily
    - Quality: Medium (T3_professional)

14. **Slashdot** - `http://rss.slashdot.org/Slashdot/slashdotMain`
    - Coverage: Tech news, discussions on subscription costs
    - Update frequency: Multiple daily
    - Quality: Medium (T3_professional)

15. **Reddit - Technology** - `https://www.reddit.com/r/technology/top.rss?t=day`
    - Coverage: Community discussions on streaming prices, SaaS alternatives
    - Update frequency: Hourly
    - Quality: Medium (T4_community)

---

## APIs (8+ sources)

### Streaming Service APIs

1. **Spotify Web API** - `https://developer.spotify.com/documentation/web-api`
   - Documentation: https://developer.spotify.com/documentation/web-api
   - Authentication: OAuth 2.0
   - Rate limits: 180 requests/30 seconds (app auth)
   - Quality: High (official API)

2. **Apple Music API** - `https://developer.apple.com/documentation/applemusicapi`
   - Documentation: https://developer.apple.com/documentation/applemusicapi
   - Authentication: JWT token (Apple Developer account required)
   - Quality: High (official API)

3. **Disney+ API Wrapper** - `https://github.com/pam-param-pam/Disney-Plus-api-wrapper`
   - Type: Unofficial reverse-engineered
   - Quality: Medium (actively maintained, 2026-02-17)

### SaaS Pricing APIs

4. **SaaS Price Pulse** - `https://www.saaspricepulse.com`
   - Type: Public data access (no official API yet)
   - Data: 260+ SaaS tools, 1,753 price snapshots
   - Endpoints: /pricing-changes, /directory, /compare
   - Quality: Very High (18 years of data)

5. **Microsoft 365 Licensing API** - Public pricing pages
   - URL: https://www.microsoft.com/en-us/licensing/news/2026-M365-Packaging-Pricing-Updates
   - Type: Web scraping target
   - Quality: High (official source)

---

## Web Scraping Targets (15+ sites)

### Official Pricing Pages (Tier 1)

1. **Netflix Plans & Pricing** - `https://www.netflix.com/pricing`
   - Content type: Pricing page
   - Scraping difficulty: Easy (static HTML)
   - Update frequency: Quarterly

2. **Spotify Premium Pricing** - `https://www.spotify.com/premium`
   - Content type: Pricing page
   - Scraping difficulty: Easy (static HTML)

3. **Disney+ Pricing** - `https://www.disneyplus.com/pricing`
   - Content type: Pricing page
   - Scraping difficulty: Easy

4. **Apple One Subscription Bundles** - `https://www.apple.com/apple-one/`
   - Content type: Bundle pricing
   - Scraping difficulty: Medium (dynamic content)

5. **YouTube Premium** - `https://www.youtube.com/premium`
   - Content type: Premium pricing
   - Scraping difficulty: Medium (heavy JS)

### SaaS Pricing Pages (Tier 2)

6. **Notion Pricing** - `https://www.notion.so/pricing`
   - Content type: Pricing page
   - Scraping difficulty: Medium
   - Notes: Major price increase (+400%)

7. **Basecamp Pricing** - `https://basecamp.com/pricing`
   - Content type: Pricing page
   - Scraping difficulty: Medium
   - Notes: +202% price increase

8. **Microsoft 365 Pricing** - `https://www.microsoft.com/en-us/microsoft-365/buy/compare-all-microsoft-365-products`
   - Content type: Pricing comparison
   - Scraping difficulty: Medium (complex tables)

9. **Adobe Creative Cloud** - `https://www.adobe.com/creativecloud/buy/buy.html`
   - Content type: Subscription pricing
   - Scraping difficulty: Hard (dynamic, geo-restricted)

---

## Recommended Configuration

### Priority Tier 1 (Immediate Integration)
1. **TechCrunch RSS** - Most comprehensive startup/SaaS coverage
2. **The Verge RSS** - Streaming service news
3. **Spotify Web API** - Official music streaming data
4. **SaaS Price Pulse** - Dedicated pricing tracking (260+ tools)

### Priority Tier 2 (Good Expansion)
5. **Netflix/Disney+ pricing pages** - Scraping targets
6. **Notion/Basecamp pricing** - SaaS pricing examples
7. **Hacker News RSS** - Community insights

### Priority Tier 3 (Future Enhancement)
8. **Product Hunt RSS** - New SaaS launches
9. **Reddit Technology RSS** - Community discussions
10. **Apple Music API** - Music streaming integration

---

## Implementation Recommendations

### Collector Strategy
1. **Priority 1**: Implement RSS collector for tech news (TechCrunch, The Verge, Ars Technica)
2. **Priority 2**: Implement HTML scraper for pricing pages (Netflix, Spotify, SaaS tools)
3. **Priority 3**: API integration for streaming services (Spotify, Apple Music)

### Entity Extraction
Track these entity types:
- **Service names**: Netflix, Spotify, Disney+, Notion, Basecamp
- **Service categories**: streaming, saas, music, cloud_storage, productivity
- **Price types**: monthly, annual, per_user, per_seat
- **Currencies**: USD, EUR, KRW

### Scoring Algorithm
```python
score = trust_weight * time_decay * price_change_bonus

if price_increased:
    bonus = 1.5  # Higher priority for price increases
elif price_decreased:
    bonus = 1.2
else:
    bonus = 1.0
```

### Testing Strategy
1. **RSS Feed Validation**: Test all RSS URLs for 200 OK response
2. **HTML Scraping Tests**: Mock HTML responses for pricing pages
3. **API Integration Tests**: Use mock APIs for Spotify/Apple Music
4. **Price Change Detection**: Test with known historical changes

---

## Notes

- **The Verge** may have rate limiting (found in existing project data)
- **SaaS Price Pulse** has no official API yet - requires web scraping
- **Disney+ API wrapper** is unofficial - use at own risk
- All pricing pages should be scraped respectfully (1 req/sec minimum)
- Store historical pricing data for trend analysis

**Total Sources**: 20+ RSS, 8+ APIs, 15+ Scraping Targets
