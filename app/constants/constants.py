"""Constant variables"""

# Contact Draft
CONTACT_INPUT_TYPE_TEMPLATE = "template"
CONTACT_INPUT_TYPE_RAW_TEXT = "raw_text"

# JD Creator
MAX_REFINEMENTS = 6
JD_INPUT_TYPE_RAW_TEXT = "raw_text"
JD_INPUT_TYPE_TEMPLATE = "template"
JD_INPUT_TYPE_DETAILS = "details"

# Resume Parser — file validation
ALLOWED_RESUME_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
MAX_RESUME_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB

# Resume Parser — PII scrubbing
GLINER_MODEL_NAME = "urchade/gliner_multi_pii-v1"
GLINER_PII_LABELS = [
    "person",
    "email address",
    "phone number",
    "address",
    "date of birth",
    "gender",
]

# Resume Parser — job statuses
JOB_STATUS_PENDING = "pending"
JOB_STATUS_PROCESSING = "processing"
JOB_STATUS_COMPLETED = "completed"
JOB_STATUS_FAILED = "failed"

# Resume Parser — chunking
RESUME_SECTIONS = [
    "professional_summary",
    "contact_information",
    "social_media_profile",
    "work_experience",
    "education",
    "skills",
    "certifications",
    "professional_affiliations",
    "publications",
    "achievements",
    "projects",
    "additional_professional_experience",
    "languages",
    "hobbies",
    "others",
]
# Resume Summary
SUMMARY_PII_LABELS = ["person", "email", "phone number", "address", "date of birth", "location"]
SUMMARY_PII_PLACEHOLDERS = {
    "person": "[NAME]",
    "email": "[EMAIL]",
    "phone number": "[PHONE]",
    "address": "[ADDRESS]",
    "date of birth": "[DOB]",
    "location": "[LOCATION]",
}
