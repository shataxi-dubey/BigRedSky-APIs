"""Constant variables"""

# JD Creator
MAX_REFINEMENTS = 5
JD_INPUT_TYPE_RAW_TEXT = "raw_text"
JD_INPUT_TYPE_TEMPLATE = "template"
JD_INPUT_TYPE_DETAILS = "details"

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
