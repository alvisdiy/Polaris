# Data Dictionary

## Polaris — Scholarship Intelligence Platform

**Version:** 0.1
**Owner:** AlVis
**Status:** Draft

---

# Purpose

Dokumen ini mendefinisikan struktur data utama Polaris.

Tujuannya adalah memastikan seluruh data beasiswa memiliki format yang konsisten sehingga dapat digunakan oleh:

* Search Engine
* Matching Engine
* AI Recommendation
* AI Insight
* Future Analytics

---

# Data Design Principles

Polaris menggunakan beberapa prinsip utama:

* Data berasal dari sumber resmi.
* Tidak menyimpan data duplikat.
* Menggunakan tipe data yang konsisten.
* Tidak menggunakan kalimat bebas apabila dapat direpresentasikan sebagai Enum atau Boolean.
* Semua perubahan data harus memiliki tanggal pembaruan.

---

# Entity Relationship

```text
Scholarship
│
├── Provider
├── Country
├── University
├── Degree
├── Field of Study
├── Requirement
├── Funding
├── Benefits
├── Timeline
└── Official Source
```

---

# Main Entity : Scholarship

| Field                | Type      | Required | Example                     | Description                                          |
| -------------------- | --------- | -------- | --------------------------- | ---------------------------------------------------- |
| scholarship_id       | UUID      | ✅        | SCH-000001                  | Unique ID                                            |
| scholarship_name     | String    | ✅        | MEXT Scholarship            | Official scholarship name                            |
| provider_name        | String    | ✅        | Ministry of Education Japan | Organization                                         |
| scholarship_type     | Enum      | ✅        | Government                  | Government / University / Foundation / Company / NGO |
| country              | Enum      | ✅        | Japan                       | Destination country                                  |
| university           | String    | ❌        | University of Tokyo         | If applicable                                        |
| degree               | Enum      | ✅        | Master                      | Bachelor / Master / PhD / Exchange                   |
| funding_type         | Enum      | ✅        | Fully Funded                | Full / Partial / Tuition Only                        |
| field_of_study       | Array     | ✅        | Computer Science, AI        | Supported majors                                     |
| application_url      | URL       | ✅        | https://...                 | Official application page                            |
| official_source      | URL       | ✅        | https://...                 | Official information page                            |
| application_open     | Date      | ❌        | 2027-04-01                  | Registration opens                                   |
| application_deadline | Date      | ✅        | 2027-05-31                  | Deadline                                             |
| created_at           | Timestamp | ✅        | -                           | System generated                                     |
| updated_at           | Timestamp | ✅        | -                           | Last updated                                         |

---

# Core Entity : SourceRegistry

| Field | Type | Required | Example | Description |
|---|---|---|---|---|
| source_id | UUID | ✅ | - | Unique source identifier |
| source_name | String | ✅ | Study in Japan | Official source catalog name |
| country_id | UUID | ❌ | - | Reference to Country model |
| provider_id | UUID | ❌ | - | Reference to Provider model |
| official_url | URL | ✅ | https://www.studyinjapan.go.jp/ | Homepage URL of official source |
| crawl_entry_url | URL | ✅ | https://... | Specific URL crawler starts at |
| crawl_method | String | ✅ | Playwright | API / Playwright / Crawl4AI |
| connector_name | String | ❌ | mext_connector | Custom connector module name |
| crawl_frequency | String | ✅ | Monthly | Daily / Weekly / Monthly / Manual |
| priority | Integer | ✅ | 1 | Crawl queue priority (1-5) |
| language | String | ❌ | English | Primary language of content |
| timezone | String | ❌ | Asia/Tokyo | Timezone of site publication |
| robots_allowed | Boolean | ✅ | true | Flag to respect robots.txt |
| requires_login | Boolean | ✅ | false | Flag if crawling requires auth |
| status | String | ✅ | Active | Active / Maintenance / Deprecated / Blocked |
| last_crawled_at | Timestamp | ❌ | - | Timestamp of last crawler run |
| last_verified_at| Timestamp | ❌ | - | Timestamp of last human audit |
| created_at | Timestamp | ✅ | - | Date added to registry |
| updated_at | Timestamp | ✅ | - | Date metadata was last modified |

---

# Core Entity : RawDocument

| Field | Type | Required | Example | Description |
|---|---|---|---|---|
| document_id | UUID | ✅ | - | Unique ID |
| source_id | UUID | ✅ | - | Reference to SourceRegistry |
| source_url | URL | ✅ | https://... | Actual URL fetched |
| content_type | String | ✅ | html | html / pdf / json / markdown |
| raw_content | Text | ✅ | - | Raw downloaded content |
| checksum | String | ✅ | - | SHA256 of raw_content |
| status_code | Integer | ❌ | 200 | HTTP status |
| fetched_at | Timestamp | ✅ | - | Date fetched |
| etag | String | ❌ | - | HTTP ETag header |
| last_modified | String | ❌ | - | HTTP Last-Modified header |
| crawl_duration_ms | Integer | ❌ | - | Crawl duration in ms |
| processing_status| String | ✅ | pending | pending / processing / completed / failed |
| created_at | Timestamp | ✅ | - | Date created |
| updated_at | Timestamp | ✅ | - | Date updated |

---

# Eligibility Requirements

| Field                 | Type    | Required | Example      |
| --------------------- | ------- | -------- | ------------ |
| minimum_gpa           | Float   | ❌        | 3.25         |
| ielts_required        | Boolean | ✅        | true         |
| minimum_ielts         | Float   | ❌        | 6.5          |
| toefl_required        | Boolean | ✅        | false        |
| minimum_toefl         | Integer | ❌        | 550          |
| gre_required          | Boolean | ✅        | false        |
| age_limit             | Integer | ❌        | 35           |
| work_experience       | Enum    | ❌        | Optional     |
| research_experience   | Enum    | ❌        | Preferred    |
| publication           | Enum    | ❌        | Not Required |
| recommendation_letter | Boolean | ✅        | true         |
| motivation_letter     | Boolean | ✅        | true         |
| cv_required           | Boolean | ✅        | true         |
| passport_required     | Boolean | ✅        | true         |

---

# Enum Standard

## Scholarship Type

* Government
* University
* Foundation
* NGO
* Company

---

## Degree

* Bachelor
* Master
* PhD
* Exchange
* Short Course

---

## Funding Type

* Fully Funded
* Partial Funded
* Tuition Only

---

## Requirement Level

Digunakan untuk:

* Work Experience
* Research Experience
* Publication

Value:

* Required
* Preferred
* Optional
* Not Required

---

# Benefits

| Field             | Type    |
| ----------------- | ------- |
| tuition_fee       | Boolean |
| monthly_allowance | Boolean |
| accommodation     | Boolean |
| health_insurance  | Boolean |
| travel_ticket     | Boolean |
| research_grant    | Boolean |

---

# Timeline

| Field                | Type |
| -------------------- | ---- |
| application_open     | Date |
| application_deadline | Date |
| interview_date       | Date |
| result_date          | Date |
| study_start          | Date |

---

# AI Matching Fields

Field berikut digunakan oleh Matching Engine.

| Field               | Weight |
| ------------------- | -----: |
| Country             |     20 |
| Degree              |     20 |
| Field of Study      |     20 |
| GPA                 |     15 |
| Language            |     10 |
| Funding Preference  |      5 |
| Research Experience |      5 |
| Work Experience     |      5 |

**Catatan:** Bobot ini adalah versi awal dan akan divalidasi menggunakan data pengguna. Jangan menganggapnya final.

---

# AI Explainable Fields

AI hanya boleh menjelaskan berdasarkan data berikut:

* Eligibility
* Requirements
* Benefits
* Timeline
* Official Information

AI **tidak boleh mengarang** syarat yang tidak ada pada sumber resmi.

---

# Data Validation Rules

* GPA menggunakan skala 0.00–4.00.
* IELTS menggunakan skala 0.0–9.0.
* TOEFL menggunakan skor resmi.
* Deadline menggunakan format ISO (YYYY-MM-DD).
* Semua URL harus berasal dari website resmi.
* Tidak boleh ada dua scholarship dengan ID yang sama.
* Semua perubahan data harus memperbarui `updated_at`.

---

# Source Priority

Urutan sumber data:

Priority 1

* Government Website

Priority 2

* Official University Website

Priority 3

* Official Scholarship Foundation

Priority 4

* International Organization

Priority 5

* Trusted Educational Partner

Blog pribadi, forum, dan media sosial **bukan** sumber utama.

---

# Future Fields (Not Used in MVP)

* Acceptance Rate
* Number of Awardees
* Alumni Testimonials
* Application Difficulty
* AI Generated Insights
* User Reviews
* Historical Deadline Changes
* Country Cost of Living
* Visa Information

---

# Next Action

* [ ] Finalisasi seluruh field.
* [ ] Normalisasi enum.
* [ ] Mulai membangun Scholarship Knowledge Base.
* [ ] Tentukan sumber data resmi pertama.
* [ ] Implementasikan database berdasarkan Data Dictionary ini.
