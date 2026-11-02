# Public incident sources

Fetched and read on November 1, 2026, Pacific time. Every URL below returned HTTP 200 after redirects. This records that check, not a promise that a page will stay online. Raw HTML hashes and resolved URLs are in incidents/source_checks.json. Summaries are paraphrases. Input observations contain user impact, not retrospective cause statements.

Some reports cover several distinct events; each row names its own date and section. No repeated symptom variant counts as a new incident. The October 2018 page is an initial update, explicitly labeled as such.

| Incident | Public page | Section | Why it supports the case |
| --- | --- | --- | --- |
| PUB-01 | [gh-intro](https://github.blog/news-insights/company-news/introducing-the-github-availability-report/) | May 5 00:45 UTC | Several apps could not obtain installation tokens. |
| PUB-02 | [gh-intro](https://github.blog/news-insights/company-news/introducing-the-github-availability-report/) | May 22 16:41 UTC | Saved changes appeared late on the website and API. |
| PUB-03 | [gh-intro](https://github.blog/news-insights/company-news/introducing-the-github-availability-report/) | June 19 08:52 UTC | Only part of the experiment population saw errors. |
| PUB-04 | [gh-intro](https://github.blog/news-insights/company-news/introducing-the-github-availability-report/) | June 29 12:03 UTC | Repeated primary crashes occurred alongside CPU starvation. |
| PUB-05 | [gh-january-2021](https://github.blog/news-insights/company-news/github-availability-report-january-2021/) | January 28 04:21 UTC | Queued tasks failed or were delayed. |
| PUB-06 | [gh-march-2021](https://github.blog/news-insights/company-news/github-availability-report-march-2021/) | Follow up to March 1 09:59 UTC | Workflow searches returned incomplete results. |
| PUB-07 | [gh-march-2021](https://github.blog/news-insights/company-news/github-availability-report-march-2021/) | March 12 19:11 UTC | Query response times degraded across dependent services. |
| PUB-08 | [gh-march-2021](https://github.blog/news-insights/company-news/github-availability-report-march-2021/) | March 15 2021-03-15 20:38 UTC | Hosted builds could not obtain execution environments. |
| PUB-09 | [gh-april-2021](https://github.blog/news-insights/company-news/github-availability-report-april-2021/) | April 1 21:30 UTC | Both upload and download operations failed for beta users. |
| PUB-10 | [gh-april-2021](https://github.blog/news-insights/company-news/github-availability-report-april-2021/) | April 22 17:16 UTC | Creating repositories failed. |
| PUB-11 | [gh-may-2021](https://github.blog/news-insights/company-news/github-availability-report-may-2021/) | May 8 06:46 UTC | Package viewing and container transfers failed. |
| PUB-12 | [gh-may-2021](https://github.blog/news-insights/company-news/github-availability-report-may-2021/) | May 16 07:17 UTC | Some API operations and Git pushes and pulls failed. |
| PUB-13 | [gh-august-2021](https://github.blog/news-insights/company-news/github-availability-report-august-2021/) | August 10 15:16 UTC | Some write operations were unavailable. |
| PUB-14 | [gh-august-2021](https://github.blog/news-insights/company-news/github-availability-report-august-2021/) | August 10 19:57 UTC | New and in-progress workflow runs had high error rates. |
| PUB-15 | [gh-october-2021](https://github.blog/news-insights/company-news/github-availability-report-october-2021/) | October 8 17:16 UTC | Existing sessions continued with missing workspace details. |
| PUB-16 | [gh-november-2021](https://github.blog/news-insights/company-news/github-availability-report-november-2021/) | November 27 20:40 UTC | Many core services were affected while writes remained healthy. |
| PUB-17 | [gh-september-2020](https://github.blog/news-insights/company-news/github-availability-report-september-2020/) | September 17 15:50 UTC | Some Pages builds failed while their serving node stayed online. |
| PUB-18 | [gh-october-2020](https://github.blog/news-insights/company-news/github-availability-report-october-2020/) | October 9 21:30 UTC | Some background job writes failed without losing jobs. |
| PUB-19 | [gh-2018](https://github.blog/news-insights/company-news/october21-incident-report/) | At 10:52 pm Sunday UTC | Issue and pull request information looked stale; Git data remained available. |
| PUB-20 | [gh-ddos](https://github.blog/news-insights/company-news/ddos-incident-report/) | The incident | The site was unavailable for minutes before full recovery. |
| PUB-21 | [cloudflare-outage-on-july-17-2020](https://blog.cloudflare.com/cloudflare-outage-on-july-17-2020/) | Timeline | Traffic dropped sharply in affected locations. |
| PUB-22 | [cloudflare-outage-on-june-21-2022](https://blog.cloudflare.com/cloudflare-outage-on-june-21-2022/) | Introduction | Access failed depending on visitor location. |
| PUB-23 | [cloudflare-incident-on-june-20-2024](https://blog.cloudflare.com/cloudflare-incident-on-june-20-2024/) | Incident timeline and impact | Visitors saw generic error pages and slow first responses. |
| PUB-24 | [cloudflare-incident-on-october-30-2023](https://blog.cloudflare.com/cloudflare-incident-on-october-30-2023/) | What was impacted | Some users could not log in or publish updates. |
| PUB-25 | [post-mortem-on-cloudflare-control-plane-and-analytics-outage](https://blog.cloudflare.com/post-mortem-on-cloudflare-control-plane-and-analytics-outage/) | Informed Speculation On What Happened Next | Raw logs were unavailable while network traffic continued. |
| PUB-26 | [cloudflare-incident-on-august-21-2025](https://blog.cloudflare.com/cloudflare-incident-on-august-21-2025/) | On August 21, 2025 | Some connections to origins failed. |
| PUB-27 | [cloudflare-incident-on-february-6-2025](https://blog.cloudflare.com/cloudflare-incident-on-february-6-2025/) | What was impacted? | All R2 bucket and object operations failed during the main window. |
| PUB-28 | [cloudflare-service-outage-june-12-2025](https://blog.cloudflare.com/cloudflare-service-outage-june-12-2025/) | What was impacted? | Affected services failed globally without reported data loss. |
| PUB-29 | [cf-2019](https://blog.cloudflare.com/details-of-the-cloudflare-outage-on-july-2-2019/) | The events of July 2 | Visitors received error pages across the network. |
| PUB-30 | [aws-s3](https://aws.amazon.com/message/41926/) | We’d like to give you | S3 requests failed in Northern Virginia. |

Three attempted paths returned 404 and were omitted. The verified July 2019 full report was found under its current path. The missing November 2020 and March 2025 reports were not used.
