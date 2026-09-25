# Agent 10 — Tracker Keeper (`AI_News_SEO_Tracker` Google Sheet)

> Creates and maintains the one spreadsheet that holds all project data. The user uploads nothing.

## Core rules (short)
Real data only (`n/a` if unknown) · never delete rows (mark status instead) · dates `YYYY-MM-DD`.

---

## Create it (first run)

1. Search Google Drive for `AI_News_SEO_Tracker`. If it exists, open it.
2. Otherwise open `https://sheets.new`, rename to `AI_News_SEO_Tracker`, and create these tabs
   with the headers in row 1 (bold, frozen):

| Tab | Headers |
|---|---|
| **State** | (the PROJECT STATE block, pasted as text in A1) |
| **Keyword Map** | Keyword, Cluster, Volume, KD (Ahrefs), KD% (Semrush), Intent, SERP weakness, Content type, Opportunity, Priority, Target URL/slug, Status, Notes |
| **Content Calendar** | Date, Story/Topic, Primary source URL, Why it matters, Added value angle, Target keyword, Type, Priority, Status |
| **Published** | Date, Title, URL, Focus keyword, Cluster, Type, Word count, Indexed (Y/N), Position (latest), Clicks 28d, Last updated |
| **Rankings** | Date, Keyword, URL, Position before, Position after, Clicks before, Clicks after, Change made |
| **Tech Issues** | Date, Issue, URL(s), Source, Impact, Fix, Status |
| **Design Log** | Date, Change, Where, CSS/Setting, Result |
| **Backlinks** | Website, URL, DR, Traffic, Country, Language, Niche, Contact Email, Opportunity Type, Article Topic, Status, Published URL, Anchor Text, Date, Notes, Score |
| **Outreach** | Website, Contact Name, Contact Email, Language, Subject, Idea, Sent Date, Follow-up Day 3, Follow-up Day 7, Follow-up Day 14, Reply Status, Next Action |
| **Reports** | Date, Type (weekly/monthly), Link, Key numbers |

3. Formulas (type in row 2, then copy down to row 1000):
   - **Keyword Map** `I2` (Opportunity; SERP weakness column G holds 1.5 / 1 / 0.5):
     `=IF(OR(C2="",D2=""),"",ROUND(C2*(1-D2/100)*IF(F2="Navigational",0.3,1)*IF(G2="",1,G2),0))`
   - **Outreach** `H2`, `I2`, `J2`: `=IF(G2="","",G2+3)` · `=IF(G2="","",G2+7)` · `=IF(G2="","",G2+14)`
4. Share the sheet link with the user once.

If typing formulas fails, calculate the values yourself and type them.

## Maintenance

- Keyword Map: sort by Priority then Opportunity; mark `Published` with the URL when done.
- Published: refresh Position and Clicks weekly from Search Console.
- Never keep two rows for the same keyword or the same outreach site — update the existing row.
