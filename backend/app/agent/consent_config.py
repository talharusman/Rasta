# OWNER: Member 3
# What the agent asks consent for. TODO(M1): confirm the real department id and scope
# names with Member 1's consent module and change them here only.
import os

PROCESSING_DEPARTMENT_ID = os.getenv("PROCESSING_DEPARTMENT_ID", "relief-processing")
PROCESSING_SCOPE = os.getenv("PROCESSING_CONSENT_SCOPE", "case_processing")
