# Trailforks API Application Guide & Draft

This document contains everything needed to apply for API access with Trailforks (Outside Inc.), including submission channels, application questions, and a copy-paste ready application draft.

---

## 1. Where and Who to Send To

- **Primary Web Submission Form**:
  - URL: [https://www.trailforks.com/about/api/](https://www.trailforks.com/about/api/)
  - Select *Request API Access* or fill out the partner intake form.
- **Direct Developer / Partner Contacts**:
  - API Team Inbox: `api@trailforks.com`
  - Brent Hillier (Trailforks Director / Pinkbike Lead): `brent@pinkbike.com`
  - General Support / Inquiries: `support@trailforks.com`
  - Outside Inc. Developer Relations: `developers@outsideinc.com`

---

## 2. Key Information Required

| Field | Value |
|---|---|
| **Application Name** | Loam (Trail Route Builder) |
| **Developer Name** | Justin Pfister |
| **Email** | `jjrpfister@gmail.com` |
| **Website / Repository** | [https://github.com/JJRPF/loam](https://github.com/JJRPF/loam) |
| **App Type** | Web App / Progressive Web App (PWA) |
| **Intended Sports** | Mountain Biking (MTB) & Trail Running |
| **Primary Region** | New Hampshire & New England, USA |
| **Commercial Status** | Non-commercial, independent open-source trail project |
| **Attribution Guarantee** | Full "© Trailforks" credit displayed on all screens and metadata popups with direct links to Trailforks trail detail pages |

---

## 3. Copy-Paste Ready Email / Application Draft

### Subject:
`Trailforks API Access Application - Loam Trail Route Builder (Non-Commercial)`

### Body:

Hello Trailforks API Team,

My name is Justin Pfister, and I am the creator of **Loam**, a focused, non-commercial trail route planning web application designed for mountain bikers and trail runners in New England and New Hampshire.

I would like to apply for API access to integrate Trailforks trail condition reports, trail metadata, and trailhead information into Loam.

### 1. About the Application
- **Name**: Loam (Trail Route Builder)
- **Developer**: Justin Pfister (`jjrpfister@gmail.com`)
- **Repository / Project**: https://github.com/JJRPF/loam
- **Primary Audience**: Mountain bikers and trail runners exploring trail networks in New Hampshire (e.g., Bear Brook State Park, Fort Rock, Franklin Falls, Green Woodlands).

### 2. What We Use the API For
Loam uses OpenStreetMap and local routing algorithms for graph routing, and we want to bring in Trailforks as our authoritative source for trail health and stewardship:
- **Trail Condition Reports**: Checking whether a trail is Open, Closed, Muddy, or Icy so riders avoid sensitive, wet, or closed trails during mud season or trail work days.
- **Trailhead & Parking Information**: Displaying designated parking coordinates and trailhead statuses so riders park legally.
- **Difficulty & Rating Metadata**: Displaying official trail difficulty (green, blue, black, double black) to assist riders in picking routes suited to their skill level.

### 3. Attribution, Terms, and Privacy Commitments
- **Clear Attribution**: We display **"© Trailforks"** prominently alongside any condition report or trail rating, accompanied by direct deep-links to the corresponding Trailforks trail page.
- **No Redistribution**: We will not redistribute, re-license, bulk-export, or republish Trailforks GIS geometry or raw data.
- **Aggressive Caching**: To minimize load on Trailforks servers, all API responses are cached locally (1–6 hour TTL for trail status, 24+ hour TTL for static trail metadata) with strict rate-limiting.
- **Non-Commercial**: Loam is completely free and non-commercial.

### 4. Technical Details
- **Architecture**: FastAPI (Python) backend + React / TypeScript / MapLibre frontend.
- **Estimated Call Volume**: Initial low-volume usage (< 500 requests/day) localized to New Hampshire trail networks.
- **Authentication**: Server-to-server API key / OAuth token stored encrypted at rest.

Please let me know if you need any additional details, mockups, or architectural documentation to evaluate our application.

Thank you for everything Trailforks does for the trail advocacy community.

Best regards,

**Justin Pfister**  
Email: `jjrpfister@gmail.com`  
Project: Loam Trail Route Builder  
GitHub: [https://github.com/JJRPF/loam](https://github.com/JJRPF/loam)
