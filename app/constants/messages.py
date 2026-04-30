"""Application messages"""

# Error Messages
UNAUTHORIZED = "Unauthorized User"
SERVER_ERROR = "Server Error."
INVALID_DATA = "Invalid {}"
INTERNAL_SERVER_ERROR = "Internal Server Error"
PYDANTIC_VALIDATION_ERROR = "Validation Error"
NOT_AUTHENTICATED = "Not Authenticated"
NOT_FOUND = "Not Found"
INVALID_CREDENTIALS = "Invalid Credentials"
RATE_LIMIT_ERROR = "Rate limit exceeded. Try again in {retry_after} seconds."

# JD Creator
JD_GENERATED = "Job description generated successfully."
JD_REPHRASED = "Text rephrased successfully."
JD_REFINED = "Job description refined successfully."
REFINEMENT_LIMIT_REACHED = "You have used all 5 refinements for this session."
JD_GENERATE_FIELD_REQUIRED = "{field} is required when input_type is '{input_type}'."

# Resume Summary
RESUME_SUMMARY_GENERATED = "Resume summary generated successfully."
RESUME_SUMMARY_DELETED = "Resume summary deleted successfully."
RESUME_SUMMARY_NOT_FOUND = "No summary found for the given candidate and JD."
RESUME_SUMMARY_PARSE_ERROR = "Failed to parse the LLM response for the resume summary."
RESUME_S3_FETCH_ERROR = "Failed to fetch resume file from S3."
RESUME_PARSE_ERROR = "Failed to extract text from resume file."
