"""Streamlit UI for the JD Creator — Generate · Rephrase · Refine."""

import json

import requests
import streamlit as st

API_BASE = "http://localhost:8002/api/v1"

st.set_page_config(page_title="JD Creator", page_icon="📝", layout="wide")
st.title("📝 Job Description Creator")

# ------------------------------------------------------------------
# Session state defaults
# ------------------------------------------------------------------
defaults = {
    "current_jd": "",
    "refine_messages": [],
    "refinements_remaining": 5,
    "rephrase_original": "",
    "rephrase_result": "",
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ------------------------------------------------------------------
# SSE stream helper
# ------------------------------------------------------------------
def _iter_sse(url: str, payload: dict):
    current_event = None
    with requests.post(url, json=payload, stream=True, timeout=120) as r:
        r.raise_for_status()
        for raw_line in r.iter_lines(decode_unicode=True):
            if raw_line.startswith("event:"):
                current_event = raw_line.split(":", 1)[1].strip()
            elif raw_line.startswith("data:"):
                data = raw_line.split(":", 1)[1].strip()
                if current_event == "content":
                    try:
                        yield json.loads(data)
                    except json.JSONDecodeError:
                        yield data
                elif current_event == "metadata":
                    try:
                        meta = json.loads(data)
                        if "refinements_remaining" in meta:
                            st.session_state.refinements_remaining = meta["refinements_remaining"]
                    except json.JSONDecodeError:
                        pass
                elif current_event == "complete":
                    break


# ══════════════════════════════════════════════════════════════════
# SECTION 1 — GENERATE FORM
# ══════════════════════════════════════════════════════════════════
st.subheader("Generate a Job Description")

input_type = st.radio(
    "Input type",
    options=["raw_text", "template", "details"],
    format_func=lambda x: {"raw_text": "Raw Text", "template": "Template", "details": "Structured Details"}[x],
    horizontal=True,
)

payload: dict = {"input_type": input_type}

if input_type == "raw_text":
    raw_text = st.text_area(
        "Describe the role in your own words",
        height=120,
        placeholder="e.g. Senior Python developer for a fintech startup, 5+ years experience…",
    )
    payload["raw_text"] = raw_text

elif input_type == "template":
    template = st.text_area(
        "Paste your template",
        height=180,
        placeholder="Job Title: {{title}}\nLocation: {{location}}\n…",
    )
    payload["template"] = template

else:
    col1, col2 = st.columns(2)
    with col1:
        job_title = st.text_input("Job Title", placeholder="Senior Software Engineer")
        department = st.text_input("Department", placeholder="Engineering")
        location = st.text_input("Location", placeholder="Remote / New York, NY")
    with col2:
        employment_type = st.selectbox(
            "Employment Type", ["Full-time", "Part-time", "Contract", "Internship"]
        )
        compensation_range = st.text_input("Compensation Range", placeholder="$120,000 – $150,000")

    responsibilities = st.text_area(
        "Responsibilities (one per line)", height=100,
        placeholder="Design and build backend APIs\nMentor junior engineers",
    )
    required_skills = st.text_area(
        "Required Skills (one per line)", height=80,
        placeholder="Python\nFastAPI\nPostgreSQL",
    )
    preferred_skills = st.text_area(
        "Preferred Skills (one per line)", height=60,
        placeholder="Docker\nKubernetes",
    )
    payload["details"] = {
        "job_title": job_title,
        "department": department,
        "location": location,
        "employment_type": employment_type,
        "compensation_range": compensation_range,
        "responsibilities": [r.strip() for r in responsibilities.splitlines() if r.strip()],
        "required_skills": [s.strip() for s in required_skills.splitlines() if s.strip()],
        "preferred_skills": [s.strip() for s in preferred_skills.splitlines() if s.strip()],
    }

generate_clicked = st.button("✨ Generate JD", type="primary")

# ══════════════════════════════════════════════════════════════════
# SECTION 2 — PERSISTENT JD DISPLAY
# This placeholder is created once and updated in-place by both
# generate and refine, so the content never disappears on rerun.
# ══════════════════════════════════════════════════════════════════
if st.session_state.current_jd or generate_clicked:
    st.divider()
    st.subheader("Generated Job Description")
    st.caption(
        "Select and copy any passage from the text below to rephrase it, "
        "or give an instruction to refine the whole JD."
    )

# Persistent placeholder — lives here in the script's top-level flow
jd_placeholder = st.empty()
if st.session_state.current_jd and not generate_clicked:
    jd_placeholder.markdown(st.session_state.current_jd)

# ── Handle generate ───────────────────────────────────────────────
if generate_clicked:
    full_text = ""
    with st.spinner("Generating…"):
        try:
            for token in _iter_sse(f"{API_BASE}/jd/generate", payload):
                full_text += token
                jd_placeholder.markdown(full_text + "▌")
            jd_placeholder.markdown(full_text)
            st.session_state.current_jd = full_text
            st.session_state.refine_messages = []
            st.session_state.refinements_remaining = 5
            st.session_state.rephrase_original = ""
            st.session_state.rephrase_result = ""
        except requests.HTTPError as e:
            st.error(f"API error {e.response.status_code}: {e.response.text}")
        except Exception as e:
            st.error(f"Error: {e}")

# ══════════════════════════════════════════════════════════════════
# SECTION 3 — REPHRASE & REFINE (only once a JD exists)
# ══════════════════════════════════════════════════════════════════
if st.session_state.current_jd:
    st.divider()
    col_rephrase, col_refine = st.columns([1, 1], gap="large")

    # ── Rephrase ──────────────────────────────────────────────────
    with col_rephrase:
        st.subheader("✏️ Rephrase a Section")
        st.caption("Copy a passage from the JD above and paste it here.")

        selected_text = st.text_area(
            "Text to rephrase",
            height=120,
            placeholder="Paste the exact passage you want rephrased…",
            key="rephrase_input",
        )
        tone = st.selectbox(
            "Tone",
            options=["", "professional", "formal", "inclusive", "concise", "friendly"],
            format_func=lambda x: "— keep original tone —" if x == "" else x.capitalize(),
        )

        if st.button("✏️ Rephrase", type="primary", disabled=not selected_text.strip()):
            with st.spinner("Rephrasing…"):
                try:
                    resp = requests.post(
                        f"{API_BASE}/jd/rephrase",
                        json={"jd_id": "current", "selected_text": selected_text, "tone": tone or None},
                        timeout=30,
                    )
                    resp.raise_for_status()
                    data = resp.json().get("data", {})
                    st.session_state.rephrase_original = data.get("original_text", "")
                    st.session_state.rephrase_result = data.get("rephrased_text", "")
                except requests.HTTPError as e:
                    st.error(f"API error {e.response.status_code}: {e.response.text}")
                except Exception as e:
                    st.error(f"Error: {e}")

        if st.session_state.rephrase_result:
            st.markdown("**Original**")
            st.info(st.session_state.rephrase_original)
            st.markdown("**Rephrased**")
            st.success(st.session_state.rephrase_result)

            if st.button("Apply to JD", key="btn_apply"):
                updated = st.session_state.current_jd.replace(
                    st.session_state.rephrase_original,
                    st.session_state.rephrase_result,
                    1,
                )
                st.session_state.current_jd = updated
                st.session_state.rephrase_original = ""
                st.session_state.rephrase_result = ""
                # Update the persistent placeholder without rerun
                jd_placeholder.markdown(updated)

    # ── Refine ────────────────────────────────────────────────────
    with col_refine:
        remaining = st.session_state.refinements_remaining
        st.subheader("🔁 Refine the JD")
        st.caption(f"Refinements remaining this session: **{remaining} / 5**")

        instruction = st.text_input(
            "Refinement instruction",
            placeholder="e.g. Make the tone more inclusive and add a DEI statement",
            disabled=(remaining <= 0),
        )

        if st.button("🔁 Refine", type="primary", disabled=(remaining <= 0 or not instruction.strip())):
            messages = list(st.session_state.refine_messages)
            current_jd = st.session_state.current_jd
            if not messages or messages[-1].get("content") != current_jd:
                messages.append({"role": "assistant", "content": current_jd})

            refine_payload = {
                "instruction": instruction,
                "messages": messages,
                "refinements_remaining": remaining,
            }

            full_text = ""
            with st.spinner("Refining…"):
                try:
                    for token in _iter_sse(f"{API_BASE}/jd/refine", refine_payload):
                        full_text += token
                        # Stream directly into the persistent JD placeholder above
                        jd_placeholder.markdown(full_text + "▌")
                    jd_placeholder.markdown(full_text)

                    messages.append({"role": "user", "content": instruction})
                    messages.append({"role": "assistant", "content": full_text})
                    st.session_state.refine_messages = messages
                    st.session_state.current_jd = full_text

                except requests.HTTPError as e:
                    if e.response.status_code == 429:
                        st.error("Refinement limit reached (5/5). Reset below to start a new session.")
                    else:
                        st.error(f"API error {e.response.status_code}: {e.response.text}")
                except Exception as e:
                    st.error(f"Error: {e}")

        if remaining <= 0:
            st.warning("All 5 refinements used.")
            if st.button("🔄 Reset refinements"):
                st.session_state.refine_messages = []
                st.session_state.refinements_remaining = 5
                st.rerun()
