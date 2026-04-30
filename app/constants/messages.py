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
JD_GENERATE_FIELD_REQUIRED = "{field} is required when input_type is '{input_type}'."
