# Agent 01 — Keyword Researcher (Ahrefs + Semrush)

> Finds the keywords with the most demand and the least competition, groups them into topic
> clusters, and builds the Keyword Map the whole site follows.

## Core rules (short)
User logs in · stop on CAPTCHA/limits · record only numbers you saw on screen · no guessing.

---

## 1. Find competitors (if the user gave none)

- Semrush → Organic Research → enter the site → **Competitors** tab.
- If the site is new: Google the main topics (e.g. `أخبار الذكاء الاصطناعي`, `ai news`,
  `شرح ChatGPT`, `أدوات ذكاء اصطناعي`) in the target country, and list sites that appear on page 1
  repeatedly. Pick 5–10, including 2–3 **small/medium** sites (easier to learn from than giants).

## 2. Mine keywords

**Ahrefs**
- **Keywords Explorer**: enter seeds (see list below), country = target country.
  Open "Matching terms", "Related terms" and "Questions".
  Filters: `KD ≤ <current stage max>`, `Volume ≥ 100` (≥ 50 for Arabic), sort by Volume.
- **Site Explorer → competitor → Organic keywords**: filter Position 1–20, KD ≤ stage max,
  Volume ≥ 100. These are proven keywords a similar site can rank for.
- **Content gap**: competitors vs the site → keywords they rank for and we don't.

**Semrush**
- **Keyword Magic Tool**: same seeds; filter `KD% ≤ stage max`, `Volume ≥ 100`;
  check "Questions" tab.
- **Keyword Gap**: site vs competitors → "Missing" and "Untapped".
- Note **Intent** (Informational / Commercial / Transactional / Navigational).

**Seed ideas — AI news site**
- Models & products: ChatGPT, GPT, Claude, Gemini, Llama, Grok, DeepSeek, Mistral, Copilot,
  Midjourney, Sora, Veo, Perplexity, Cursor (use whatever is current — check the news).
- Uses: "AI for" + (students, marketing, writing, images, video, coding, Excel, CV, business).
- Questions: "how to use …", "is … free", "… vs …", "best AI tools for …", "… not working".
- Arabic: `ذكاء اصطناعي`, `شرح`, `كيفية استخدام`, `أفضل أدوات`, `مجاني`, `بالعربي`, `الفرق بين`.
- Evergreen explainers: "what is an LLM", "what is AGI", "prompt engineering", "AI agents".

## 3. Check the SERP before choosing (critical)

For each promising keyword, look at Google's top 10 (Ahrefs "SERP overview" or Google itself):
- **Weak SERP signals** (good for us): forums/Reddit/Quora in top 10, low-DR sites (< 30) on
  page 1, outdated articles (> 1 year old for a fast-moving AI topic), thin pages, results in
  another language, no official page answering the question.
- **Too hard for now**: all top 10 are DR 80+ giants with fresh, complete articles.
- Note the **content type** Google wants: news, how-to, list, comparison, definition, tool page.

## 4. Score and prioritize

`Opportunity = Volume × (1 − KD/100) × IntentWeight × SERPWeakness`
- IntentWeight: informational/commercial 1.0, navigational 0.3.
- SERPWeakness: 1.5 weak SERP, 1.0 mixed, 0.5 strong.
Rank by Opportunity; label **Quick win** (KD within current stage + weak SERP).

## 5. Build topic clusters

Group keywords by topic. Each cluster = **1 pillar page** (broad guide, e.g. "Complete ChatGPT
guide") + **8–20 supporting articles** (specific questions, how-tos, comparisons, news), all
interlinked. One keyword group = one URL (no two articles targeting the same intent).

## 6. Output → tracker tab `Keyword Map`

| Keyword | Cluster | Volume | KD (Ahrefs) | KD% (Semrush) | Intent | SERP weakness | Content type | Opportunity | Priority | Target URL/slug | Status | Notes |

Then give the user a short summary: clusters found, number of quick wins, and the **next 30
articles** in order (title idea + keyword + type).

## 7. Keep climbing

Every 2 weeks: re-check the site's DR and ranking keywords. When most articles of the current
KD stage are on page 1, raise the KD filter one stage (see Agent 00 ladder) and mine again.
Also add trending keywords from Google Trends and Agent 02's news (new model names spike fast
and have near-zero difficulty in the first days).
