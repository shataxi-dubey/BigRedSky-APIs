# Product Requirements Document
## Applicant Tracking System (ATS) — API Suite
**Version 1.0 | April 2026**

---

## Table of Contents

1. [Overview](#1-overview)
2. [Scope & Goals](#2-scope--goals)
3. [Architecture Principles](#3-architecture-principles)
4. [Authentication & Authorisation](#4-authentication--authorisation)
5. [Feature 1 — Resume Parser](#5-feature-1--resume-parser)
6. [Feature 2 — Job Description Creator](#6-feature-2--job-description-creator)
7. [Feature 3 — Resume Summary](#7-feature-3--resume-summary)
8. [Feature 4 — Contact Draft](#8-feature-4--contact-draft)
9. [Feature 5 — AI Ranking](#9-feature-5--ai-ranking)
10. [Non-Functional Requirements](#10-non-functional-requirements)
11. [Error Handling](#11-error-handling)
12. [Key Dependencies](#12-key-dependencies)
13. [Open Questions](#13-open-questions)
14. [Revision History](#14-revision-history)

---

## 1. Overview

This document defines the product requirements for the backend API suite of an Applicant Tracking System (ATS). The system comprises five core features designed to automate and accelerate the recruiting lifecycle:

- **Resume Parser** — Extract structured data from candidate resumes
- **JD Creator** — Generate and iteratively refine job descriptions
- **Resume Summary** — Produce JD-aware candidate summaries
- **Contact Draft** — Generate personalised outreach emails
- **AI Ranking** — Score and rank candidates against a job role

All APIs must be asynchronous, stateless, and secured via JWT or OAuth 2.0. Privacy-by-design is a cross-cutting concern — Personally Identifiable Information (PII) must be scrubbed before any LLM call.

---

## 2. Scope & Goals

### 2.1 In Scope

- REST API design and specifications for all five ATS features
- Authentication and authorisation layer (JWT / OAuth 2.0)
- PII scrubbing pipeline using Nvidia GLiNER
- Asynchronous job queue for background processing
- Redis caching for resume summaries
- Vector embedding pipeline (sparse + dense) for resume chunking
- Scoring criteria generation and persistence for AI Ranking

### 2.2 Out of Scope

- Front-end / UI implementation
- Candidate-facing application portals
- Video interviews, scheduling calendars, or HRIS integrations
- Custom LLM fine-tuning

---

## 3. Architecture Principles

- **Async-first**: Every long-running operation runs behind a job queue (e.g., Celery + Redis / BullMQ). HTTP responses return immediately with a `job_id`.
- **PII-safe by default**: All resume text is PII-scrubbed with Nvidia GLiNER before being sent to any LLM. Raw PII is stored only in designated, access-controlled fields.
- **Stateless APIs**: No server-side session state. All context required for a request is supplied in the request payload or retrieved from the database/cache.
- **Observability**: Every background job emits structured logs. A status endpoint is available per `job_id`.
- **Security**: All endpoints require a valid JWT Bearer token or OAuth 2.0 access token. Role-based access control (RBAC) governs recruiter vs. admin permissions.

---

## 4. Authentication & Authorisation

All API endpoints are protected. Clients must supply a valid token in the `Authorization` header.

| Property | Detail |
|---|---|
| Scheme | `Bearer <JWT>` or OAuth 2.0 access token |
| Token Issuer | Internal auth service or external IdP (e.g., Auth0, Okta) |
| Access Token Expiry | 15 minutes |
| Refresh Token Expiry | 7 days |
| RBAC Roles | `recruiter`, `hiring_manager`, `admin` |
| 401 | Missing or expired token |
| 403 | Insufficient role |

---

## 5. Feature 1 — Resume Parser

### 5.1 Purpose

Automatically populate an application form by extracting structured data from a candidate's resume (PDF or DOCX). PII is scrubbed before LLM processing and returned in separate, controlled fields. Simultaneously, the resume is enqueued for vector embedding to support semantic search.

### 5.2 API Endpoints

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/api/v1/resume/parse` | Parse resume & return structured form data |
| `GET` | `/api/v1/resume/chunk/{candidate_id}/status` | Poll the status of a background chunking job |

### 5.3 Request — `POST /api/v1/resume/parse`

**Content-Type:** `multipart/form-data`

| Field | Description |
|---|---|
| `resume` | (file, required) PDF or DOCX, max 10 MB |
| `candidate_id` | (string, required) Unique identifier for the candidate |
| `form_fields` | (JSON array, required) Field names to populate, e.g. `["education", "skills", "certifications"]` |

### 5.4 Response — `202 Accepted`

```json
{
  "job_id": "<uuid>",
  "chunk_job_id": "<uuid>",
  "status": "queued",
  "message": "Resume received. Parse job queued; chunking started in background."
}
```

### 5.5 PII Scrubbing Pipeline

Before the resume text reaches the LLM, the following steps are applied in order:

1. Extract raw text from the uploaded file (PDF / DOCX).
2. Run **Nvidia GLiNER** to identify and extract PII entities: name, gender, location, email, phone, date of birth.
3. Store the extracted PII values in dedicated, access-controlled fields — these are never logged or forwarded to the LLM.
4. Replace each PII token in the resume text with a neutral placeholder (e.g., `[NAME]`, `[EMAIL]`, `[LOCATION]`).
5. Pass the redacted resume text to the LLM with the `form_fields` extraction prompt.

### 5.6 Background Chunking Pipeline

Resume chunking is triggered immediately upon file receipt but does **not** block the parse response.

1. The resume file and `candidate_id` are pushed onto a dedicated chunking queue.
2. A worker dequeues the job and uses an LLM to segment the resume into predefined sections: Summary, Education, Work Experience, Projects, Skills, Certifications, Achievements.
3. Each chunk is embedded with both **sparse** (BM25 / TF-IDF) and **dense** (sentence-transformer) encodings.
4. Chunks are persisted to the vector store with the following metadata:

| Metadata Field | Description |
|---|---|
| `candidate_id` | Owner of the resume |
| `section_name` | e.g., `work_experience`, `skills` |
| `skills` | Skills mentioned in the chunk |
| `current_role` | Most recent job title |
| `all_roles` | All roles listed in the resume |
| `years_of_experience` | Derived total years |
| `education` | Highest / all education entries |
| `certifications` | Certifications in the chunk |
| `chunk_type` | `sparse` or `dense` |

5. A status endpoint (`GET /api/v1/resume/chunk/{candidate_id}/status`) exposes chunk job progress.

---

## 6. Feature 2 — Job Description Creator

### 6.1 Purpose

Generate and iteratively refine a job description (JD) from raw text, a template, or structured job details. Supports three editing modes: direct user edits (handled client-side), LLM-powered rephrasing of selected text, and instruction-driven refinement (capped at **5 refinements per session**).

### 6.2 API Endpoints

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/api/v1/jd/generate` | Generate a JD from raw input, template, or structured details |
| `POST` | `/api/v1/jd/rephrase` | Rephrase a user-selected passage within the JD |
| `POST` | `/api/v1/jd/refine` | Refine the full JD via a natural-language instruction |
| `GET` | `/api/v1/jd/{jd_id}` | Fetch a finalised JD by ID |

### 6.3 Generate — `POST /api/v1/jd/generate`

**Request Body (JSON)**

| Field | Description |
|---|---|
| `input_type` | (required) `"raw_text"` \| `"template"` \| `"details"` |
| `raw_text` | (string) Free-form text. Required if `input_type = raw_text`. |
| `template` | (string) Pre-defined template with placeholders. Required if `input_type = template`. |
| `details` | (object) `{ job_title, department, location, employment_type, responsibilities[], required_skills[], preferred_skills[], compensation_range }`. Required if `input_type = details`. |

**Response — `200 OK`**

```json
{
  "jd_id": "<uuid>",
  "content": "## Software Engineer ...",
  "session_refinements_remaining": 5
}
```

### 6.4 Rephrase — `POST /api/v1/jd/rephrase`

**Request Body (JSON)**

| Field | Description |
|---|---|
| `jd_id` | (string, required) The JD this selection belongs to |
| `selected_text` | (string, required) The exact passage the user highlighted |
| `tone` | (string, optional) e.g., `"formal"`, `"inclusive"`, `"concise"` |

**Response — `200 OK`**

```json
{
  "original_text": "...",
  "rephrased_text": "..."
}
```

### 6.5 Refine — `POST /api/v1/jd/refine`

**Request Body (JSON)**

| Field | Description |
|---|---|
| `jd_id` | (string, required) The JD being refined |
| `session_id` | (string, required) Used to enforce the 5-refinement cap |
| `instruction` | (string, required) Natural-language refinement instruction |

**Response — `200 OK`**

```json
{
  "jd_id": "<uuid>",
  "content": "## Software Engineer ...",
  "session_refinements_remaining": 4
}
```

> When `session_refinements_remaining` reaches `0`, subsequent refine calls return **HTTP 429** with error code `REFINEMENT_LIMIT_REACHED`.

---

## 7. Feature 3 — Resume Summary

### 7.1 Purpose

Generate a concise, JD-aware professional profile for a candidate highlighting their strengths relative to the role, skill gaps, experience relevance, and any red flags. PII is scrubbed before the LLM call. Results are cached in Redis to avoid redundant LLM calls.

### 7.2 API Endpoints

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/api/v1/resume/summary` | Generate or retrieve a cached resume summary |
| `DELETE` | `/api/v1/resume/summary/{candidate_id}/{jd_id}` | Invalidate cache for a candidate + JD pair |

### 7.3 Request — `POST /api/v1/resume/summary`

| Field | Description |
|---|---|
| `candidate_id` | (string, required) |
| `jd_id` | (string, required) The finalised JD to compare against |
| `force_refresh` | (boolean, optional, default `false`) Bypass cache and regenerate |

Using candidate id we can get the chunks of the resume from the Vector DB.

### 7.4 Response — `200 OK`

```json
{
  "candidate_id": "<uuid>",
  "jd_id": "<uuid>",
  "cache_hit": true,
  "generated_at": "2026-04-27T10:00:00Z",
  "summary": {
    "professional_profile": "...",
    "strengths": ["..."],
    "skill_gaps": ["..."],
    "experience_relevance": "...",
    "red_flags": ["..."],
    "notable_items": ["..."]
  }
}
```

### 7.5 Caching Strategy

| Property | Detail |
|---|---|
| Cache key | `summary:{candidate_id}:{jd_id}` |
| TTL | 24 hours (configurable via `SUMMARY_CACHE_TTL` env var) |
| Cache hit | Return cached result immediately; no LLM call |
| Cache miss | Scrub PII → call LLM → store in Redis → return result |
| Invalidation | Explicit `DELETE` endpoint, or automatically when the resume or JD is updated |

---

## 8. Feature 4 — Contact Draft

### 8.1 Purpose

Generate personalised outreach emails to candidates, either individually or in bulk. The LLM produces a Markdown-formatted email with appropriate merge fields (e.g., `[Name]`, `[Job Title]`, `[Interview Stage]`) from a user-supplied template or raw text.

### 8.2 API Endpoints

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/api/v1/contact/draft` | Draft an email for one or more candidates |
| `GET` | `/api/v1/contact/draft/{job_id}` | Poll bulk draft job status and results |

### 8.3 Request — `POST /api/v1/contact/draft`

| Field | Description |
|---|---|
| `input_type` | (required) `"template"` \| `"raw_text"` |
| `template` | (string) Pre-built email template. Required if `input_type = template`. |
| `raw_text` | (string) Free-form description of the email. Required if `input_type = raw_text`. |
| `send_mode` | (required) `"individual"` \| `"bulk"` |
| `custom_merge_fields` | (object, optional) Additional merge fields beyond the standard set |

### 8.4 Responses

**Individual — `200 OK`**

```json
{
  "candidate_id": "<uuid>",
  "subject": "Interview Invitation — Software Engineer",
  "body": "Hi [Name], ...",
  "merge_fields_used": ["[Name]", "[Job Title]", "[Interview Stage]"]
}
```

**Bulk — `202 Accepted`**

```json
{
  "job_id": "<uuid>",
  "status": "queued",
  "recipient_count": 50
}
```

**Bulk Resolved — `GET /api/v1/contact/draft/{job_id}` → `200 OK`**

```json
{
  "job_id": "<uuid>",
  "status": "completed",
  "drafts": [
    {
      "candidate_id": "<uuid>",
      "subject": "...",
      "body": "...",
      "merge_fields_used": ["[Name]", "[Job Title]"],
      "error": null
    }
  ]
}
```

---

## 9. Feature 5 — AI Ranking

### 9.1 Purpose

Score all candidates who applied for a job role against LLM-generated scoring criteria derived from the JD. Criteria are persisted in the database when a JD is finalised and retrieved at ranking time. The system returns a ranked list of candidates with individual scores and per-criterion rationale.

### 9.2 API Endpoints

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/api/v1/ranking/criteria` | Generate and persist scoring criteria for a JD |
| `GET` | `/api/v1/ranking/criteria/{jd_id}` | Retrieve stored scoring criteria for a JD |
| `POST` | `/api/v1/ranking/score` | Asynchronously score all candidates for a job |
| `GET` | `/api/v1/ranking/score/{job_id}` | Poll scoring job status and results |

### 9.3 Generate Criteria — `POST /api/v1/ranking/criteria`

**Request Body (JSON)**

| Field | Description |
|---|---|
| `jd_id` | (string, required) Finalised JD to derive criteria from |
| `jd_file` | (File, required) PDF/DOCX/HTML file of the JD | 

**Response — `201 Created`**

```json
{
  "jd_id": "<uuid>",
  "criteria_id": "<uuid>",
  "generated_at": "2026-04-27T10:00:00Z",
  "criteria": [
    {
      "criterion_name": "Technical Skills Match",
      "description": "Degree to which the candidate's skills align with required stack",
      "weight": 0.35,
      "scoring_scale": "0–10"
    }
  ]
}
```

> Criteria are persisted to the database linked to `jd_id`. A subsequent call for the same `jd_id` **overwrites** existing criteria.

### 9.4 Score Candidates — `POST /api/v1/ranking/score`

**Request Body (JSON)**

| Field | Description |
|---|---|
| `jd_id` | (string, required) Criteria are fetched from DB via this ID |
| `candidate_ids` | (array of strings, required) Candidate UUIDs to score |

**Response — `202 Accepted`**

```json
{
  "job_id": "<uuid>",
  "status": "queued",
  "candidate_count": 120
}
```

  The resume of the candidates are retrieved from the Qdrant. Qdrant has the resume chunks with section name and section text. By combining all the sections, candidate full resume can be created.

### 9.5 Scoring Results — `GET /api/v1/ranking/score/{job_id}` → `200 OK`

```json
{
  "job_id": "<uuid>",
  "jd_id": "<uuid>",
  "status": "completed",
  "completed_at": "2026-04-27T10:05:00Z",
  "results": [
    {
  "vacancy": {
    "title": "Community and Digital Programs Officer, Marketing"
  },
  "overall_match": {
    "percentage": 94,
    "requirements_met": {
      "met": 10,
      "total": 11
    }
  },
  "hold": {
    "status": "clear",
    "red_flags": {
      "count": 0,
      "items": []
    }
  },
  "alerts": [],
  "requirement_detail": {
    "skills": {
      "percentage": 100,
      "met": 7,
      "total": 7,
      "items": [
        {
          "name": "Digital marketing",
          "type": "Skill",
          "priority": "must-have",
          "status": "met"
        },
        {
          "name": "Community engagement",
          "type": "Skill",
          "priority": "must-have",
          "status": "met"
        },
        {
          "name": "Content strategy",
          "type": "Skill",
          "priority": "must-have",
          "status": "met"
        },
        {
          "name": "Social media management",
          "type": "Skill",
          "priority": "must-have",
          "status": "met"
        },
        {
          "name": "SEO/Analytics",
          "type": "Skill",
          "priority": "good-to-have",
          "status": "met"
        },
        {
          "name": "Stakeholder communication",
          "type": "Soft skill",
          "priority": "good-to-have",
          "status": "met"
        },
        {
          "name": "Event coordination",
          "type": "Skill",
          "priority": "good-to-have",
          "status": "met"
        }
      ]
    },
    "experience": {
      "percentage": 0,
      "met": 0,
      "total": 2,
      "items": [
        {
          "name": "3+ years community programs",
          "type": "Experience",
          "priority": "must-have",
          "status": "Not met"
        },
        {
          "name": "Marketing/digital sector",
          "type": "Domain",
          "priority": "good-to-have",
          "status": "Not met"
        }
      ]
    },
    "qualifications": {
      "percentage": 33,
      "met": 1,
      "total": 3,
      "items": [
        {
          "name": "Master's Degree",
          "type": "Education",
          "priority": "must-have",
          "status": "Not met"
        },
        {
          "name": "Bachelor's Degree",
          "type": "Education",
          "priority": "must-have",
          "status": "Met"
        },
        {
          "name": "Digital marketing certification",
          "type": "Credential",
          "priority": "good-to-have",
          "status": "Not met"
        }
      ]
    }
  }
}
  ]
}
```

---

## 10. Non-Functional Requirements

### 10.1 Performance

| Operation | Target (p95) |
|---|---|
| Resume parse (sync portion) | < 3 seconds |
| Resume summary (cache miss) | < 8 seconds |
| Bulk contact draft (50 recipients) | < 60 seconds |
| AI scoring (100 candidates) | < 5 minutes |

### 10.2 Reliability

- All background workers support at-least-once delivery with idempotent job processing.
- Failed jobs are retried up to 3 times with exponential back-off before moving to a dead-letter queue.
- Job status endpoints return a consistent schema regardless of success or failure.

### 10.3 Security

- PII fields are encrypted at rest (AES-256) and in transit (TLS 1.3).
- Rate limiting: 60 requests/minute per authenticated user; 10 requests/minute for bulk operations.
- Uploaded files are scanned for malware before processing.

### 10.4 Scalability

- Worker pools auto-scale based on queue depth.
- Redis cache cluster supports horizontal sharding.
- Vector store must support at least 1 million chunks at launch.

---

## 11. Error Handling

All error responses follow a consistent envelope:

```json
{
  "error_code": "REFINEMENT_LIMIT_REACHED",
  "message": "You have used all 5 refinements for this session.",
  "details": [],
  "request_id": "<uuid>"
}
```

**Standard HTTP status codes used:**

| Code | Meaning |
|---|---|
| `400` | Bad Request — malformed input |
| `401` | Unauthorized — missing or expired token |
| `403` | Forbidden — insufficient role |
| `404` | Not Found |
| `413` | Payload Too Large — file exceeds size limit |
| `422` | Unprocessable Entity — validation failure |
| `429` | Too Many Requests — rate limit or refinement cap hit |
| `500` | Internal Server Error |
| `503` | Service Unavailable — queue or LLM unreachable |

---

## 12. Key Dependencies

| Component | Technology |
|---|---|
| LLM Provider | Configurable (OpenAI GPT-4.1 / Anthropic Claude / internal model) |
| PII Scrubbing | Nvidia GLiNER (self-hosted) |
| Job Queue | Celery + Redis or BullMQ — to be finalised in technical design |
| Cache | Redis 7+ |
| Vector Store | Qdrant / Weaviate / Pinecone — to be finalised |
| Dense Embeddings | `sentence-transformers` (e.g., `all-MiniLM-L6-v2`) |
| Sparse Embeddings | BM25 / TF-IDF |
| Auth | JWT (RS256) or OAuth 2.0 (Authorization Code / Client Credentials) |
| File Parsing | PyMuPDF (PDF), python-docx (DOCX) |

---

## 13. Open Questions

- **Queue technology**: Celery (Python-first)
- **Vector store**: Self-hosted Qdrant
- **Refinement session storage**: Redis session key vs. JWT-embedded claim?
- **Scoring criteria versioning**: Should updating a JD invalidate existing criteria and trigger re-scoring? This is not decided yet.
- **Bulk email delivery**: return drafts for an external mail service.
---

## 14. Revision History

| Version | Date | Changes | Author |
|---|---|---|---|
| 0.1 | April 2026 | Initial draft based on stakeholder notes | Product Team |
| 1.0 | April 2026 | Full refinement: API specs, auth, caching, async patterns, error handling, NFRs | Claude AI |
