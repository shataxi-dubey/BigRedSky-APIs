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

# Contact Draft
CONTACT_DRAFTED = "Email draft generated successfully."
CONTACT_DRAFT_PARSE_ERROR = "Failed to parse the LLM response for the email draft."

# JD Creator
JD_GENERATED = "Job description generated successfully."
JD_REPHRASED = "Text rephrased successfully."
JD_REFINED = "Job description refined successfully."
REFINEMENT_LIMIT_REACHED = "You have used all 5 refinements for this session."
JD_SESSION_NOT_FOUND = "No JD session found for session_id={session_id}."
JD_GENERATE_FIELD_REQUIRED = "{field} is required when input_type is '{input_type}'."

# Resume Parser
RESUME_PARSE_COMPLETED = "Resume parsed successfully. Chunking started in background."
RESUME_PARSE_RETRY_COMPLETED = "Resume re-parsed successfully."
RESUME_INVALID_FILE_TYPE = "Only PDF and DOCX files are supported."
RESUME_FILE_TOO_LARGE = "File exceeds the 10 MB limit."
RESUME_CHUNK_NOT_FOUND = "No chunking job found for candidate_id={candidate_id}."
RESUME_PARSE_NOT_FOUND = "No parse job found for job_id={job_id}."
RESUME_JOB_NOT_RETRYABLE = "Job cannot be retried — current status is '{status}'. Only failed jobs can be retried."
RESUME_CHUNK_RETRY_QUEUED = "Chunk job re-queued successfully."
# Resume Summary
RESUME_SUMMARY_GENERATED = "Resume summary generated successfully."
RESUME_SUMMARY_NOT_FOUND = "No summary found for the given candidate and JD."
RESUME_SUMMARY_PARSE_ERROR = "Failed to parse the LLM response for the resume summary."
RESUME_S3_FETCH_ERROR = "Failed to fetch resume file from S3."
RESUME_PARSE_ERROR = "Failed to extract text from resume file."
